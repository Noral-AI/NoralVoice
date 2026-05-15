"""Tests for the integration-webhook registration + firing path.

Two layers:

  1. **Route layer** — POST / GET / DELETE under `/integration-webhooks`,
     org-scoping, secret reveal-once contract.
  2. **Firing layer** — HMAC signature roundtrip, retry-with-backoff
     behaviour on transient categories, and the chokepoint hook in
     `update_workflow_run` enqueuing the arq job on terminal transition.

The DB client and arq enqueue are mocked so tests stay in-process.
"""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.integration_webhooks import router
from api.services.auth.depends import get_user
from api.services.integration_webhooks import (
    EVENT_RUN_COMPLETED,
    PAYLOAD_SCHEMA_VERSION,
    build_run_completed_payload,
    deliver_with_retry,
    event_for_terminal_state,
    sign_payload,
)


def _make_app(caller_org_id: int = 100):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    caller = MagicMock()
    caller.id = 1
    caller.selected_organization_id = caller_org_id
    app.dependency_overrides[get_user] = lambda: caller
    return app


# ---------------- Route layer ------------------------------------------


def test_create_returns_secret_once(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    row = MagicMock()
    row.id = 1
    row.event_type = "run.completed"
    row.target_url = "https://hooks.example/run"
    row.secret = "test-secret"
    row.created_at = datetime.now(UTC)
    row.last_fired_at = None
    row.last_status = None
    monkeypatch.setattr(
        "api.routes.integration_webhooks.db_client.create_integration_webhook",
        AsyncMock(return_value=row),
    )

    resp = client.post(
        "/api/v1/integration-webhooks",
        json={"event_type": "run.completed", "target_url": "https://hooks.example/run"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["secret"] == "test-secret"
    assert body["id"] == 1
    assert body["event_type"] == "run.completed"


def test_list_omits_secret(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    row = MagicMock()
    row.id = 1
    row.event_type = "run.completed"
    row.target_url = "https://hooks.example/run"
    row.secret = "still-redacted"
    row.created_at = datetime.now(UTC)
    row.last_fired_at = None
    row.last_status = "ok"
    monkeypatch.setattr(
        "api.routes.integration_webhooks.db_client.list_integration_webhooks",
        AsyncMock(return_value=[row]),
    )

    resp = client.get("/api/v1/integration-webhooks")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 1
    assert "secret" not in payload[0]
    assert payload[0]["last_status"] == "ok"


def test_delete_404_when_not_in_org(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)
    monkeypatch.setattr(
        "api.routes.integration_webhooks.db_client.delete_integration_webhook",
        AsyncMock(return_value=False),
    )

    resp = client.delete("/api/v1/integration-webhooks/99")
    assert resp.status_code == 404


def test_delete_204_on_success(monkeypatch):
    app = _make_app(caller_org_id=100)
    client = TestClient(app)
    delete_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "api.routes.integration_webhooks.db_client.delete_integration_webhook",
        delete_mock,
    )

    resp = client.delete("/api/v1/integration-webhooks/5")
    assert resp.status_code == 204
    # Org-scoped delete: caller org must be passed through.
    assert delete_mock.await_args.kwargs["organization_id"] == 100
    assert delete_mock.await_args.kwargs["webhook_id"] == 5


def test_create_rejects_unknown_event_type():
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/integration-webhooks",
        json={"event_type": "unknown.event", "target_url": "https://x.example/x"},
    )
    assert resp.status_code == 422


# ---------------- Firing layer -----------------------------------------


def test_hmac_signature_roundtrip():
    """The receiver should be able to recompute the same hash over the
    raw body bytes using the per-registration secret."""
    secret = "shared-secret"
    body = b'{"event":"run.completed"}'
    sig = sign_payload(secret, body)
    # Reproduce the receiver's verify step.
    import hashlib
    import hmac

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert sig == expected
    # Different body -> different signature.
    assert sign_payload(secret, body + b"x") != sig


def test_build_run_completed_payload_shape():
    workflow = MagicMock()
    workflow.workflow_uuid = "wf-uuid-abc"

    run = MagicMock()
    run.id = 42
    run.state = "completed"
    run.transcript_url = "transcripts/42.txt"
    run.recording_url = "recordings/42.wav"
    run.gathered_context = {"extracted_variables": {"name": "Alice"}}
    run.cost_info = {"total_cost_usd": 0.12}
    run.created_at = datetime(2026, 5, 15, tzinfo=UTC)

    payload = build_run_completed_payload(run, workflow, organization_id=100)
    assert payload["schemaVersion"] == PAYLOAD_SCHEMA_VERSION
    assert payload["event"] == EVENT_RUN_COMPLETED
    assert payload["run_id"] == "42"
    assert payload["workflow_uuid"] == "wf-uuid-abc"
    assert payload["organization_id"] == 100
    assert payload["status"] == "completed"
    assert payload["transcript_url"] == "transcripts/42.txt"
    assert payload["recording_url"] == "recordings/42.wav"
    assert payload["extracted_variables"] == {"name": "Alice"}
    assert payload["cost_info"] == {"total_cost_usd": 0.12}
    assert payload["started_at"].startswith("2026-05-15")
    assert "ended_at" in payload


def test_event_for_terminal_state():
    # Only `completed` is terminal today; non-terminal states return None
    # so the data-layer hook stays quiet.
    assert event_for_terminal_state("completed") == EVENT_RUN_COMPLETED
    assert event_for_terminal_state("running") is None
    assert event_for_terminal_state("initialized") is None


@pytest.mark.asyncio
async def test_deliver_with_retry_succeeds_on_first_try(monkeypatch):
    """Happy path: one POST, status=ok, no sleeps."""
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("api.services.integration_webhooks.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "api.services.integration_webhooks._post_once",
        AsyncMock(side_effect=["ok"]),
    )
    status = await deliver_with_retry(
        "https://x.example/", b"{}", "sig", max_attempts=3
    )
    assert status == "ok"
    assert sleeps == []  # no backoff needed


@pytest.mark.asyncio
async def test_deliver_with_retry_stops_on_4xx(monkeypatch):
    """4xx is the integration's problem; don't retry."""
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("api.services.integration_webhooks.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "api.services.integration_webhooks._post_once",
        AsyncMock(side_effect=["http_404"]),
    )
    status = await deliver_with_retry("https://x.example/", b"{}", "sig")
    assert status == "http_404"
    assert sleeps == []


@pytest.mark.asyncio
async def test_deliver_with_retry_backs_off_on_timeout(monkeypatch):
    """Timeouts + 5xx are transient: retry with exponential backoff."""
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("api.services.integration_webhooks.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "api.services.integration_webhooks._post_once",
        AsyncMock(side_effect=["timeout", "http_500", "ok"]),
    )
    status = await deliver_with_retry(
        "https://x.example/", b"{}", "sig",
        max_attempts=3, base_seconds=1.0, factor=4.0,
    )
    assert status == "ok"
    # Two backoffs (after attempt 1 and after attempt 2). Last attempt
    # has no sleep after it because we returned ok.
    assert sleeps == [1.0, 4.0]


@pytest.mark.asyncio
async def test_deliver_with_retry_gives_up_after_max_attempts(monkeypatch):
    async def fake_sleep(_s):
        return

    monkeypatch.setattr("api.services.integration_webhooks.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "api.services.integration_webhooks._post_once",
        AsyncMock(side_effect=["timeout", "timeout", "http_500"]),
    )
    status = await deliver_with_retry(
        "https://x.example/", b"{}", "sig",
        max_attempts=3, base_seconds=0.01,
    )
    assert status == "http_500"
