"""Tests for the ElevenLabs client and its credential resolution.

The acceptance criterion this file exists to prove is plan §7 Phase 1b's:
*no code path reaches ElevenLabs without an organization-resolved credential.*
On a single shared workspace that resolution path is the control doing the
isolation work, so it is asserted rather than assumed — including the
structural assertion in ``test_no_ambient_credential_in_the_package``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.services.crypto import generate_key, seal_credential_data
from api.services.crypto.secrets import ENCRYPTION_KEY_ENV_VAR
from api.services.elevenlabs import (
    ElevenLabsAPIError,
    ElevenLabsClient,
    MissingCredentialError,
    PhoneNumberAssignmentError,
    assign_agent,
    create_agent,
    extract_run_fields,
    get_client_for_organization,
    list_agents,
)
from api.services.elevenlabs import client as client_module
from api.db.db_client import DBClient

#: httpx.AsyncClient is patched in several tests below. Capture the real class
#: first, or the replacement recurses into itself.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def mock_transport(handler):
    """Patch httpx.AsyncClient so requests route to ``handler`` in-process."""
    transport = httpx.MockTransport(handler)
    return patch.object(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_ASYNC_CLIENT(transport=transport, **kw),
    )


def credential_lookup(return_value=None, side_effect=None):
    """Patch the org credential lookup on the client class.

    Patched on DBClient rather than on ``api.db.db_client`` because the package
    attribute is shadowed by the same-named submodule.
    """
    return patch.object(
        DBClient,
        "get_provider_credential",
        new=AsyncMock(return_value=return_value, side_effect=side_effect),
    )

API_KEY = "sk_elevenlabs_test_key_abcdef"


@pytest.fixture
def encryption_key():
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: generate_key()}):
        yield


def _client() -> ElevenLabsClient:
    return ElevenLabsClient(api_key=API_KEY, organization_id=42)


# ---------------------------------------------------------------------------
# No ambient credential — the isolation control
# ---------------------------------------------------------------------------


def test_client_cannot_be_built_without_an_organization():
    with pytest.raises(ValueError, match="organization_id"):
        ElevenLabsClient(api_key=API_KEY, organization_id=None)


def test_client_cannot_be_built_with_an_empty_key():
    with pytest.raises(MissingCredentialError):
        ElevenLabsClient(api_key="", organization_id=42)


async def test_resolution_requires_an_organization():
    with pytest.raises(MissingCredentialError, match="without an organization"):
        await get_client_for_organization(None)


async def test_resolution_fails_when_the_organization_has_no_credential():
    with credential_lookup(return_value=None):
        with pytest.raises(MissingCredentialError, match="no ElevenLabs credential"):
            await get_client_for_organization(42)


async def test_resolution_fails_on_an_empty_stored_credential(encryption_key):
    row = MagicMock()
    row.credential_data = seal_credential_data({"api_key": ""})

    with credential_lookup(return_value=row):
        with pytest.raises(MissingCredentialError, match="is empty"):
            await get_client_for_organization(42)


async def test_resolution_returns_a_client_bound_to_that_organization(encryption_key):
    row = MagicMock()
    row.credential_data = seal_credential_data({"api_key": API_KEY})

    with credential_lookup(return_value=row) as lookup:
        resolved = await get_client_for_organization(42)

    lookup.assert_awaited_once_with(42, "elevenlabs")
    assert resolved.organization_id == 42


async def test_resolution_is_not_cached_between_organizations(encryption_key):
    """Two organizations must never share a client instance."""
    row_a, row_b = MagicMock(), MagicMock()
    row_a.credential_data = seal_credential_data({"api_key": "sk_org_a_key"})
    row_b.credential_data = seal_credential_data({"api_key": "sk_org_b_key"})

    with credential_lookup(side_effect=[row_a, row_b]):
        a = await get_client_for_organization(1)
        b = await get_client_for_organization(2)

    assert a is not b
    assert (a.organization_id, b.organization_id) == (1, 2)


def test_no_ambient_credential_in_the_package():
    """Structural guard: nothing in the package may read the API key from the
    environment or hold a module-level client.

    A test that only exercises the happy path would not catch someone adding
    `_client = ElevenLabsClient(os.environ["ELEVENLABS_API_KEY"])` later, which
    is exactly the regression the plan forbids.
    """
    package_dir = Path(client_module.__file__).parent

    for source_file in package_dir.glob("*.py"):
        tree = ast.parse(source_file.read_text())

        for node in ast.walk(tree):
            # No os.environ / os.getenv anywhere in the package.
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                pytest.fail(
                    f"{source_file.name} reads the environment. The ElevenLabs "
                    "key must resolve from the calling organization only."
                )

        # No module-level ElevenLabsClient instance.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "ElevenLabsClient"
                ):
                    pytest.fail(
                        f"{source_file.name} holds a module-level client. Every "
                        "call must resolve a per-organization client."
                    )


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_repr_never_shows_the_key():
    assert API_KEY not in repr(_client())
    assert "organization_id=42" in repr(_client())


async def test_api_errors_do_not_echo_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized: bad key")

    with mock_transport(handler):
        with pytest.raises(ElevenLabsAPIError) as exc:
            await _client().get("/v1/convai/agents")

    assert API_KEY not in str(exc.value)
    assert exc.value.status_code == 401


async def test_key_is_sent_in_the_expected_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"agents": []})

    with mock_transport(handler):
        await list_agents(_client())

    assert seen["xi-api-key"] == API_KEY


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------


async def test_create_agent_builds_the_documented_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return httpx.Response(200, json={"agent_id": "agent_1"})

    with mock_transport(handler):
        await create_agent(
            _client(),
            name="Reference agent",
            prompt="You are a test agent.",
            first_message="Hello.",
            voice_id="voice_123",
            data_collection={"caller_name": {"type": "string"}},
        )

    agent = captured["conversation_config"]["agent"]
    assert captured["name"] == "Reference agent"
    assert agent["prompt"]["prompt"] == "You are a test agent."
    assert agent["first_message"] == "Hello."
    assert captured["conversation_config"]["tts"]["voice_id"] == "voice_123"
    assert "caller_name" in captured["platform_settings"]["data_collection"]


async def test_204_returns_none_rather_than_failing_to_parse():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    with mock_transport(handler):
        assert await _client().delete("/v1/convai/agents/a1") is None


# ---------------------------------------------------------------------------
# Phone number assignment — the silent-failure guard
# ---------------------------------------------------------------------------


async def test_assignment_verifies_and_raises_when_it_did_not_take():
    """The documented failure mode in this project: the PATCH succeeds, the
    number keeps serving its old destination, and nothing looks wrong."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        # Read-back reports the OLD agent — the cutover did not happen.
        return httpx.Response(
            200, json={"assigned_agent": {"agent_id": "agent_OLD"}}
        )

    with mock_transport(handler):
        with pytest.raises(PhoneNumberAssignmentError, match="has NOT"):
            await assign_agent(_client(), "pn_1", "agent_NEW")


