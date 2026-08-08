"""Tests for the agent-management and calls-dashboard routes.

The property under test throughout is tenant isolation. On a single shared
ElevenLabs workspace the vendor will happily confirm that any client's agent
exists, so ownership has to be a fact about *our* database — and every one of
these routes has to check it. A route that took an agent id and acted on it
without that check would be a cross-client hole that no vendor-side control
would catch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.agents import router as agents_router
from api.services.auth.depends import get_user
from api.services.elevenlabs import MissingCredentialError


def _make_app(caller_org_id: int | None = 100):
    app = FastAPI()
    app.include_router(agents_router, prefix="/api/v1")
    caller = MagicMock()
    caller.id = 7
    caller.selected_organization_id = caller_org_id
    app.dependency_overrides[get_user] = lambda: caller
    return app


def _workflow(workflow_id=3, name="Reception", agent_id="agent_1"):
    row = MagicMock()
    row.id = workflow_id
    row.name = name
    row.elevenlabs_agent_id = agent_id
    return row


# ---------------------------------------------------------------------------
# Ownership — the cross-client hole these routes must not have
# ---------------------------------------------------------------------------


def test_reading_an_agent_the_org_does_not_own_is_404():
    """The vendor would serve this agent happily; our database must not."""
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    with patch(
        "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/api/v1/agents/agent_owned_by_someone_else")

    assert response.status_code == 404


def test_updating_an_agent_the_org_does_not_own_is_404():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    with patch(
        "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
        new=AsyncMock(return_value=None),
    ):
        response = client.patch(
            "/api/v1/agents/agent_theirs", json={"name": "hijacked"}
        )

    assert response.status_code == 404


def test_deleting_an_agent_the_org_does_not_own_is_404():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    with patch(
        "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
        new=AsyncMock(return_value=None),
    ):
        response = client.delete("/api/v1/agents/agent_theirs")

    assert response.status_code == 404


def test_ownership_lookup_is_passed_the_callers_org():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    spy = AsyncMock(return_value=None)
    with patch(
        "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id", new=spy
    ):
        client.get("/api/v1/agents/agent_1")

    spy.assert_awaited_once_with(100, "agent_1")


def test_listing_is_scoped_to_the_callers_org():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    spy = AsyncMock(return_value=[_workflow()])
    with patch("api.routes.agents.db_client.get_elevenlabs_workflows", new=spy):
        response = client.get("/api/v1/agents/")

    spy.assert_awaited_once_with(100)
    assert response.json()[0]["name"] == "Reception"


def test_no_organization_selected_is_rejected():
    app = _make_app(caller_org_id=None)
    client = TestClient(app)

    assert client.get("/api/v1/agents/").status_code == 400


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def test_missing_key_is_a_409_pointing_at_settings():
    """Not a 500 — nothing is broken, setup is incomplete."""
    app = _make_app()
    client = TestClient(app)

    with (
        patch(
            "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
            new=AsyncMock(return_value=_workflow()),
        ),
        patch(
            "api.routes.agents.get_client_for_organization",
            new=AsyncMock(side_effect=MissingCredentialError("no key; add one")),
        ),
    ):
        response = client.get("/api/v1/agents/agent_1")

    assert response.status_code == 409
    assert "add one" in response.json()["detail"]


def test_create_resolves_the_client_for_the_callers_org():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    resolver = AsyncMock(return_value=MagicMock())
    with (
        patch("api.routes.agents.get_client_for_organization", new=resolver),
        patch(
            "api.routes.agents.get_selected_llm",
            new=AsyncMock(return_value={"identifier": "gemini-2.5-flash"}),
        ),
        patch(
            "api.routes.agents.create_agent",
            new=AsyncMock(return_value={"agent_id": "agent_new"}),
        ),
        patch("api.routes.agents.set_agent_retention", new=AsyncMock()),
        patch(
            "api.routes.agents.db_client.create_elevenlabs_workflow", new=AsyncMock()
        ),
    ):
        client.post(
            "/api/v1/agents/", json={"name": "New", "prompt": "You are a bot."}
        )

    resolver.assert_awaited_once_with(100)


# ---------------------------------------------------------------------------
# Retention — the two-year default must not survive agent creation
# ---------------------------------------------------------------------------


def test_creating_an_agent_sets_retention_off_the_vendor_default():
    app = _make_app()
    client = TestClient(app)

    retention = AsyncMock()
    with (
        patch(
            "api.routes.agents.get_client_for_organization",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "api.routes.agents.get_selected_llm",
            new=AsyncMock(return_value={"identifier": "gemini-2.5-flash"}),
        ),
        patch(
            "api.routes.agents.create_agent",
            new=AsyncMock(return_value={"agent_id": "agent_new"}),
        ),
        patch("api.routes.agents.set_agent_retention", new=retention),
        patch(
            "api.routes.agents.db_client.create_elevenlabs_workflow", new=AsyncMock()
        ),
    ):
        client.post(
            "/api/v1/agents/", json={"name": "New", "prompt": "You are a bot."}
        )

    retention.assert_awaited_once()
    kwargs = retention.await_args.kwargs
    assert kwargs["transcript_retention_days"] < 730
    assert kwargs["audio_retention_days"] <= kwargs["transcript_retention_days"]


def test_a_failed_retention_call_does_not_fail_agent_creation():
    """The agent exists and works; retention is loud but non-fatal."""
    from api.services.elevenlabs import ElevenLabsAPIError

    app = _make_app()
    client = TestClient(app)

    with (
        patch(
            "api.routes.agents.get_client_for_organization",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "api.routes.agents.get_selected_llm",
            new=AsyncMock(return_value={"identifier": "gemini-2.5-flash"}),
        ),
        patch(
            "api.routes.agents.create_agent",
            new=AsyncMock(return_value={"agent_id": "agent_new"}),
        ),
        patch(
            "api.routes.agents.set_agent_retention",
            new=AsyncMock(
                side_effect=ElevenLabsAPIError(
                    500, "nope", method="PATCH", path="/x"
                )
            ),
        ),
        patch(
            "api.routes.agents.db_client.create_elevenlabs_workflow", new=AsyncMock()
        ),
    ):
        response = client.post(
            "/api/v1/agents/", json={"name": "New", "prompt": "You are a bot."}
        )

    assert response.status_code == 200


def test_delete_archives_rather_than_removing_the_workflow_row():
    """Historical runs reference it, and Phase 5 retention depends on them
    still resolving."""
    app = _make_app()
    client = TestClient(app)

    archive = AsyncMock()
    with (
        patch(
            "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
            new=AsyncMock(return_value=_workflow()),
        ),
        patch(
            "api.routes.agents.get_client_for_organization",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("api.routes.agents.delete_agent", new=AsyncMock()),
        patch("api.routes.agents.db_client.archive_workflow", new=archive),
    ):
        response = client.delete("/api/v1/agents/agent_1")

    assert response.status_code == 204
    archive.assert_awaited_once_with(3, 100)


# ---------------------------------------------------------------------------
# Vendor failures surface as 502, not 500
# ---------------------------------------------------------------------------


def test_vendor_errors_become_502():
    from api.services.elevenlabs import ElevenLabsAPIError

    app = _make_app()
    client = TestClient(app)

    with (
        patch(
            "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
            new=AsyncMock(return_value=_workflow()),
        ),
        patch(
            "api.routes.agents.get_client_for_organization",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "api.routes.agents.get_agent",
            new=AsyncMock(
                side_effect=ElevenLabsAPIError(
                    503, "upstream down", method="GET", path="/x"
                )
            ),
        ),
    ):
        response = client.get("/api/v1/agents/agent_1")

    assert response.status_code == 502
