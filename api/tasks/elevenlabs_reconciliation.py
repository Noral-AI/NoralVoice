"""Scheduled backfill for conversations the webhook never delivered.

Webhook-only ingestion loses calls, and loses them invisibly: nothing arrives
to tell you something did not arrive. An endpoint restart during a deploy, a
network partition, or a vendor retry budget running out all produce the same
symptom — a call that happened and is simply not in the dashboard, with no
error anywhere to indicate it.

This job closes that hole by re-listing recent conversations per organization
and inserting whatever is missing. It is cheap because the listing is windowed,
and safe to run often because ingestion is idempotent on the conversation id.

It also downloads recordings, which is the other half of Phase 2: the audio
lands in our MinIO under a per-client prefix so our copy stays complete even
if the vendor's retention window is short — which, by design, it is.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger
from sqlalchemy import select

from api.db import db_client
from api.db.models import OrganizationModel
from api.services.elevenlabs import MissingCredentialError, get_client_for_organization
from api.services.elevenlabs.ingestion import (
    DEFAULT_RECONCILIATION_WINDOW,
    reconcile_organization,
)


async def reconcile_elevenlabs_conversations(ctx, window_hours: int | None = None):
    """Reconcile every organization that has an ElevenLabs credential.

    Runs per organization rather than globally because there is no global
    ElevenLabs client to run it with — each organization's credential resolves
    its own, which is the same constraint that keeps the rest of the system
    tenant-scoped.

    An organization without a credential is skipped quietly: not being set up
    yet is a normal state, not an error worth paging about.
    """
    window = (
        timedelta(hours=window_hours)
        if window_hours is not None
        else DEFAULT_RECONCILIATION_WINDOW
    )

    totals = {"organizations": 0, "seen": 0, "created": 0, "skipped": 0}

    async with db_client.async_session() as session:
        result = await session.execute(select(OrganizationModel.id))
        organization_ids = [row[0] for row in result.all()]

    for organization_id in organization_ids:
        try:
            client = await get_client_for_organization(organization_id)
        except MissingCredentialError:
            continue

        totals["organizations"] += 1

        try:
            async with db_client.async_session() as session:
                counts = await reconcile_organization(
                    session, client, organization_id, window=window
                )
                await session.commit()

            for key in ("seen", "created", "skipped"):
                totals[key] += counts[key]

        except Exception as exc:
            # One organization's failure must not stop the rest. A vendor
            # outage or a revoked key should degrade this job, not disable it.
            logger.opt(exception=True).error(
                f"Reconciliation failed for organization {organization_id}: {exc!r}"
            )

    if totals["created"]:
        logger.warning(
            f"Reconciliation recovered {totals['created']} conversation(s) the "
            f"webhooks missed across {totals['organizations']} organization(s). "
            "Repeated non-zero recoveries mean the webhook path is unhealthy."
        )
    else:
        logger.info(
            f"Reconciliation clean: {totals['seen']} conversation(s) checked "
            f"across {totals['organizations']} organization(s), nothing missing."
        )

    return totals
