"""HTTP middleware that resolves the calling external actor from headers.

Reads the five ``X-Noralos-Actor-*`` / ``X-Noralos-Run-*`` /
``X-Noralos-Company-*`` / ``X-Noralos-Initiated-By`` headers documented in
``PARITY_AND_VISIBILITY_PLAN.md`` §3.1. When all the required headers are
present and ``EXTERNAL_ACTOR_HEADERS_ENABLED`` is true, upserts the
``external_actors`` row and stashes a ``ExternalActorContext`` in the
request-scoped ``CURRENT_EXTERNAL_ACTOR`` ContextVar so the SQLAlchemy
event listeners can stamp attribution columns on the rows this request
creates or modifies.

Headers absent → middleware is a no-op (the request handler runs as if
this middleware weren't installed). This preserves the existing
human-user write path exactly. The kill switch
``EXTERNAL_ACTOR_HEADERS_ENABLED=false`` short-circuits the entire path.

Only triggers on writes (POST/PUT/PATCH/DELETE). Read requests skip the
work entirely — attribution doesn't apply to them.
"""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable, Optional

from fastapi import Request, Response
from loguru import logger

from api.constants import EXTERNAL_ACTOR_HEADERS_ENABLED
from api.db import db_client
from api.services.auth.external_actor_context import (
    CURRENT_EXTERNAL_ACTOR,
    ExternalActorContext,
)


INTEGRATION_ID = "noralai.noralvoice"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ACTOR_HEADER = "X-Noralos-Actor-Agent-Id"
ACTOR_NAME_HEADER = "X-Noralos-Actor-Agent-Name"
RUN_HEADER = "X-Noralos-Run-Id"
COMPANY_HEADER = "X-Noralos-Company-Id"
INITIATED_HEADER = "X-Noralos-Initiated-By"


def _parse_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


async def external_actor_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not EXTERNAL_ACTOR_HEADERS_ENABLED:
        return await call_next(request)

    if request.method not in WRITE_METHODS:
        return await call_next(request)

    raw_actor = request.headers.get(ACTOR_HEADER)
    actor_uuid = _parse_uuid(raw_actor)
    if actor_uuid is None:
        # No actor header (or malformed) → human-direct write. Pass through.
        return await call_next(request)

    display_name = request.headers.get(ACTOR_NAME_HEADER) or "Unknown agent"
    run_uuid = _parse_uuid(request.headers.get(RUN_HEADER))
    company_id = request.headers.get(COMPANY_HEADER)
    initiated_by = request.headers.get(INITIATED_HEADER)

    try:
        actor_row_id = await db_client.upsert_external_actor(
            integration_id=INTEGRATION_ID,
            external_actor_id=str(actor_uuid),
            display_name=display_name,
            display_kind="agent",
            metadata={
                "company_id": company_id,
                "initiated_by": initiated_by,
            },
        )
    except Exception as exc:  # pragma: no cover — defensive
        # If the upsert itself fails, the request must still succeed —
        # attribution is best-effort, never a write-blocker. Log + fall
        # through with no ContextVar set; the row will land NULL-attributed.
        logger.warning(f"external_actor upsert failed: {exc}")
        return await call_next(request)

    ctx = ExternalActorContext(
        actor_row_id=actor_row_id,
        run_id=run_uuid,
        display_label=f"{display_name} (NoralOS)",
    )
    token = CURRENT_EXTERNAL_ACTOR.set(ctx)
    try:
        return await call_next(request)
    finally:
        CURRENT_EXTERNAL_ACTOR.reset(token)
