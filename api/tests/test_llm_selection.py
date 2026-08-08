"""Tests for platform-level LLM selection.

The choice is per organization, not per agent — one setting the operator makes
once, inherited by every agent created afterwards. These tests pin that
inheritance, the BYO-LLM cap, and the deliberate decision to accept
identifiers we do not recognise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.llm_settings import (
    BYO_LLM_CLIENT_CAP,
    DEFAULT_LLM,
    router as llm_router,
)
from api.services.auth.depends import get_user
from api.services.elevenlabs.llms import CATALOGUE, CUSTOM_LLM, is_known


def _app(caller_org_id: int | None = 100):
    app = FastAPI()
    app.include_router(llm_router, prefix="/api/v1")
    caller = MagicMock()
    caller.id = 7
    caller.selected_organization_id = caller_org_id
    app.dependency_overrides[get_user] = lambda: caller
    return app


# ---------------------------------------------------------------------------
# Selection is organization-level
# ---------------------------------------------------------------------------


def test_selection_is_stored_against_the_organization():
    client = TestClient(_app(caller_org_id=100))

    spy = AsyncMock()
    with patch("api.routes.llm_settings.db_client.upsert_configuration", new=spy):
        response = client.put(
            "/api/v1/llm/selection", json={"identifier": "claude-sonnet-4-5"}
        )

    assert response.status_code == 200
    organization_id, key, value = spy.await_args.args
    assert organization_id == 100
    assert key == "LLM_SELECTION"
    assert value == {"identifier": "claude-sonnet-4-5"}


def test_an_organization_that_never_chose_gets_a_sensible_default():
    """Rather than whatever the vendor happens to default to."""
    client = TestClient(_app())

    with patch(
        "api.routes.llm_settings.db_client.get_configuration_value",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/api/v1/llm/selection")

    body = response.json()
    assert body["identifier"] == DEFAULT_LLM
    assert body["is_default"] is True


def test_reading_back_a_stored_selection():
    client = TestClient(_app())

    with patch(
        "api.routes.llm_settings.db_client.get_configuration_value",
        new=AsyncMock(return_value={"identifier": "gpt-4o"}),
    ):
        body = client.get("/api/v1/llm/selection").json()

    assert body["identifier"] == "gpt-4o"
    assert body["is_default"] is False
    assert body["is_known"] is True


def test_no_organization_selected_is_rejected():
    client = TestClient(_app(caller_org_id=None))
    assert client.get("/api/v1/llm/selection").status_code == 400


# ---------------------------------------------------------------------------
# Agents inherit the organization's choice
# ---------------------------------------------------------------------------


async def test_created_agents_inherit_the_organization_selection():
    """The point of making this platform-level: no agent gets a different
    model by accident, and none has to be told which one to use."""
    from api.routes import agents as agents_module

    creator = AsyncMock(return_value={"agent_id": "agent_1"})

    with (
        patch.object(
            agents_module,
            "get_selected_llm",
            new=AsyncMock(return_value={"identifier": "claude-haiku-4-5"}),
        ),
        patch.object(
            agents_module,
            "get_client_for_organization",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch.object(agents_module, "create_agent", new=creator),
        patch.object(agents_module, "set_agent_retention", new=AsyncMock()),
        patch.object(
            agents_module.db_client, "create_elevenlabs_workflow", new=AsyncMock()
        ),
    ):
        user = MagicMock(id=7, selected_organization_id=100)
        request = agents_module.CreateAgentRequest(
            name="Reception", prompt="You are a receptionist."
        )
        await agents_module.create_organization_agent(request, user)

    assert creator.await_args.kwargs["llm"] == "claude-haiku-4-5"


def test_create_agent_request_has_no_per_agent_llm_field():
    """Guards the design decision against being quietly reversed."""
    from api.routes.agents import CreateAgentRequest

    assert "llm" not in CreateAgentRequest.model_fields


# ---------------------------------------------------------------------------
# BYO-LLM cap (plan §9.2)
# ---------------------------------------------------------------------------


def test_custom_llm_requires_an_endpoint_url():
    client = TestClient(_app())

    with patch(
        "api.routes.llm_settings.db_client.get_all_configurations_by_key",
        new=AsyncMock(return_value=[]),
    ):
        response = client.put(
            "/api/v1/llm/selection", json={"identifier": CUSTOM_LLM}
        )

    assert response.status_code == 422


def test_custom_llm_is_allowed_under_the_cap():
    client = TestClient(_app(caller_org_id=100))

    with (
        patch(
            "api.routes.llm_settings.db_client.get_all_configurations_by_key",
            new=AsyncMock(return_value=[]),
        ),
        patch("api.routes.llm_settings.db_client.upsert_configuration", new=AsyncMock()),
    ):
        response = client.put(
            "/api/v1/llm/selection",
            json={"identifier": CUSTOM_LLM, "custom_url": "https://llm.example/v1"},
        )

    assert response.status_code == 200
    assert response.json()["custom_url"] == "https://llm.example/v1"


def test_custom_llm_is_refused_once_the_cap_is_reached():
    """Running inference in the voice path is infrastructure, which the prime
    directive forbids by default. A third case is a decision, not a setting."""
    client = TestClient(_app(caller_org_id=100))

    at_cap = [
        {"organization_id": 200 + i, "value": {"identifier": CUSTOM_LLM}}
        for i in range(BYO_LLM_CLIENT_CAP)
    ]

    with patch(
        "api.routes.llm_settings.db_client.get_all_configurations_by_key",
        new=AsyncMock(return_value=at_cap),
    ):
        response = client.put(
            "/api/v1/llm/selection",
            json={"identifier": CUSTOM_LLM, "custom_url": "https://llm.example/v1"},
        )

    assert response.status_code == 409
    assert "capped" in response.json()["detail"]


def test_an_organization_already_on_byo_llm_can_change_its_endpoint():
    """The cap counts *other* organizations — re-saving your own settings must
    not be blocked by your own existing entry."""
    client = TestClient(_app(caller_org_id=100))

    including_self = [
        {"organization_id": 100, "value": {"identifier": CUSTOM_LLM}},
        {"organization_id": 200, "value": {"identifier": CUSTOM_LLM}},
    ]

    with (
        patch(
            "api.routes.llm_settings.db_client.get_all_configurations_by_key",
            new=AsyncMock(return_value=including_self),
        ),
        patch("api.routes.llm_settings.db_client.upsert_configuration", new=AsyncMock()),
    ):
        response = client.put(
            "/api/v1/llm/selection",
            json={"identifier": CUSTOM_LLM, "custom_url": "https://new.example/v1"},
        )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# The catalogue is advisory, not a gate
# ---------------------------------------------------------------------------


def test_an_unknown_identifier_is_accepted_with_a_warning():
    """The vendor ships models faster than we release. Rejecting anything
    unlisted would make every new model wait on a deploy from us."""
    client = TestClient(_app())

    with patch(
        "api.routes.llm_settings.db_client.upsert_configuration", new=AsyncMock()
    ):
        response = client.put(
            "/api/v1/llm/selection", json={"identifier": "gpt-7-released-tomorrow"}
        )

    assert response.status_code == 200
    assert response.json()["is_known"] is False


def test_a_blank_identifier_is_rejected():
    client = TestClient(_app())
    assert (
        client.put("/api/v1/llm/selection", json={"identifier": "   "}).status_code
        == 422
    )


def test_catalogue_spans_multiple_providers():
    """The ask was multiple LLMs to choose between, not one vendor's."""
    providers = {option.provider for option in CATALOGUE}

    assert {"Anthropic", "OpenAI", "Google"} <= providers


def test_catalogue_identifiers_are_unique():
    identifiers = [option.identifier for option in CATALOGUE]
    assert len(identifiers) == len(set(identifiers))


def test_the_default_is_a_model_we_actually_list():
    assert is_known(DEFAULT_LLM)
