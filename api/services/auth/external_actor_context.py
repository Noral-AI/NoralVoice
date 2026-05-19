"""Request-scoped context for the calling external actor (e.g. a NoralOS agent).

Set by ``external_actor_middleware`` from the ``X-Noralos-Actor-*`` headers
and read by the SQLAlchemy event listeners in ``external_actor_events`` to
stamp attribution columns onto rows the request creates or modifies.

NULL context = the request is a direct human action (or a system task that
doesn't go through the plugin). Attribution columns stay NULL — preserves
existing data shape exactly.

See ``PARITY_AND_VISIBILITY_PLAN.md`` §3.1.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExternalActorContext:
    """Resolved actor identity for a single in-flight request."""

    actor_row_id: uuid.UUID
    run_id: Optional[uuid.UUID]
    display_label: str


CURRENT_EXTERNAL_ACTOR: ContextVar[Optional[ExternalActorContext]] = ContextVar(
    "noralvoice.external_actor", default=None
)
