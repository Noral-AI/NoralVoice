"""SQLAlchemy ``before_insert`` / ``before_update`` listeners that stamp
attribution columns on user-authored rows.

Registered once at app startup via ``register_external_actor_listeners()``.
Each listener reads the request-scoped ``CURRENT_EXTERNAL_ACTOR`` ContextVar
set by ``external_actor_middleware``. When the var is None (no actor for the
current request — e.g. a human writing directly), the listener is a no-op
and the row's six attribution columns stay NULL.

The list of models below MUST stay in sync with ``ATTRIBUTED_TABLES`` in the
``20260519_phase7_5_external_actors`` migration.
"""

from __future__ import annotations

from sqlalchemy import event

from api.db.models import (
    CampaignModel,
    EmbedTokenModel,
    KnowledgeBaseDocumentModel,
    TelephonyConfigurationModel,
    ToolModel,
    WorkflowModel,
    WorkflowRecordingModel,
    WorkflowRunModel,
)
from api.services.auth.external_actor_context import CURRENT_EXTERNAL_ACTOR


ATTRIBUTED_MODELS = (
    WorkflowModel,
    WorkflowRunModel,
    CampaignModel,
    KnowledgeBaseDocumentModel,
    ToolModel,
    TelephonyConfigurationModel,
    WorkflowRecordingModel,
    EmbedTokenModel,
)


def _stamp_create(mapper, connection, target) -> None:
    ctx = CURRENT_EXTERNAL_ACTOR.get()
    if ctx is None:
        return
    target.created_by_external_actor_id = ctx.actor_row_id
    target.created_by_external_run_id = ctx.run_id
    target.created_by_external_label = ctx.display_label
    target.last_modified_by_external_actor_id = ctx.actor_row_id
    target.last_modified_by_external_run_id = ctx.run_id
    target.last_modified_by_external_label = ctx.display_label


def _stamp_update(mapper, connection, target) -> None:
    ctx = CURRENT_EXTERNAL_ACTOR.get()
    if ctx is None:
        return
    target.last_modified_by_external_actor_id = ctx.actor_row_id
    target.last_modified_by_external_run_id = ctx.run_id
    target.last_modified_by_external_label = ctx.display_label


_registered = False


def register_external_actor_listeners() -> None:
    """Idempotent — safe to call from app startup + tests."""
    global _registered
    if _registered:
        return
    for model in ATTRIBUTED_MODELS:
        event.listen(model, "before_insert", _stamp_create)
        event.listen(model, "before_update", _stamp_update)
    _registered = True
