"""Tests for the cross-product SSO module (`api.services.auth.noral_sso`).

The module forwards an inbound Cookie header to agent.noral.ai's Better
Auth session endpoint and maps the returned user to a local user.

These tests mock both the outbound httpx call and `db_client` so they
run without a database or a live agent.noral.ai.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.services.auth.noral_sso import (
    DEFAULT_VALIDATE_URL,
    get_user_from_noralos_session,
)


def _fake_user(user_id: int = 42, email: str | None = None) -> MagicMock:
    """Build a minimal UserModel-shaped mock."""
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _response(status_code: int, json_body=None, text: str = "") -> MagicMock:
    """Build an httpx.Response stub."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    if json_body is not None:
        r.json.return_value = json_body
    else:
        r.json.side_effect = ValueError("not json")
    r.text = text
    return r


@pytest.fixture
def mock_db_client():
    """Patch the db_client used by noral_sso."""
    with patch("api.services.auth.noral_sso.db_client") as db:
        db.get_or_create_user_by_provider_id = AsyncMock(
            return_value=(_fake_user(user_id=10, email=None), True),
        )
        db.update_user_email = AsyncMock()
        yield db


@pytest.fixture
def mock_httpx_client():
    """Patch httpx.AsyncClient so we control responses."""
    client_instance = AsyncMock()
    async_ctx = AsyncMock()
    async_ctx.__aenter__.return_value = client_instance
    async_ctx.__aexit__.return_value = False
    with patch("api.services.auth.noral_sso.httpx.AsyncClient", return_value=async_ctx):
        yield client_instance


# ===========================================================================
# Cookie-missing path: short-circuit before any network call
# ===========================================================================


@pytest.mark.asyncio
async def test_no_cookie_header_returns_none_without_network_call(mock_httpx_client):
    result = await get_user_from_noralos_session(None)
    assert result is None
    mock_httpx_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_empty_cookie_header_returns_none_without_network_call(mock_httpx_client):
    result = await get_user_from_noralos_session("")
    assert result is None
    mock_httpx_client.get.assert_not_called()


# ===========================================================================
# Network failure path: never silently pass
# ===========================================================================


@pytest.mark.asyncio
async def test_network_error_returns_none(mock_httpx_client):
    mock_httpx_client.get.side_effect = httpx.ConnectError("agent.noral.ai unreachable")
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


@pytest.mark.asyncio
async def test_timeout_returns_none(mock_httpx_client):
    mock_httpx_client.get.side_effect = httpx.ReadTimeout("slow agent")
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


# ===========================================================================
# HTTP status path: 401 quiet, other non-200 logged
# ===========================================================================


@pytest.mark.asyncio
async def test_401_returns_none_quietly(mock_httpx_client):
    mock_httpx_client.get.return_value = _response(401)
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


@pytest.mark.asyncio
async def test_5xx_returns_none(mock_httpx_client):
    mock_httpx_client.get.return_value = _response(503, text="upstream busy")
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


# ===========================================================================
# Malformed payload paths
# ===========================================================================


@pytest.mark.asyncio
async def test_non_json_body_returns_none(mock_httpx_client):
    mock_httpx_client.get.return_value = _response(200, json_body=None, text="<html>")
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


@pytest.mark.asyncio
async def test_missing_user_field_returns_none(mock_httpx_client):
    mock_httpx_client.get.return_value = _response(200, json_body={"session": {}})
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


@pytest.mark.asyncio
async def test_user_without_id_returns_none(mock_httpx_client):
    mock_httpx_client.get.return_value = _response(
        200, json_body={"user": {"email": "q@noral.ai"}},
    )
    result = await get_user_from_noralos_session("noralos-default.session_token=abc")
    assert result is None


# ===========================================================================
# Happy paths: user found/created, email synced
# ===========================================================================


@pytest.mark.asyncio
async def test_valid_session_returns_local_user(mock_httpx_client, mock_db_client):
    mock_httpx_client.get.return_value = _response(
        200,
        json_body={
            "user": {"id": "ba-user-xyz", "email": "q@noral.ai", "name": "Quentin"},
            "session": {"id": "sess-1"},
        },
    )

    existing_user = _fake_user(user_id=5, email="q@noral.ai")
    mock_db_client.get_or_create_user_by_provider_id.return_value = (existing_user, False)

    result = await get_user_from_noralos_session(
        "noralos-default.session_token=abc; other=val",
    )

    assert result is existing_user
    mock_db_client.get_or_create_user_by_provider_id.assert_awaited_once_with(
        provider_id="noralos:ba-user-xyz",
    )
    # Email already matches → no update.
    mock_db_client.update_user_email.assert_not_called()


@pytest.mark.asyncio
async def test_email_synced_on_first_sign_in(mock_httpx_client, mock_db_client):
    """When the local user has no email yet, copy the agent.noral.ai one."""
    mock_httpx_client.get.return_value = _response(
        200,
        json_body={
            "user": {"id": "ba-user-xyz", "email": "q@noral.ai"},
        },
    )

    fresh_user = _fake_user(user_id=99, email=None)
    mock_db_client.get_or_create_user_by_provider_id.return_value = (fresh_user, True)

    result = await get_user_from_noralos_session(
        "noralos-default.session_token=abc",
    )

    assert result is fresh_user
    mock_db_client.update_user_email.assert_awaited_once_with(99, "q@noral.ai")
    assert result.email == "q@noral.ai"


