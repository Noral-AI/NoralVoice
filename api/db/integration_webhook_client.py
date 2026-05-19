"""Database client for integration_webhooks registrations.

The CRUD surface is tiny — register, list, delete, mark fired — and the
firing path itself lives in a separate arq task that calls into these
helpers.
"""

from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import IntegrationWebhookModel


# Mirror the Postgres enum from the Alembic migration so route handlers
# and the firing path don't have to duplicate the string set.
ALLOWED_EVENT_TYPES = ("run.completed", "run.failed", "campaign.progress")


class IntegrationWebhookClient(BaseDBClient):
    async def create_integration_webhook(
        self,
        organization_id: int,
        event_type: str,
        target_url: str,
        secret: str,
        reverse_rpc_url: Optional[str] = None,
        reverse_rpc_secret: Optional[str] = None,
    ) -> IntegrationWebhookModel:
        async with self.async_session() as session:
            row = IntegrationWebhookModel(
                organization_id=organization_id,
                event_type=event_type,
                target_url=target_url,
                secret=secret,
                reverse_rpc_url=reverse_rpc_url,
                reverse_rpc_secret=reverse_rpc_secret,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            await session.refresh(row)
        return row

    async def get_reverse_rpc_for_org(
        self, organization_id: int
    ) -> Optional[IntegrationWebhookModel]:
        """Return the first integration_webhooks row for this org that
        carries a non-null ``reverse_rpc_url``. Used by the
        ``noralos://`` tool executor to find the per-org reverse-RPC
        callback URL + secret.

        Multiple rows could carry the same reverse-RPC config (one per
        event-type the plugin subscribed to). They're all for the same
        plugin install per org, so any non-null row is sufficient. The
        partial index ``ix_integration_webhooks_reverse_rpc_org``
        backs this lookup.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(IntegrationWebhookModel)
                .where(
                    IntegrationWebhookModel.organization_id == organization_id,
                    IntegrationWebhookModel.reverse_rpc_url.is_not(None),
                )
                .limit(1)
            )
            return result.scalars().first()

    async def list_integration_webhooks(
        self, organization_id: int
    ) -> List[IntegrationWebhookModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(IntegrationWebhookModel)
                .where(IntegrationWebhookModel.organization_id == organization_id)
                .order_by(IntegrationWebhookModel.created_at.desc())
            )
            return list(result.scalars().all())

    async def get_integration_webhooks_for_event(
        self, organization_id: int, event_type: str
    ) -> List[IntegrationWebhookModel]:
        """Used by the firing path. Reads only the rows matching the
        given org + event_type."""
        async with self.async_session() as session:
            result = await session.execute(
                select(IntegrationWebhookModel).where(
                    IntegrationWebhookModel.organization_id == organization_id,
                    IntegrationWebhookModel.event_type == event_type,
                )
            )
            return list(result.scalars().all())

    async def delete_integration_webhook(
        self, webhook_id: int, organization_id: int
    ) -> bool:
        """Org-scoped delete. Returns True if a row was removed.

        We filter on both id and organization_id so a caller with a key
        for org A can't delete a registration owned by org B even if
        they guess its id.
        """
        async with self.async_session() as session:
            result = await session.execute(
                sa_delete(IntegrationWebhookModel).where(
                    IntegrationWebhookModel.id == webhook_id,
                    IntegrationWebhookModel.organization_id == organization_id,
                )
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result.rowcount > 0

    async def update_integration_webhook_firing(
        self, webhook_id: int, status: str, fired_at: Optional[datetime] = None
    ) -> None:
        """Stamp the outcome of the last firing attempt.

        Stored as ``last_status`` (short opaque string surfaced to the
        integration UI) and ``last_fired_at`` so operators can see when
        a webhook last delivered.
        """
        when = fired_at or datetime.now(UTC)
        async with self.async_session() as session:
            result = await session.execute(
                select(IntegrationWebhookModel)
                .where(IntegrationWebhookModel.id == webhook_id)
                .with_for_update()
            )
            row = result.scalars().first()
            if row is None:
                return
            row.last_fired_at = when
            row.last_status = status
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
