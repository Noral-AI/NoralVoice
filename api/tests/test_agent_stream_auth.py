"""Auth gate tests for the agent-stream WebSocket.

The endpoint previously authenticated callers only by knowledge of the
workflow UUID. UUIDs leak in exported React-Flow JSON, so we now require
``?api_key=<value>`` on the upgrade.

These tests cover three reject paths:
  1. Missing ``api_key`` query parameter → close 4401.
  2. ``api_key`` doesn't validate → close 4401.
  3. ``api_key`` validates but the key's organization doesn't match the
     workflow's organization → close 4401.

Each case is exercised against the real router via TestClient.
``_handle_api_key_auth`` and ``db_client`` are mocked so the test does
not need a database.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.routes.agent_stream import router


WS_UNAUTHORIZED = 4401


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _expect_ws_close(
    client: TestClient,
    url: str,
    expected_code: int,
    expected_reason_substr: str | None = None,
) -> None:
    """Open the WS, expect the server to close it with `expected_code`."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(url) as ws:
            # Server-side close arrives on the first recv. If the server
            # closed before we could send, recv() raises immediately.
            ws.receive_text()
    assert excinfo.value.code == expected_code, (
        f"expected close code {expected_code}, got {excinfo.value.code}"
    )
    if expected_reason_substr is not None:
        assert expected_reason_substr in (excinfo.value.reason or ""), (
            f"reason {excinfo.value.reason!r} did not contain "
            f"{expected_reason_substr!r}"
        )


def test_missing_api_key_closes_4401():
    app = _make_app()
    client = TestClient(app)

    _expect_ws_close(
        client,
        "/agent-stream/any-workflow-uuid",
        expected_code=WS_UNAUTHORIZED,
        expected_reason_substr="api_key",
    )


def test_invalid_api_key_closes_4401():
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.agent_stream._handle_api_key_auth",
        new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid or expired API key")),
    ):
        _expect_ws_close(
            client,
            "/agent-stream/any-workflow-uuid?api_key=bogus",
            expected_code=WS_UNAUTHORIZED,
            expected_reason_substr="Invalid",
        )


def test_api_key_org_mismatch_closes_4401():
    app = _make_app()
    client = TestClient(app)

    user = MagicMock()
    user.id = 1
    user.selected_organization_id = 100  # api_key's org

    workflow = MagicMock()
    workflow.id = 42
    workflow.organization_id = 999  # different org — must reject
    workflow.user_id = 7
    workflow.template_context_variables = {}

    with (
        patch(
            "api.routes.agent_stream._handle_api_key_auth",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "api.routes.agent_stream.db_client.get_workflow_by_uuid_unscoped",
            new=AsyncMock(return_value=workflow),
        ),
        patch(
            "api.routes.agent_stream.telephony_registry.get_optional",
            new=MagicMock(return_value=MagicMock()),
        ),
    ):
        _expect_ws_close(
            client,
            "/agent-stream/any-workflow-uuid?api_key=valid&provider=cloudonix",
            expected_code=WS_UNAUTHORIZED,
            expected_reason_substr="not authorized",
        )
