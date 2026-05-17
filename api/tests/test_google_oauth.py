"""Tests for the Google OAuth flow (`api.services.auth.google_oauth`).

These tests mock httpx, the Redis-backed state store, and db_client so
they run without external services. We exercise the full request-cycle
through `start_oauth` and `handle_callback`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import HTTPException

from api.services.auth import google_oauth


def _fake_user(user_id: int = 42, email: str | None = None, provider_id: str = "google:sub-x"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    u.provider_id = provider_id
    u.selected_organization_id = None
    return u


def _response(status_code: int, json_body=None, text: str = "") -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    if json_body is not None:
        r.json.return_value = json_body
    else:
        r.json.side_effect = ValueError("not json")
    r.text = text
    return r


@pytest.fixture(autouse=True)
def enable_oauth(monkeypatch):
    """Enable the feature + set credentials for every test in this file.
    Individual tests override when they want to exercise the disabled path."""
    monkeypatch.setattr(google_oauth, "GOOGLE_OAUTH_ENABLED", True)
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        google_oauth, "GOOGLE_OAUTH_REDIRECT_URI",
        "https://voice.noral.ai/api/v1/auth/google/callback",
    )
    monkeypatch.setattr(
        google_oauth, "GOOGLE_OAUTH_POST_LOGIN_REDIRECT",
        "https://voice.noral.ai/after-sign-in",
    )


@pytest.fixture
def mock_state_store():
    """Replace the Redis-backed state store with a simple in-memory dict."""
    store: dict[str, dict] = {}

    async def fake_put(state: str, payload: dict, ttl_seconds: int = 600) -> None:
        store[state] = payload

    async def fake_pop(state: str):
        return store.pop(state, None)

    with patch.object(google_oauth.oauth_state, "put", side_effect=fake_put), \
         patch.object(google_oauth.oauth_state, "pop", side_effect=fake_pop):
        yield store


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient. Tests configure .post/.get on the returned
    instance; both are AsyncMocks."""
    client_instance = AsyncMock()
    async_ctx = AsyncMock()
    async_ctx.__aenter__.return_value = client_instance
    async_ctx.__aexit__.return_value = False
    with patch("api.services.auth.google_oauth.httpx.AsyncClient", return_value=async_ctx):
        yield client_instance


@pytest.fixture
def mock_db_client():
    """Mock db_client on google_oauth's namespace."""
    with patch("api.services.auth.google_oauth.db_client") as db:
        db.get_user_by_email = AsyncMock(return_value=None)
        db.create_user_with_provider = AsyncMock(
            return_value=_fake_user(user_id=10, email="new@example.com"),
        )
        yield db


@pytest.fixture(autouse=True)
def mock_posthog():
    """No-op the PostHog capture so tests don't issue network calls."""
    with patch("api.services.auth.google_oauth.capture_event") as ce:
        yield ce


# ===========================================================================
# start_oauth — 503 when disabled, otherwise 302 to Google with state + PKCE
# ===========================================================================


@pytest.mark.asyncio
async def test_start_503_when_disabled(monkeypatch, mock_state_store):
    monkeypatch.setattr(google_oauth, "GOOGLE_OAUTH_ENABLED", False)
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.start_oauth(request=MagicMock())
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_start_503_when_credentials_missing(monkeypatch, mock_state_store):
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", None)
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.start_oauth(request=MagicMock())
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_start_redirects_to_google_with_state(mock_state_store):
    response = await google_oauth.start_oauth(request=MagicMock())

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")

    params = parse_qs(urlparse(location).query)
    assert params["client_id"] == ["test-client-id"]
    assert params["redirect_uri"] == ["https://voice.noral.ai/api/v1/auth/google/callback"]
    assert params["response_type"] == ["code"]
    assert "openid" in params["scope"][0]
    assert "email" in params["scope"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["state"][0]) > 20
    assert len(params["code_challenge"][0]) > 20


@pytest.mark.asyncio
async def test_start_stores_state_with_verifier(mock_state_store):
    response = await google_oauth.start_oauth(request=MagicMock())
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert state in mock_state_store
    assert "code_verifier" in mock_state_store[state]
    assert isinstance(mock_state_store[state]["code_verifier"], str)


# ===========================================================================
# handle_callback — rejection paths (state, code, email_verified)
# ===========================================================================


@pytest.mark.asyncio
async def test_callback_rejects_missing_code(mock_state_store):
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code=None, state="abc")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_missing_state(mock_state_store):
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="abc", state=None)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state(mock_state_store):
    """Replay defense: a state we never issued (or that already got popped)
    is rejected. Note this test also covers the 'expired state' case since
    expiry just removes the entry from Redis — same observable behaviour."""
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="some-code", state="never-issued")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_state_is_single_use(mock_state_store, mock_httpx_client, mock_db_client):
    """Second callback with the same state must fail — Redis GETDEL pops
    the entry on first use."""
    mock_state_store["good-state"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub", "email": "a@b.com", "email_verified": True},
    )

    await google_oauth.handle_callback(code="c", state="good-state")
    # Second call: same state should be rejected.
    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="c", state="good-state")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_unverified_email(mock_state_store, mock_httpx_client, mock_db_client):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub", "email": "x@y.com", "email_verified": False},
    )

    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="c", state="s")
    assert exc_info.value.status_code == 403
    assert "verified email" in exc_info.value.detail.lower()


