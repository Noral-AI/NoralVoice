"""Outbound integration-webhook firing.

Phase 1 hook point: the data-layer ``update_workflow_run`` enqueues a
single arq job ``fire_integration_webhooks`` when a run transitions to
a terminal state. The arq task looks up registered webhooks for the
run's organization + event, builds the payload, HMAC-signs it, and
POSTs with retries + exponential backoff. Failures are logged to
``last_status`` on the registration but never block the run completion
flow.

The hook lives at the data layer because the workflow_run terminal
transition isn't centralised — pipeline finish, telephony status
callback, campaign dispatcher, and the agent_stream raw-audio branch
all call ``update_workflow_run(state=COMPLETED, …)`` from different
places. The data layer is the one chokepoint they share.
"""

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any, Mapping

import httpx
from loguru import logger

# Event-type constants — the canonical strings.
EVENT_RUN_COMPLETED = "run.completed"
EVENT_RUN_FAILED = "run.failed"
EVENT_CAMPAIGN_PROGRESS = "campaign.progress"

# Payload schema version. Bump only on breaking changes; consumers
# branch on this and reject unknown majors.
PAYLOAD_SCHEMA_VERSION = 1

# Retry policy. Three attempts total (one initial + two retries) with
# exponential backoff so a 30s-long downstream outage doesn't lose the
# event but doesn't loop forever either.
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 4.0  # 1s, 4s, 16s
PER_ATTEMPT_TIMEOUT_SECONDS = 10.0


def sign_payload(secret: str, body_bytes: bytes) -> str:
    """HMAC-SHA256 over the raw response bytes, hex-encoded.

    The receiver reads the raw bytes (NOT a re-serialised JSON dict —
    key ordering would shift the hash) and recomputes the HMAC over
    them. Standard pattern; lets the receiver verify integrity + origin
    without trusting the network path.
    """
    return hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()


def build_run_completed_payload(
    run: Any, workflow: Any, organization_id: int
) -> dict:
    """Compose the v1 ``run.completed`` payload.

    Pulls from the run + workflow models loaded by the firing task.
    Fields are intentionally flat (no nested objects beyond
    ``cost_info`` / ``extracted_variables``) so a downstream consumer
    can de-serialize without a schema.
    """
    gathered = run.gathered_context or {}
    return {
        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
        "event": EVENT_RUN_COMPLETED,
        "run_id": str(run.id),
        "workflow_uuid": getattr(workflow, "workflow_uuid", None) if workflow else None,
        "organization_id": organization_id,
        # The workflow run model only has one terminal value (`completed`)
        # today; receivers can branch on `gathered_context.call_tags`
        # for failure flavours.
        "status": run.state,
        "transcript_url": run.transcript_url,
        "recording_url": run.recording_url,
        "extracted_variables": gathered.get("extracted_variables") or gathered,
        "started_at": run.created_at.isoformat() if run.created_at else None,
        "ended_at": datetime.now(UTC).isoformat(),
        "cost_info": run.cost_info or {},
    }


