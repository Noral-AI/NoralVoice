"""Conversation ingestion — turning ElevenLabs calls into workflow_runs.

Two sources feed the same writer:

1. **Post-call webhooks** — the fast path. ElevenLabs pushes each conversation
   as it completes.
2. **Reconciliation** — the safety net. Webhooks get lost: an endpoint restart,
   a deploy, a network partition, a vendor-side retry that gives up. A
   webhook-only design silently loses calls, and the loss is invisible because
   nothing arrives to indicate it. So a scheduled job re-lists conversations
   over a recent window and inserts whatever is missing.

Both go through :func:`ingest_conversation`, which is idempotent on
``elevenlabs_conversation_id``. That single property is what makes
reconciliation safe to run as often as we like, and what makes a replayed
webhook a no-op rather than a duplicate call.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select

from api.db.models import OrganizationModel, WorkflowModel, WorkflowRunModel
from api.services.elevenlabs.conversations import extract_run_fields

#: How far back reconciliation looks by default. Comfortably longer than any
#: plausible webhook outage, and cheap because the listing is windowed.
DEFAULT_RECONCILIATION_WINDOW = timedelta(hours=6)

#: Reject webhooks whose timestamp is older than this, to bound replay attacks.
SIGNATURE_TOLERANCE_SECONDS = 30 * 60


class WebhookVerificationError(Exception):
    """Raised when a webhook's signature is absent, malformed, or wrong."""


def verify_webhook_signature(
    payload: bytes,
    signature_header: str | None,
    secret: str,
    *,
    tolerance_seconds: int = SIGNATURE_TOLERANCE_SECONDS,
    now: float | None = None,
) -> None:
    """Verify an ``ElevenLabs-Signature`` header.

    Format is ``t=<unix>,v0=<hex hmac>`` over ``"<t>.<body>"``.

    Raises:
        WebhookVerificationError: on any failure. Deliberately does not
            distinguish "bad signature" from "unknown key" in the message —
            an attacker probing the endpoint learns nothing from the error.
    """
    if not secret:
        raise WebhookVerificationError("No webhook secret configured")
    if not signature_header:
        raise WebhookVerificationError("Missing signature header")

    timestamp: str | None = None
    provided: str | None = None
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v0":
            provided = value

    if not timestamp or not provided:
        raise WebhookVerificationError("Malformed signature header")

    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("Malformed signature timestamp") from exc

    current = now if now is not None else time.time()
    if abs(current - sent_at) > tolerance_seconds:
        raise WebhookVerificationError("Signature timestamp outside tolerance")

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time — a byte-by-byte comparison leaks the prefix length.
    if not hmac.compare_digest(expected, provided):
        raise WebhookVerificationError("Signature mismatch")


async def resolve_organization_for_agent(session, agent_id: str) -> int | None:
    """Find which organization owns an ElevenLabs agent.

    The webhook arrives with an agent id and no tenant context — the endpoint
    is workspace-scoped, so one URL serves every client. This lookup is what
    attributes the call, and a call that cannot be attributed must not be
    written to an arbitrary organization.
    """
    result = await session.execute(
        select(WorkflowModel).where(WorkflowModel.elevenlabs_agent_id == agent_id)
    )
    workflow = result.scalars().first()
    return workflow.organization_id if workflow else None


