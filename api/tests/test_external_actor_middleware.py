"""Phase 7.5 cross-system attribution — unit tests for the middleware and
SQLAlchemy event listeners.

These tests intentionally don't touch the database. The middleware's DB call
(``db_client.upsert_external_actor``) is monkey-patched per-test; the event
listeners are exercised by calling them directly with a mock target. An
end-to-end test that runs the migration + a real POST request lives separately
in the integration test suite (see ``test_external_actor_middleware_integration.py``
once the test DB fixture is wired up).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.auth.external_actor_context import (
    CURRENT_EXTERNAL_ACTOR,
    ExternalActorContext,
)
from api.services.auth.external_actor_events import (
    ATTRIBUTED_MODELS,
    _stamp_create,
    _stamp_update,
)
from api.services.auth import external_actor_middleware as mw_mod


# ---------------------------------------------------------------------------
# Listener tests — no DB, no app needed.
# ---------------------------------------------------------------------------


def _make_target():
    """A bare object the listeners can stamp attributes on, like a model instance."""
    return SimpleNamespace(
        created_by_external_actor_id=None,
        created_by_external_run_id=None,
        created_by_external_label=None,
        last_modified_by_external_actor_id=None,
        last_modified_by_external_run_id=None,
        last_modified_by_external_label=None,
    )


def test_stamp_create_noop_when_no_context():
    target = _make_target()
    # No context set
    _stamp_create(mapper=MagicMock(), connection=MagicMock(), target=target)
    assert target.created_by_external_actor_id is None
    assert target.last_modified_by_external_label is None


def test_stamp_create_writes_all_six_columns_when_context_set():
    target = _make_target()
    actor_row_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ctx = ExternalActorContext(
        actor_row_id=actor_row_id,
        run_id=run_id,
        display_label="Voice Director (NoralOS)",
    )
    token = CURRENT_EXTERNAL_ACTOR.set(ctx)
    try:
        _stamp_create(mapper=MagicMock(), connection=MagicMock(), target=target)
    finally:
        CURRENT_EXTERNAL_ACTOR.reset(token)

    assert target.created_by_external_actor_id == actor_row_id
    assert target.created_by_external_run_id == run_id
    assert target.created_by_external_label == "Voice Director (NoralOS)"
    assert target.last_modified_by_external_actor_id == actor_row_id
    assert target.last_modified_by_external_run_id == run_id
    assert target.last_modified_by_external_label == "Voice Director (NoralOS)"


def test_stamp_update_only_touches_last_modified_columns():
    target = _make_target()
    # Pre-populate created_* as if the row already existed
    pre_existing_actor = uuid.uuid4()
    target.created_by_external_actor_id = pre_existing_actor
    target.created_by_external_label = "Original Author"

    new_actor = uuid.uuid4()
    new_run = uuid.uuid4()
    ctx = ExternalActorContext(
        actor_row_id=new_actor,
        run_id=new_run,
        display_label="Different Agent (NoralOS)",
    )
    token = CURRENT_EXTERNAL_ACTOR.set(ctx)
    try:
        _stamp_update(mapper=MagicMock(), connection=MagicMock(), target=target)
    finally:
        CURRENT_EXTERNAL_ACTOR.reset(token)

    # created_* is preserved
    assert target.created_by_external_actor_id == pre_existing_actor
    assert target.created_by_external_label == "Original Author"
    # last_modified_* updated
    assert target.last_modified_by_external_actor_id == new_actor
    assert target.last_modified_by_external_run_id == new_run
    assert target.last_modified_by_external_label == "Different Agent (NoralOS)"


def test_listener_registered_on_each_attributed_model():
    """ATTRIBUTED_MODELS list must match the 8 plan tables."""
    table_names = {m.__tablename__ for m in ATTRIBUTED_MODELS}
    assert table_names == {
        "workflows",
        "workflow_runs",
        "campaigns",
        "knowledge_base_documents",
        "tools",
        "telephony_configurations",
        "workflow_recordings",
        "embed_tokens",
    }


# ---------------------------------------------------------------------------
# Middleware tests — monkey-patch the DB upsert.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRequest:
    method: str
    headers: dict[str, str]


async def _passthrough(request) -> str:
    """A stand-in for `call_next` that returns a sentinel."""
    return "called"


@pytest.fixture(autouse=True)
def _ensure_enabled(monkeypatch):
    monkeypatch.setattr(mw_mod, "EXTERNAL_ACTOR_HEADERS_ENABLED", True)


def _patch_upsert(monkeypatch, returns: uuid.UUID):
    """Replace db_client.upsert_external_actor with an AsyncMock."""
    fake = AsyncMock(return_value=returns)
    monkeypatch.setattr(mw_mod.db_client, "upsert_external_actor", fake)
    return fake


def test_middleware_noop_when_kill_switch_off(monkeypatch):
    monkeypatch.setattr(mw_mod, "EXTERNAL_ACTOR_HEADERS_ENABLED", False)
    fake_upsert = _patch_upsert(monkeypatch, uuid.uuid4())

    request = _FakeRequest("POST", {"X-Noralos-Actor-Agent-Id": str(uuid.uuid4())})
    result = asyncio.run(mw_mod.external_actor_middleware(request, _passthrough))

    assert result == "called"
    assert fake_upsert.call_count == 0
    assert CURRENT_EXTERNAL_ACTOR.get() is None


def test_middleware_noop_on_read_method(monkeypatch):
    fake_upsert = _patch_upsert(monkeypatch, uuid.uuid4())

    request = _FakeRequest("GET", {"X-Noralos-Actor-Agent-Id": str(uuid.uuid4())})
    result = asyncio.run(mw_mod.external_actor_middleware(request, _passthrough))

    assert result == "called"
    assert fake_upsert.call_count == 0
    assert CURRENT_EXTERNAL_ACTOR.get() is None


def test_middleware_noop_when_actor_header_absent(monkeypatch):
    fake_upsert = _patch_upsert(monkeypatch, uuid.uuid4())

    # POST but no actor header — human-direct write
    request = _FakeRequest("POST", {})
    result = asyncio.run(mw_mod.external_actor_middleware(request, _passthrough))

    assert result == "called"
    assert fake_upsert.call_count == 0
    assert CURRENT_EXTERNAL_ACTOR.get() is None


def test_middleware_noop_when_actor_header_malformed(monkeypatch):
    fake_upsert = _patch_upsert(monkeypatch, uuid.uuid4())

    # Non-UUID actor id — silently ignored, write proceeds as human-direct
    request = _FakeRequest("POST", {"X-Noralos-Actor-Agent-Id": "not-a-uuid"})
    result = asyncio.run(mw_mod.external_actor_middleware(request, _passthrough))

    assert result == "called"
    assert fake_upsert.call_count == 0


def test_middleware_sets_context_with_full_headers(monkeypatch):
    actor_row_id = uuid.uuid4()
    fake_upsert = _patch_upsert(monkeypatch, actor_row_id)

    agent_id = uuid.uuid4()
    run_id = uuid.uuid4()
    captured = {}

    async def capture_ctx(request):
        captured["ctx"] = CURRENT_EXTERNAL_ACTOR.get()
        return "ok"

    request = _FakeRequest(
        "POST",
        {
            "X-Noralos-Actor-Agent-Id": str(agent_id),
            "X-Noralos-Actor-Agent-Name": "Voice Director",
            "X-Noralos-Run-Id": str(run_id),
            "X-Noralos-Company-Id": "company-123",
            "X-Noralos-Initiated-By": "user-42",
        },
    )
    asyncio.run(mw_mod.external_actor_middleware(request, capture_ctx))

    # Upsert called with the right inputs
    assert fake_upsert.call_count == 1
    call_kwargs = fake_upsert.call_args.kwargs
    assert call_kwargs["external_actor_id"] == str(agent_id)
    assert call_kwargs["display_name"] == "Voice Director"
    assert call_kwargs["display_kind"] == "agent"
    assert call_kwargs["metadata"]["company_id"] == "company-123"
    assert call_kwargs["metadata"]["initiated_by"] == "user-42"

    # ContextVar populated during call_next
    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.actor_row_id == actor_row_id
    assert ctx.run_id == run_id
    assert ctx.display_label == "Voice Director (NoralOS)"

    # ContextVar cleared after call
    assert CURRENT_EXTERNAL_ACTOR.get() is None


def test_middleware_tolerates_missing_optional_headers(monkeypatch):
    actor_row_id = uuid.uuid4()
    _patch_upsert(monkeypatch, actor_row_id)

    captured = {}

    async def capture_ctx(request):
        captured["ctx"] = CURRENT_EXTERNAL_ACTOR.get()
        return "ok"

    # Only the agent-id header — name, run, company, initiated-by all absent.
    request = _FakeRequest(
        "POST",
        {"X-Noralos-Actor-Agent-Id": str(uuid.uuid4())},
    )
    asyncio.run(mw_mod.external_actor_middleware(request, capture_ctx))

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.run_id is None
    assert ctx.display_label == "Unknown agent (NoralOS)"


def test_middleware_passes_through_when_upsert_fails(monkeypatch):
    """Attribution is best-effort — a DB error must not block the request."""
    fake_upsert = AsyncMock(side_effect=RuntimeError("db unreachable"))
    monkeypatch.setattr(mw_mod.db_client, "upsert_external_actor", fake_upsert)

    captured = {}

    async def capture_ctx(request):
        captured["ctx"] = CURRENT_EXTERNAL_ACTOR.get()
        return "ok"

    request = _FakeRequest(
        "POST", {"X-Noralos-Actor-Agent-Id": str(uuid.uuid4())}
    )
    result = asyncio.run(mw_mod.external_actor_middleware(request, capture_ctx))

    assert result == "ok"
    assert captured["ctx"] is None  # No context — the write is human-attributed