async def test_assignment_succeeds_when_the_read_back_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(
            200, json={"assigned_agent": {"agent_id": "agent_NEW"}}
        )

    with mock_transport(handler):
        observed = await assign_agent(_client(), "pn_1", "agent_NEW")

    assert observed["assigned_agent"]["agent_id"] == "agent_NEW"


# ---------------------------------------------------------------------------
# Conversation field extraction
# ---------------------------------------------------------------------------


def test_extract_run_fields_flattens_the_payload():
    conversation = {
        "conversation_id": "conv_1",
        "agent_id": "agent_1",
        "status": "done",
        "metadata": {"call_duration_secs": 92, "start_time_unix_secs": 1_700_000_000},
        "transcript": [{"role": "agent", "message": "Hello"}],
        "analysis": {
            "data_collection_results": {"caller_name": {"value": "Sam"}},
            "call_successful": "success",
            "transcript_summary": "Caller asked about hours.",
        },
    }

    fields = extract_run_fields(conversation)

    assert fields["elevenlabs_conversation_id"] == "conv_1"
    assert fields["duration_seconds"] == 92
    assert fields["gathered_context"]["caller_name"]["value"] == "Sam"
    assert fields["call_successful"] == "success"


def test_extract_run_fields_tolerates_a_sparse_payload():
    """Reconciliation sees in-progress and failed calls, not just clean ones."""
    fields = extract_run_fields({"conversation_id": "conv_2"})

    assert fields["elevenlabs_conversation_id"] == "conv_2"
    assert fields["duration_seconds"] is None
    assert fields["gathered_context"] == {}
