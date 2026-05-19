"""Tests for the cross-domain iframe auth bridge.

Covers:
  - Token issuance happy path
  - Cross-org rejection (target_user not in caller's org)
  - target_path validation (must be relative)
  - TTL clamp via FastAPI's Field validation
  - Single-use consumption (second consume returns 410)
  - Expired token returns 410
  - Cookies set + redirect on successful consumption

The route is wired into a minimal app per the codebase's established
testing pattern (see test_masked_key_rejection.py); the DB client is
fully mocked so the tests stay in-process and don't need Postgres.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.embed_exchange_token_client import hash_exchange_token
from api.routes.embed import router
from api.services.auth.depends import get_user


def _make_app(caller_org_id: int = 100):
    """FastAPI app with the embed router and a fixed authenticated caller."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    caller = MagicMock()
    caller.id = 1
    caller.selected_organization_id = caller_org_id
    caller.is_superuser = False
    app.dependency_overrides[get_user] = lambda: caller
    return app


def _target_user(user_id: int = 7, org_id: int = 100):
    u = MagicMock()
    u.id = user_id
    u.email = "alice@example.com"
    u.selected_organization_id = org_id
    u.provider_id = "stack_alice"
    return u


def test_exchange_token_happy_path(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    target = _target_user(user_id=7, org_id=100)
    issued_row = MagicMock()
    issued_row.expires_at = datetime.now(UTC) + timedelta(seconds=90)

    monkeypatch.setattr(
        "api.routes.embed._resolve_target_user_in_org_async",
        AsyncMock(return_value=(target, True)),
    )
    create_mock = AsyncMock(return_value=issued_row)
    monkeypatch.setattr("api.routes.embed.db_client.create_embed_exchange_token", create_mock)

    resp = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "alice@example.com",
            "target_path": "/workflow/abc-uuid",
            "ttl_seconds": 90,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"].startswith("emx_")
    assert "embed_url" in body
    assert "token=" in body["embed_url"]
    assert "%2Fworkflow%2Fabc-uuid" in body["embed_url"]  # url-encoded path

    # Verify the row was created with the correct hash + org binding.
    call = create_mock.await_args
    assert call.kwargs["organization_id"] == 100
    assert call.kwargs["target_user_id"] == 7
    assert call.kwargs["target_path"] == "/workflow/abc-uuid"
    assert call.kwargs["token_hash"] == hash_exchange_token(body["token"])
    assert call.kwargs["ttl_seconds"] == 90


def test_exchange_token_cross_org_rejected(monkeypatch):
    """Target user exists but is in a different org → 404 (deliberately
    collapsed with not-found so the endpoint isn't a user-enum oracle)."""
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    other_org_user = _target_user(user_id=7, org_id=999)
    monkeypatch.setattr(
        "api.routes.embed._resolve_target_user_in_org_async",
        AsyncMock(return_value=(other_org_user, False)),
    )

    resp = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "alice@example.com",
            "target_path": "/workflow/abc-uuid",
            "ttl_seconds": 90,
        },
    )
    assert resp.status_code == 404


def test_exchange_token_unknown_user_rejected(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    monkeypatch.setattr(
        "api.routes.embed._resolve_target_user_in_org_async",
        AsyncMock(return_value=(None, False)),
    )

    resp = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "nobody@example.com",
            "target_path": "/workflow/abc",
            "ttl_seconds": 90,
        },
    )
    assert resp.status_code == 404


def test_exchange_token_ttl_clamped():
    """FastAPI Field validation enforces 30 ≤ ttl_seconds ≤ 300."""
    app = _make_app()
    client = TestClient(app)

    too_short = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "x@x.com",
            "target_path": "/x",
            "ttl_seconds": 5,
        },
    )
    too_long = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "x@x.com",
            "target_path": "/x",
            "ttl_seconds": 999,
        },
    )
    assert too_short.status_code == 422
    assert too_long.status_code == 422


def test_exchange_token_target_path_must_be_relative(monkeypatch):
    app = _make_app()
    client = TestClient(app)

    monkeypatch.setattr(
        "api.routes.embed._resolve_target_user_in_org_async",
        AsyncMock(return_value=(_target_user(), True)),
    )

    resp = client.post(
        "/api/v1/embed/exchange-token",
        json={
            "target_user_email": "alice@example.com",
            "target_path": "https://evil.example.com/oops",
            "ttl_seconds": 90,
        },
    )
    assert resp.status_code == 400
    assert "relative path" in resp.json()["detail"]


def test_embed_login_consumes_and_redirects(monkeypatch):
    app = _make_app()
    client = TestClient(app)

    target = _target_user(user_id=7, org_id=100)
    row = MagicMock()
    row.target_user_id = 7
    row.target_path = "/workflow/abc-uuid"
    row.expires_at = datetime.now(UTC) + timedelta(seconds=60)

    monkeypatch.setattr(
        "api.routes.embed.db_client.consume_embed_exchange_token",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "api.routes.embed.db_client.get_user_by_id",
        AsyncMock(return_value=target),
    )

    resp = client.get(
        "/api/v1/embed/embed-login?token=emx_test&path=/workflow/abc-uuid",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/workflow/abc-uuid" in location

    # Both cookies set.
    cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [
        v for k, v in resp.headers.items() if k.lower() == "set-cookie"
    ]
    cookie_blob = "\n".join(cookies)
    assert "noralvoice_auth_token=" in cookie_blob
    assert "noralvoice_auth_user=" in cookie_blob
    assert "HttpOnly" in cookie_blob  # at least one cookie should be HttpOnly (the token)


def test_embed_login_double_consume_returns_410(monkeypatch):
    app = _make_app()
    client = TestClient(app)

    # consume returns None on the second call — simulating already-consumed.
    monkeypatch.setattr(
        "api.routes.embed.db_client.consume_embed_exchange_token",
        AsyncMock(return_value=None),
    )

    resp = client.get(
        "/api/v1/embed/embed-login?token=emx_test&path=/workflow/abc",
        follow_redirects=False,
    )
    assert resp.status_code == 410
    assert "invalid, expired, or already consumed" in resp.json()["detail"]


def test_embed_login_path_mismatch_returns_410(monkeypatch):
    """target_path committed at issuance must match the path the
    browser presents at login."""
    app = _make_app()
    client = TestClient(app)

    row = MagicMock()
    row.target_user_id = 7
    row.target_path = "/workflow/EXPECTED"
    row.expires_at = datetime.now(UTC) + timedelta(seconds=60)

    monkeypatch.setattr(
        "api.routes.embed.db_client.consume_embed_exchange_token",
        AsyncMock(return_value=row),
    )

    resp = client.get(
        "/api/v1/embed/embed-login?token=emx_test&path=/workflow/SWAPPED",
        follow_redirects=False,
    )
    assert resp.status_code == 410
    assert "path mismatch" in resp.json()["detail"]


def test_embed_login_orphan_target_user_returns_410(monkeypatch):
    """If the target user has been deleted between issuance and consume,
    fail loudly rather than minting a JWT for nobody."""
    app = _make_app()
    client = TestClient(app)

    row = MagicMock()
    row.target_user_id = 7
    row.target_path = "/x"
    row.expires_at = datetime.now(UTC) + timedelta(seconds=60)

    monkeypatch.setattr(
        "api.routes.embed.db_client.consume_embed_exchange_token",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "api.routes.embed.db_client.get_user_by_id",
        AsyncMock(return_value=None),
    )

    resp = client.get(
        "/api/v1/embed/embed-login?token=emx_test&path=/x",
        follow_redirects=False,
    )
    assert resp.status_code == 410