async def ingest_conversation(
    session,
    conversation: dict[str, Any],
    *,
    organization_id: int | None = None,
) -> tuple[WorkflowRunModel | None, bool]:
    """Write a conversation as a run. Idempotent.

    Returns ``(run, created)``. ``created`` is False when the conversation was
    already ingested, which is the normal case for reconciliation and for a
    replayed webhook.

    Returns ``(None, False)`` when the conversation cannot be attributed to an
    organization — better to leave it unclaimed and visible in the logs than to
    file another client's call under the wrong tenant.
    """
    fields = extract_run_fields(conversation)
    conversation_id = fields["elevenlabs_conversation_id"]

    if not conversation_id:
        logger.warning("Ignoring ElevenLabs conversation with no conversation_id")
        return None, False

    # Idempotency. The unique index is the real guarantee; this check makes the
    # common case a clean no-op instead of an IntegrityError.
    existing = await session.execute(
        select(WorkflowRunModel).where(
            WorkflowRunModel.elevenlabs_conversation_id == conversation_id
        )
    )
    already = existing.scalars().first()
    if already:
        return already, False

    agent_id = fields["elevenlabs_agent_id"]

    if organization_id is None and agent_id:
        organization_id = await resolve_organization_for_agent(session, agent_id)

    if organization_id is None:
        logger.warning(
            f"Could not attribute ElevenLabs conversation {conversation_id} "
            f"(agent {agent_id}) to an organization; not ingesting."
        )
        return None, False

    workflow_result = await session.execute(
        select(WorkflowModel).where(
            WorkflowModel.elevenlabs_agent_id == agent_id,
            WorkflowModel.organization_id == organization_id,
        )
    )
    workflow = workflow_result.scalars().first()
    if not workflow:
        logger.warning(
            f"No workflow in organization {organization_id} for agent {agent_id}; "
            f"not ingesting conversation {conversation_id}."
        )
        return None, False

    started_at = fields.get("started_at_unix")

    run = WorkflowRunModel(
        name=f"elevenlabs-{conversation_id}",
        workflow_id=workflow.id,
        mode="elevenlabs",
        is_completed=True,
        elevenlabs_conversation_id=conversation_id,
        elevenlabs_agent_id=agent_id,
        duration_seconds=fields.get("duration_seconds"),
        sentiment=fields.get("call_successful"),
        transcript=fields.get("transcript"),
        gathered_context=fields.get("gathered_context") or {},
        created_at=(
            datetime.fromtimestamp(started_at, UTC)
            if started_at
            else datetime.now(UTC)
        ),
    )
    session.add(run)
    await session.flush()

    logger.info(
        f"Ingested ElevenLabs conversation {conversation_id} for organization "
        f"{organization_id} as run {run.id}"
    )
    return run, True


async def attach_recording(
    session,
    client,
    run: WorkflowRunModel | None,
    organization_id: int,
) -> None:
    """Fetch and store a run's recording, then point the run at it.

    Best-effort by design. A call with a transcript and no audio is still a
    useful record, so a storage failure degrades the row rather than rejecting
    the whole ingestion — the alternative would be discarding a call we
    successfully received because its audio did not arrive.
    """
    if run is None or not run.elevenlabs_conversation_id:
        return

    from api.services.elevenlabs.recordings import (
        store_recording,
        storage_backend_name,
    )

    try:
        path = await store_recording(
            client, organization_id, run.elevenlabs_conversation_id
        )
    except Exception as exc:
        logger.opt(exception=True).error(
            f"Recording storage failed for run {run.id}; the call is ingested "
            f"without audio: {exc!r}"
        )
        return

    if path:
        run.recording_url = path
        run.storage_backend = storage_backend_name()
        session.add(run)


async def reconcile_organization(
    session,
    client,
    organization_id: int,
    *,
    window: timedelta = DEFAULT_RECONCILIATION_WINDOW,
) -> dict[str, int]:
    """Backfill any conversations the webhook missed for one organization.

    Safe to run as often as you like — everything routes through the idempotent
    writer, so a window that overlaps an already-ingested period costs a lookup
    per conversation and writes nothing.

    Returns counts: ``{"seen": n, "created": n, "skipped": n}``.
    """
    from api.services.elevenlabs.conversations import iter_conversations_since

    since = datetime.now(UTC) - window
    seen = created = skipped = 0

    async for summary in iter_conversations_since(client, since):
        seen += 1
        conversation_id = summary.get("conversation_id")
        if not conversation_id:
            skipped += 1
            continue

        # The list payload is a summary; fetch the full record only for
        # conversations we have not already stored.
        existing = await session.execute(
            select(WorkflowRunModel.id).where(
                WorkflowRunModel.elevenlabs_conversation_id == conversation_id
            )
        )
        if existing.scalars().first():
            skipped += 1
            continue

        from api.services.elevenlabs.conversations import get_conversation

        full = await get_conversation(client, conversation_id)
        run, was_created = await ingest_conversation(
            session, full, organization_id=organization_id
        )
        if was_created:
            created += 1
            # Recording is fetched only for calls we actually stored, so a
            # re-run over an already-ingested window costs no downloads.
            await attach_recording(session, client, run, organization_id)
        else:
            skipped += 1

    if created:
        logger.info(
            f"Reconciliation recovered {created} conversation(s) for "
            f"organization {organization_id} that the webhook missed"
        )

    return {"seen": seen, "created": created, "skipped": skipped}