# ===========================================================================
# handle_callback — Google API error paths
# ===========================================================================


@pytest.mark.asyncio
async def test_callback_handles_google_token_endpoint_error(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(
        400, json_body={"error": "invalid_grant"}, text='{"error":"invalid_grant"}',
    )

    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="c", state="s")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_handles_token_endpoint_network_error(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.side_effect = httpx.ConnectError("dns")

    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="c", state="s")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_callback_handles_userinfo_endpoint_error(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(500, text="oops")

    with pytest.raises(HTTPException) as exc_info:
        await google_oauth.handle_callback(code="c", state="s")
    assert exc_info.value.status_code == 502


# ===========================================================================
# handle_callback — happy paths (create vs link, cookie set, redirect)
# ===========================================================================


@pytest.mark.asyncio
async def test_callback_creates_local_user_first_time(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub-new", "email": "new@example.com", "email_verified": True},
    )

    new_user = _fake_user(user_id=99, email="new@example.com", provider_id="google:google-sub-new")
    mock_db_client.get_user_by_email.return_value = None
    mock_db_client.create_user_with_provider.return_value = new_user

    response = await google_oauth.handle_callback(code="c", state="s")

    assert response.status_code == 302
    mock_db_client.create_user_with_provider.assert_awaited_once_with(
        email="new@example.com", provider_id="google:google-sub-new",
    )


@pytest.mark.asyncio
async def test_callback_links_to_existing_user_by_email(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    """Existing local user (e.g. created via email/password) signing in
    via Google for the first time should be linked by email — NOT
    duplicated into a new row."""
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub-x", "email": "existing@example.com", "email_verified": True},
    )

    existing_user = _fake_user(user_id=5, email="existing@example.com", provider_id="oss_old")
    mock_db_client.get_user_by_email.return_value = existing_user

    response = await google_oauth.handle_callback(code="c", state="s")

    assert response.status_code == 302
    mock_db_client.create_user_with_provider.assert_not_called()


@pytest.mark.asyncio
async def test_callback_redirects_to_post_login_url(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub", "email": "a@b.com", "email_verified": True},
    )
    mock_db_client.get_user_by_email.return_value = _fake_user(user_id=1, email="a@b.com")

    response = await google_oauth.handle_callback(code="c", state="s")
    assert response.headers["location"] == "https://voice.noral.ai/after-sign-in"


@pytest.mark.asyncio
async def test_callback_sets_session_cookies(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    """The callback must set BOTH the new noralvoice_* cookies AND the
    legacy dograh_* cookies (PHASE-5 dual-write window) so the existing
    Next.js middleware reads either name transparently."""
    mock_state_store["s"] = {"code_verifier": "v"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub", "email": "a@b.com", "email_verified": True},
    )
    mock_db_client.get_user_by_email.return_value = _fake_user(user_id=7, email="a@b.com")

    response = await google_oauth.handle_callback(code="c", state="s")
    set_cookie_headers = response.headers.getlist("set-cookie")
    cookie_str = "\n".join(set_cookie_headers)

    assert "noralvoice_auth_token=" in cookie_str
    assert "noralvoice_auth_user=" in cookie_str
    assert "dograh_auth_token=" in cookie_str
    assert "dograh_auth_user=" in cookie_str
    assert "HttpOnly" in cookie_str
    assert "SameSite=lax" in cookie_str
    # No Domain attribute → host-only, matches the Next.js session route.
    assert "Domain=" not in cookie_str


@pytest.mark.asyncio
async def test_callback_posts_pkce_verifier_to_token_endpoint(
    mock_state_store, mock_httpx_client, mock_db_client,
):
    """The PKCE code_verifier stored at start must be forwarded to Google's
    token endpoint — otherwise PKCE doesn't actually validate anything."""
    mock_state_store["s"] = {"code_verifier": "my-secret-verifier"}
    mock_httpx_client.post.return_value = _response(200, {"access_token": "tok"})
    mock_httpx_client.get.return_value = _response(
        200, {"sub": "google-sub", "email": "a@b.com", "email_verified": True},
    )
    mock_db_client.get_user_by_email.return_value = _fake_user(user_id=1, email="a@b.com")

    await google_oauth.handle_callback(code="auth-code-from-google", state="s")

    post_kwargs = mock_httpx_client.post.await_args.kwargs
    data = post_kwargs["data"]
    assert data["code_verifier"] == "my-secret-verifier"
    assert data["code"] == "auth-code-from-google"
    assert data["grant_type"] == "authorization_code"
    assert data["client_id"] == "test-client-id"
    assert data["client_secret"] == "test-client-secret"
