"""Tests for the provider-credential routes.

These routes handle the ElevenLabs API key, which the plan requires be managed
in the platform UI and never in env or code. The properties that matter are
less about CRUD mechanics than about exposure and tenancy:

  - the secret goes in and never comes back out (plan §9.1)
  - every read and write is scoped to the caller's organization (plan §5.2)
  - what lands in the database is ciphertext, not the key

The DB client is mocked so these stay in-process, except where a test is
specifically about what gets written — those assert on the value handed to the
client, which is where sealing happens.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.credentials import router
from api.services.auth.depends import get_user
from api.services.crypto import generate_key, unseal_credential_data
from api.services.crypto.secrets import ENCRYPTION_KEY_ENV_VAR

ELEVENLABS_KEY = "sk_elevenlabs_0123456789abcdef"


def _make_app(caller_org_id: int | None = 100):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    caller = MagicMock()
    caller.id = 7
    caller.selected_organization_id = caller_org_id
    app.dependency_overrides[get_user] = lambda: caller
    return app


def _stored_credential(last_four="cdef", rotated_at=None):
    row = MagicMock()
    row.last_four = last_four
    row.rotated_at = rotated_at
    row.created_at = datetime.now(UTC)
    return row


# ---------------------------------------------------------------------------
# Exposure — the property this whole phase exists for
# ---------------------------------------------------------------------------


def test_reading_a_credential_never_returns_the_secret():
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.credentials.db_client.get_provider_credential",
        new=AsyncMock(return_value=_stored_credential()),
    ):
        response = client.get("/api/v1/credentials/providers/elevenlabs")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["last_four"] == "cdef"
    # The secret must not appear anywhere in the serialised response.
    assert ELEVENLABS_KEY not in json.dumps(body)
    assert "secret" not in body
    assert "api_key" not in body
    assert "credential_data" not in body


def test_setting_a_credential_does_not_echo_it_back():
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.credentials.db_client.set_provider_credential",
        new=AsyncMock(return_value=_stored_credential()),
    ):
        response = client.put(
            "/api/v1/credentials/providers/elevenlabs",
            json={"secret": ELEVENLABS_KEY},
        )

    assert response.status_code == 200
    assert ELEVENLABS_KEY not in json.dumps(response.json())


def test_what_reaches_the_database_is_ciphertext():
    """The route hands a raw secret to the client; the client seals it. This
    asserts the seam actually seals, rather than trusting that it does."""
    from api.db.webhook_credential_client import seal_credential_data

    with patch.dict("os.environ", {ENCRYPTION_KEY_ENV_VAR: generate_key()}):
        sealed = seal_credential_data({"api_key": ELEVENLABS_KEY})

        assert ELEVENLABS_KEY not in json.dumps(sealed)
        assert unseal_credential_data(sealed) == {"api_key": ELEVENLABS_KEY}


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


def test_read_is_scoped_to_the_callers_organization():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    spy = AsyncMock(return_value=None)
    with patch("api.routes.credentials.db_client.get_provider_credential", new=spy):
        client.get("/api/v1/credentials/providers/elevenlabs")

    spy.assert_awaited_once_with(100, "elevenlabs")


def test_write_is_scoped_to_the_callers_organization():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    spy = AsyncMock(return_value=_stored_credential())
    with patch("api.routes.credentials.db_client.set_provider_credential", new=spy):
        client.put(
            "/api/v1/credentials/providers/elevenlabs",
            json={"secret": ELEVENLABS_KEY},
        )

    assert spy.await_args.kwargs["organization_id"] == 100


def test_revoke_is_scoped_to_the_callers_organization():
    app = _make_app(caller_org_id=100)
    client = TestClient(app)

    spy = AsyncMock(return_value=True)
    with patch("api.routes.credentials.db_client.revoke_provider_credential", new=spy):
        client.delete("/api/v1/credentials/providers/elevenlabs")

    spy.assert_awaited_once_with(100, "elevenlabs")


def test_no_organization_selected_is_rejected():
    app = _make_app(caller_org_id=None)
    client = TestClient(app)

    assert client.get("/api/v1/credentials/providers/elevenlabs").status_code == 400


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_unconfigured_provider_reports_not_configured_rather_than_404():
    """The settings page renders "not set up yet" as a normal state."""
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.credentials.db_client.get_provider_credential",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/api/v1/credentials/providers/elevenlabs")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "elevenlabs",
        "configured": False,
        "last_four": None,
        "rotated_at": None,
        "created_at": None,
    }


def test_rotation_surfaces_rotated_at():
    app = _make_app()
    client = TestClient(app)
    rotated = datetime.now(UTC)

    with patch(
        "api.routes.credentials.db_client.set_provider_credential",
        new=AsyncMock(return_value=_stored_credential(last_four="9999", rotated_at=rotated)),
    ):
        response = client.put(
            "/api/v1/credentials/providers/elevenlabs",
            json={"secret": "sk_elevenlabs_rotated_999999999999"},
        )

    assert response.status_code == 200
    assert response.json()["last_four"] == "9999"
    assert response.json()["rotated_at"] is not None


def test_revoking_nothing_is_a_404():
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.credentials.db_client.revoke_provider_credential",
        new=AsyncMock(return_value=False),
    ):
        response = client.delete("/api/v1/credentials/providers/elevenlabs")

    assert response.status_code == 404


def test_revoking_an_installed_credential_succeeds():
    app = _make_app()
    client = TestClient(app)

    with patch(
        "api.routes.credentials.db_client.revoke_provider_credential",
        new=AsyncMock(return_value=True),
    ):
        response = client.delete("/api/v1/credentials/providers/elevenlabs")

    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_unknown_provider_is_rejected():
    """No ambient providers — an unrecognised name is a 404, not a silently
    created credential row for a provider nothing can use."""
    app = _make_app()
    client = TestClient(app)

    assert (
        client.get("/api/v1/credentials/providers/openai").status_code == 404
    )
    assert (
        client.put(
            "/api/v1/credentials/providers/openai", json={"secret": "x"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_secret_is_rejected(blank):
    app = _make_app()
    client = TestClient(app)

    spy = AsyncMock()
    with patch("api.routes.credentials.db_client.set_provider_credential", new=spy):
        response = client.put(
            "/api/v1/credentials/providers/elevenlabs", json={"secret": blank}
        )

    assert response.status_code == 422
    spy.assert_not_awaited()


def test_secret_is_stripped_before_storage():
    """Keys pasted from a dashboard routinely carry trailing whitespace, and a
    key with a stray newline fails auth in a way that is painful to diagnose."""
    app = _make_app()
    client = TestClient(app)

    spy = AsyncMock(return_value=_stored_credential())
    with patch("api.routes.credentials.db_client.set_provider_credential", new=spy):
        client.put(
            "/api/v1/credentials/providers/elevenlabs",
            json={"secret": f"  {ELEVENLABS_KEY}\n"},
        )

    assert spy.await_args.kwargs["secret"] == ELEVENLABS_KEY
