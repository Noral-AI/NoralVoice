from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel

from api.enums import CallType


class ExternalActorAttribution(BaseModel):
    """Phase-7.5 cross-system attribution for a single row.

    All fields nullable; all-NULL means a direct human action through the
    NoralVoice UI / API. Populated by the actor middleware
    (`api/services/auth/external_actor_middleware.py`) when a request
    arrives with `X-Noralos-Actor-*` headers.
    """

    actor_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    label: Optional[str] = None


class WorkflowRunResponseSchema(BaseModel):
    id: int
    workflow_id: int
    name: str
    mode: str
    created_at: datetime
    is_completed: bool
    transcript_url: str | None
    recording_url: str | None
    cost_info: Dict[str, Any] | None
    definition_id: int | None  # This is for backward compatibility
    initial_context: dict | None = None
    gathered_context: dict | None = None
    call_type: CallType
    logs: Dict[str, Any] | None = None
    annotations: Dict[str, Any] | None = None
    # Phase 7.5 attribution — null when the run was kicked off via direct
    # human action; populated when a NoralOS agent (or other integration)
    # made the call. The UI renders an "Acted by" badge off this and the
    # run-history page filters on it.
    created_by_external: Optional[ExternalActorAttribution] = None
    last_modified_by_external: Optional[ExternalActorAttribution] = None