async def _post_once(
    url: str,
    body_bytes: bytes,
    signature: str,
    timeout_seconds: float,
) -> str:
    """Single delivery attempt. Returns a `last_status` string.

    Never raises — the caller wants the categorised outcome, not a
    stack trace.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Signature": f"sha256={signature}",
        "X-NoralVoice-Schema": str(PAYLOAD_SCHEMA_VERSION),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
    except httpx.TimeoutException:
        return "timeout"
    except httpx.HTTPError as exc:
        return f"connection_error:{type(exc).__name__}"
    except Exception as exc:  # pragma: no cover — defensive
        return f"error:{type(exc).__name__}"

    if 200 <= resp.status_code < 300:
        return "ok"
    return f"http_{resp.status_code}"


async def deliver_with_retry(
    url: str,
    body_bytes: bytes,
    signature: str,
    max_attempts: int = MAX_ATTEMPTS,
    base_seconds: float = BACKOFF_BASE_SECONDS,
    factor: float = BACKOFF_FACTOR,
    timeout_seconds: float = PER_ATTEMPT_TIMEOUT_SECONDS,
) -> str:
    """Deliver with exponential backoff. Returns the final status.

    Retries on transient categories (timeout, connection_error, 5xx).
    Stops immediately on success or 4xx (downstream rejected the
    payload; retrying won't help).
    """
    last_status = "error:no_attempts"
    delay = base_seconds
    for attempt in range(1, max_attempts + 1):
        last_status = await _post_once(url, body_bytes, signature, timeout_seconds)
        if last_status == "ok":
            return last_status
        if last_status.startswith("http_4"):
            return last_status  # don't retry client errors
        if attempt < max_attempts:
            await asyncio.sleep(delay)
            delay *= factor
    return last_status


async def fire_integration_webhooks(
    _ctx, workflow_run_id: int, event_type: str
) -> None:
    """ARQ task. Look up registered webhooks for the run's org + event,
    build the payload, fire each with retries + signature.

    Failures are absorbed (logged + stamped on the registration's
    `last_status`) so a misbehaving downstream never blocks the run
    completion pipeline.
    """
    # Import locally — module init order matters here because
    # api.db is set up at first import and this task is loaded by arq
    # worker boot, not by the main FastAPI app.
    from api.db import db_client

    try:
        run = await db_client.get_workflow_run_by_id(workflow_run_id)
    except Exception:
        logger.exception(
            f"fire_integration_webhooks: failed to load run {workflow_run_id}"
        )
        return
    if run is None:
        logger.warning(
            f"fire_integration_webhooks: run {workflow_run_id} not found"
        )
        return

    workflow = run.workflow if hasattr(run, "workflow") else None
    organization_id = None
    if workflow and hasattr(workflow, "organization_id"):
        organization_id = workflow.organization_id

    if organization_id is None:
        # Fallback path for older runs where workflow.user holds the org.
        organization_id = await db_client.get_organization_id_by_workflow_run_id(
            workflow_run_id
        )

    if organization_id is None:
        logger.warning(
            f"fire_integration_webhooks: no org context for run {workflow_run_id}"
        )
        return

    webhooks = await db_client.get_integration_webhooks_for_event(
        organization_id=organization_id, event_type=event_type
    )
    if not webhooks:
        logger.debug(
            f"No integration webhooks registered for org={organization_id} "
            f"event={event_type}"
        )
        return

    if event_type == EVENT_RUN_COMPLETED:
        payload = build_run_completed_payload(run, workflow, organization_id)
    else:
        # Phase 1 only fires `run.completed`. The schema admits the
        # other event types so registrations don't have to change later,
        # but we don't synthesise payloads for events that haven't been
        # wired into a producer yet.
        logger.warning(
            f"fire_integration_webhooks: event {event_type} not yet produced; "
            f"skipping firing for org={organization_id}"
        )
        return

    body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    for wh in webhooks:
        signature = sign_payload(wh.secret, body_bytes)
        status = await deliver_with_retry(wh.target_url, body_bytes, signature)
        logger.info(
            f"integration_webhook fired id={wh.id} org={organization_id} "
            f"event={event_type} url={wh.target_url[:60]} status={status}"
        )
        try:
            await db_client.update_integration_webhook_firing(wh.id, status)
        except Exception:
            # Don't crash the task because a side-effect bookkeeping
            # write failed — the actual delivery is what matters.
            logger.exception(
                f"failed to stamp last_status for webhook {wh.id}"
            )


# State-machine helpers --------------------------------------------------

# The workflow_run table has exactly one terminal state today
# (COMPLETED). When the data layer detects a transition into that
# state, it enqueues a single arq job that fires every registered
# `run.completed` webhook. If/when `run.failed` or other terminal
# states are added, the producer-side mapping lives here.
TERMINAL_STATES = ("completed",)
TERMINAL_STATE_TO_EVENT: Mapping[str, str] = {
    "completed": EVENT_RUN_COMPLETED,
}


def event_for_terminal_state(state: str) -> str | None:
    """Map a terminal ``WorkflowRunState`` value to its webhook event,
    or return None if the state isn't terminal / doesn't map."""
    return TERMINAL_STATE_TO_EVENT.get(state)