@pytest.mark.asyncio
async def test_no_email_in_payload_skips_email_sync(mock_httpx_client, mock_db_client):
    mock_httpx_client.get.return_value = _response(
        200,
        json_body={"user": {"id": "ba-user-xyz"}},
    )
    fresh_user = _fake_user(user_id=100, email=None)
    mock_db_client.get_or_create_user_by_provider_id.return_value = (fresh_user, True)

    result = await get_user_from_noralos_session(
        "noralos-default.session_token=abc",
    )

    assert result is fresh_user
    mock_db_client.update_user_email.assert_not_called()


# ===========================================================================
# Cookie header is forwarded verbatim + env var overrides URL
# ===========================================================================


@pytest.mark.asyncio
async def test_cookie_header_forwarded_verbatim(mock_httpx_client, mock_db_client):
    mock_httpx_client.get.return_value = _response(
        200, json_body={"user": {"id": "ba-user-xyz"}},
    )
    fresh_user = _fake_user(user_id=200)
    mock_db_client.get_or_create_user_by_provider_id.return_value = (fresh_user, True)

    cookie_header = "noralos-default.session_token=abc123; other=stuff"
    await get_user_from_noralos_session(cookie_header)

    call_kwargs = mock_httpx_client.get.await_args.kwargs
    assert call_kwargs["headers"] == {"Cookie": cookie_header}


@pytest.mark.asyncio
async def test_env_var_overrides_validate_url(mock_httpx_client, mock_db_client, monkeypatch):
    monkeypatch.setenv(
        "NORALOS_SESSION_VALIDATE_URL",
        "https://staging.agent.noral.ai/api/auth/get-session",
    )
    mock_httpx_client.get.return_value = _response(
        200, json_body={"user": {"id": "ba-user-xyz"}},
    )
    mock_db_client.get_or_create_user_by_provider_id.return_value = (
        _fake_user(user_id=300), True,
    )

    await get_user_from_noralos_session("noralos-default.session_token=abc")

    called_url = mock_httpx_client.get.await_args.args[0]
    assert called_url == "https://staging.agent.noral.ai/api/auth/get-session"


@pytest.mark.asyncio
async def test_default_validate_url_when_env_unset(mock_httpx_client, mock_db_client, monkeypatch):
    monkeypatch.delenv("NORALOS_SESSION_VALIDATE_URL", raising=False)
    mock_httpx_client.get.return_value = _response(
        200, json_body={"user": {"id": "ba-user-xyz"}},
    )
    mock_db_client.get_or_create_user_by_provider_id.return_value = (
        _fake_user(user_id=400), True,
    )

    await get_user_from_noralos_session("noralos-default.session_token=abc")

    called_url = mock_httpx_client.get.await_args.args[0]
    assert called_url == DEFAULT_VALIDATE_URL
    assert "agent.noral.ai" in called_url


# ===========================================================================
# Integration with depends.py: SSO + local-auth fallback
# ===========================================================================


@pytest.mark.asyncio
async def test_depends_falls_back_to_local_auth_when_sso_returns_none(monkeypatch):
    """When AUTH_PROVIDER=noral and SSO returns None (no cookie / expired /
    agent.noral.ai unreachable), get_user falls through to local auth
    instead of raising 401. Lets users with direct email/password creds
    sign in even when SSO isn't usable."""
    monkeypatch.setattr("api.services.auth.depends.AUTH_PROVIDER", "noral")

    sso_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "api.services.auth.depends.get_user_from_noralos_session", sso_mock,
    )

    local_user = _fake_user(user_id=500, email="local@noral.ai")
    local_mock = AsyncMock(return_value=local_user)
    monkeypatch.setattr("api.services.auth.depends._handle_oss_auth", local_mock)

    from api.services.auth.depends import get_user

    result = await get_user(authorization="Bearer some-local-token", cookie=None)

    assert result is local_user
    sso_mock.assert_awaited_once_with(None)
    local_mock.assert_awaited_once_with("Bearer some-local-token")


@pytest.mark.asyncio
async def test_depends_sso_takes_precedence_when_valid(monkeypatch):
    """When SSO returns a user, local-auth fallback must NOT be called.
    SSO is the preferred path; we only fall through on SSO failure."""
    monkeypatch.setattr("api.services.auth.depends.AUTH_PROVIDER", "noral")

    sso_user = _fake_user(user_id=600, email="sso@noral.ai")
    sso_mock = AsyncMock(return_value=sso_user)
    monkeypatch.setattr(
        "api.services.auth.depends.get_user_from_noralos_session", sso_mock,
    )

    local_mock = AsyncMock()
    monkeypatch.setattr("api.services.auth.depends._handle_oss_auth", local_mock)

    from api.services.auth.depends import get_user

    result = await get_user(
        authorization="Bearer should-be-ignored",
        cookie="noralos-default.session_token=valid",
    )

    assert result is sso_user
    local_mock.assert_not_called()
