from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.n8n_integration import router
from api.services.auth.depends import get_superuser
from api.services.n8n_client import (
    SECRET_HEADER_NAME,
    N8nTriggerResult,
    get_n8n_status,
    get_webhook_url,
    normalize_event_name,
    resolve_event_type,
    trigger_n8n_workflow,
)


def _enable_n8n(monkeypatch, *, retry_count: str = "2", timeout_ms: str = "10000"):
    monkeypatch.setenv("N8N_ENABLED", "true")
    monkeypatch.setenv("N8N_BASE_URL", "https://automation.noral.ai")
    monkeypatch.setenv("N8N_WEBHOOK_SECRET", "super-secret-value")
    monkeypatch.setenv("N8N_RETRY_COUNT", retry_count)
    monkeypatch.setenv("N8N_TIMEOUT_MS", timeout_ms)


def _disable_n8n(monkeypatch):
    monkeypatch.setenv("N8N_ENABLED", "false")
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_n8n_disabled_behavior(monkeypatch):
    _disable_n8n(monkeypatch)

    result = await trigger_n8n_workflow("CALL_COMPLETED", {"callId": "CA123"})

    assert result.success is False
    assert result.status_code is None
    assert result.message == "n8n integration disabled"


@pytest.mark.asyncio
async def test_missing_config_when_enabled(monkeypatch):
    monkeypatch.setenv("N8N_ENABLED", "true")
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_WEBHOOK_SECRET", raising=False)

    result = await trigger_n8n_workflow("CALL_COMPLETED", {})

    assert result.success is False
    assert "N8N_BASE_URL" in result.message
    assert "N8N_WEBHOOK_SECRET" in result.message


def test_event_name_normalization():
    assert normalize_event_name("CALL_COMPLETED") == "call-completed"
    assert normalize_event_name("callCompleted") == "call-completed"
    assert normalize_event_name("post call summary created") == (
        "post-call-summary-created"
    )


def test_supported_event_validation():
    assert resolve_event_type("CALL_COMPLETED").value == "CALL_COMPLETED"
    assert resolve_event_type("call-completed").value == "CALL_COMPLETED"

    with pytest.raises(ValueError):
        resolve_event_type("DELETE_EVERYTHING")


def test_webhook_url_generation(monkeypatch):
    _enable_n8n(monkeypatch)

    assert get_webhook_url("CALL_COMPLETED") == (
        "https://automation.noral.ai/webhook/noralvoice/call-completed"
    )


@pytest.mark.asyncio
async def test_successful_trigger_includes_secret_header(monkeypatch):
    _enable_n8n(monkeypatch)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get(SECRET_HEADER_NAME)
        seen["body"] = request.read()
        return httpx.Response(200, json={"executionId": "exec_123"})

    transport = httpx.MockTransport(handler)

    result = await trigger_n8n_workflow(
        "CALL_COMPLETED",
        {"companyId": 42, "callId": "CA123"},
        transport=transport,
    )

    assert result.success is True
    assert result.status_code == 200
    assert result.execution_id == "exec_123"
    assert seen["url"] == (
        "https://automation.noral.ai/webhook/noralvoice/call-completed"
    )
    assert seen["secret"] == "super-secret-value"
    assert b"super-secret-value" not in seen["body"]


@pytest.mark.asyncio
async def test_failed_trigger_does_not_leak_secret(monkeypatch):
    _enable_n8n(monkeypatch, retry_count="0")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded super-secret-value")

    result = await trigger_n8n_workflow(
        "CALL_COMPLETED",
        {"callId": "CA123"},
        transport=httpx.MockTransport(handler),
    )

    assert result.success is False
    assert result.status_code == 500
    assert "super-secret-value" not in result.message
    assert result.raw_response is None
    assert "rawResponse" not in result.to_dict()


@pytest.mark.asyncio
async def test_timeout_handling(monkeypatch):
    _enable_n8n(monkeypatch, retry_count="0")

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    result = await trigger_n8n_workflow(
        "CALL_COMPLETED",
        {"callId": "CA123"},
        transport=httpx.MockTransport(handler),
    )

    assert result.success is False
    assert result.status_code is None
    assert result.message == "n8n webhook timed out"


@pytest.mark.asyncio
async def test_retry_behavior(monkeypatch):
    _enable_n8n(monkeypatch, retry_count="2")
    monkeypatch.setattr("api.services.n8n_client.asyncio.sleep", AsyncMock())
    calls = {"count": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json={"id": "exec_retry"})

    result = await trigger_n8n_workflow(
        "CALL_COMPLETED",
        {"callId": "CA123"},
        transport=httpx.MockTransport(handler),
    )

    assert result.success is True
    assert result.execution_id == "exec_retry"
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_no_retry_on_clear_4xx(monkeypatch):
    _enable_n8n(monkeypatch, retry_count="2")
    calls = {"count": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(404, text="missing webhook")

    result = await trigger_n8n_workflow(
        "CALL_COMPLETED",
        {},
        transport=httpx.MockTransport(handler),
    )

    assert result.success is False
    assert result.status_code == 404
    assert calls["count"] == 1


def _make_app(superuser: MagicMock | None = None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if superuser is not None:
        app.dependency_overrides[get_superuser] = lambda: superuser
    return app


def test_diagnostic_status_response(monkeypatch):
    _enable_n8n(monkeypatch)
    user = MagicMock()
    user.id = 1
    user.is_superuser = True
    user.selected_organization_id = 42
    client = TestClient(_make_app(user))

    resp = client.get("/api/v1/integrations/n8n/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["configured"] is True
    assert body["baseUrlHost"] == "automation.noral.ai"
    assert "super-secret-value" not in resp.text
    assert {"name": "CALL_COMPLETED", "webhookSlug": "call-completed"} in body[
        "supportedEvents"
    ]


def test_get_n8n_status_when_disabled(monkeypatch):
    _disable_n8n(monkeypatch)

    status = get_n8n_status()

    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["configurationError"] is None


def test_unauthorized_test_endpoint_blocked():
    client = TestClient(_make_app())

    resp = client.post("/api/v1/integrations/n8n/test", json={})

    assert resp.status_code == 401


def test_authorized_test_endpoint_works(monkeypatch):
    user = MagicMock()
    user.id = 7
    user.is_superuser = True
    user.selected_organization_id = 42
    app = _make_app(user)
    client = TestClient(app)
    trigger_mock = AsyncMock(
        return_value=N8nTriggerResult(
            success=True,
            status_code=200,
            execution_id="exec_test",
            message="n8n workflow triggered",
        )
    )
    monkeypatch.setattr(
        "api.routes.n8n_integration.trigger_n8n_workflow",
        trigger_mock,
    )

    resp = client.post(
        "/api/v1/integrations/n8n/test",
        json={"eventType": "CALL_COMPLETED", "payload": {"callId": "CA123"}},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "success": True,
        "statusCode": 200,
        "executionId": "exec_test",
        "message": "n8n workflow triggered",
    }
    assert trigger_mock.await_args.args[0] == "CALL_COMPLETED"
    assert trigger_mock.await_args.args[1]["companyId"] == 42
    assert trigger_mock.await_args.args[1]["callId"] == "CA123"
