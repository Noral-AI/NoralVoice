"""External-actor roster client.

Methods on this client manage the ``external_actors`` table — the
append-only roster of non-human identities (e.g. NoralOS agents) that
have ever acted against this NoralVoice organisation. Looked up by
``(integration_id, external_actor_id)`` per the cross-system attribution
contract in ``PARITY_AND_VISIBILITY_PLAN.md`` §3.1.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import ExternalActorModel


class ExternalActorClient(BaseDBClient):
    async def upsert_external_actor(
        self,
        *,
        integration_id: str,
        external_actor_id: str,
        display_name: str,
        display_kind: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> uuid.UUID:
        """INSERT ... ON CONFLICT DO UPDATE the actor row and return its id.

        Refreshes ``last_seen_at`` and ``display_name`` on conflict so the
        roster stays current as agents are renamed or rotate through the
        integration.
        """
        async with self.async_session() as session:
            stmt = (
                pg_insert(ExternalActorModel)
                .values(
                    integration_id=integration_id,
                    external_actor_id=external_actor_id,
                    display_name=display_name,
                    display_kind=display_kind,
                    metadata_json=metadata or {},
                )
                .on_conflict_do_update(
                    constraint="uq_external_actors_integration_actor",
                    set_={
                        "display_name": display_name,
                        "metadata_json": metadata or {},
                        "last_seen_at": pg_insert(ExternalActorModel).excluded.last_seen_at,
                    },
                )
                .returning(ExternalActorModel.id)
            )
            result = await session.execute(stmt)
            actor_id = result.scalar_one()
            await session.commit()
            return actor_id

    async def get_external_actor_id(
        self, *, integration_id: str, external_actor_id: str
    ) -> Optional[uuid.UUID]:
        """Lookup the row id without writing — for tests + UI badge."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ExternalActorModel.id).where(
                    ExternalActorModel.integration_id == integration_id,
                    ExternalActorModel.external_actor_id == external_actor_id,
                )
            )
            return result.scalar_one_or_none()
