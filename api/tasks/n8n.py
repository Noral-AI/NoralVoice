"""ARQ tasks for hidden n8n automation delivery."""

from __future__ import annotations

from loguru import logger
from pipecat.utils.run_context import set_current_run_id

from api.db import db_client
from api.services.n8n_client import (
    NoralVoiceAutomationEvent,
    resolve_event_type,
    trigger_n8n_workflow,
)
from api.services.n8n_lifecycle import build_workflow_run_n8n_payload


async def trigger_n8n_automation_event(
    _ctx,
    event_type: str,
    workflow_run_id: int | None = None,
    payload: dict | None = None,
) -> None:
    """Build and deliver a NoralVoice automation event to n8n.

    This task intentionally swallows delivery failures. n8n is a backend side
    effect and must not disrupt the primary call flow.
    """
    try:
        event = resolve_event_type(event_type)
    except ValueError:
        logger.warning(f"Unsupported n8n automation event queued: {event_type}")
        return
    payload = payload or {}
    organization_id = None
    automation_slug: str | None = None

    if workflow_run_id is not None:
        set_current_run_id(workflow_run_id)
        run, organization_id = await db_client.get_workflow_run_with_context(
            workflow_run_id
        )
        if not run:
            logger.warning(
                f"trigger_n8n_automation_event: run {workflow_run_id} not found"
            )
            return
        automation_slug = getattr(
            getattr(run, "workflow", None), "n8n_automation_slug", None
        )
        payload = build_workflow_run_n8n_payload(
            run,
            event_type=event,
            organization_id=organization_id,
            overrides=payload,
        )

    # Override-supplied slug (rare — diagnostics / test endpoint) wins over
    # the agent's persisted slug.
    automation_slug = payload.get("automationSlug") or automation_slug

    result = await trigger_n8n_workflow(
        event,
        payload,
        options={
            "company_id": organization_id or payload.get("companyId"),
            "account_id": organization_id or payload.get("accountId"),
            "call_id": payload.get("callId"),
            "session_id": payload.get("sessionId") or workflow_run_id,
            "user_id": payload.get("userId"),
            "automation_slug": automation_slug,
            "trace_id": (payload.get("metadata") or {}).get("traceId"),
            "request_id": (payload.get("metadata") or {}).get("requestId"),
        },
    )
    if not result.success:
        logger.warning(
            f"n8n automation event {event.value} finished unsuccessfully: "
            f"{result.message}"
        )
