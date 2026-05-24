"""Workflow-run payload helpers for hidden n8n automations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pipecat.utils.enums import EndTaskReason

from api.db.models import WorkflowRunModel
from api.enums import WorkflowRunState
from api.services.n8n_client import (
    N8nConfigurationError,
    NoralVoiceAutomationEvent,
    load_n8n_config,
)


CALL_STATE_TO_N8N_EVENT: dict[str, NoralVoiceAutomationEvent] = {
    WorkflowRunState.RUNNING.value: NoralVoiceAutomationEvent.CALL_STARTED,
}

LEAD_FIELD_KEYS = {
    "first_name": "firstName",
    "firstName": "firstName",
    "last_name": "lastName",
    "lastName": "lastName",
    "phone": "phone",
    "phone_number": "phone",
    "email": "email",
    "address": "address",
    "service_type": "serviceType",
    "serviceType": "serviceType",
    "urgency": "urgency",
    "notes": "notes",
}

APPOINTMENT_FIELD_KEYS = {
    "requested_date": "requestedDate",
    "requestedDate": "requestedDate",
    "confirmed_date": "confirmedDate",
    "confirmedDate": "confirmedDate",
    "calendar_event_id": "calendarEventId",
    "calendarEventId": "calendarEventId",
    "assigned_rep": "assignedRep",
    "assignedRep": "assignedRep",
}


def n8n_event_for_run_state(state: str | None) -> NoralVoiceAutomationEvent | None:
    if not state:
        return None
    return CALL_STATE_TO_N8N_EVENT.get(state)


def _first_value(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _last_status_callback(logs: dict[str, Any]) -> dict[str, Any]:
    callbacks = logs.get("telephony_status_callbacks") or []
    if isinstance(callbacks, list) and callbacks:
        latest = callbacks[-1]
        return latest if isinstance(latest, dict) else {}
    return {}


def _extract_mapped_fields(
    gathered_context: dict[str, Any], field_map: dict[str, str]
) -> dict[str, Any]:
    extracted = gathered_context.get("extracted_variables") or {}
    sources = [gathered_context, extracted]
    result: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for source_key, target_key in field_map.items():
            value = source.get(source_key)
            if value is not None and value != "":
                result[target_key] = value
    return result


def _call_duration_seconds(
    run: WorkflowRunModel,
    latest_status: dict[str, Any],
) -> int | float | None:
    usage_info = run.usage_info or {}
    cost_info = run.cost_info or {}
    value = _first_value(
        usage_info.get("call_duration_seconds"),
        cost_info.get("call_duration_seconds"),
        latest_status.get("duration"),
    )
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _summary_from_context(gathered_context: dict[str, Any]) -> Any:
    return _first_value(
        gathered_context.get("summary"),
        gathered_context.get("call_summary"),
        gathered_context.get("post_call_summary"),
    )


def _disposition_from_context(gathered_context: dict[str, Any]) -> Any:
    return _first_value(
        gathered_context.get("mapped_call_disposition"),
        gathered_context.get("call_disposition"),
        gathered_context.get("disposition"),
    )


def build_workflow_run_n8n_payload(
    run: WorkflowRunModel,
    *,
    event_type: NoralVoiceAutomationEvent,
    organization_id: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable, secret-free automation payload from a workflow run."""
    initial_context = run.initial_context or {}
    gathered_context = run.gathered_context or {}
    logs = run.logs or {}
    latest_status = _last_status_callback(logs)
    workflow = getattr(run, "workflow", None)
    summary = _summary_from_context(gathered_context)
    lead_fields = _extract_mapped_fields(gathered_context, LEAD_FIELD_KEYS)
    appointment_fields = _extract_mapped_fields(
        gathered_context, APPOINTMENT_FIELD_KEYS
    )

    source_provider = _first_value(
        initial_context.get("provider"),
        gathered_context.get("provider"),
        getattr(run, "mode", None),
    )
    call_id = _first_value(
        gathered_context.get("call_id"),
        run.cost_info.get("call_id") if run.cost_info else None,
        latest_status.get("call_id"),
    )
    company_id = organization_id or (
        getattr(workflow, "organization_id", None) if workflow else None
    )

    payload = {
        "companyId": company_id,
        "accountId": company_id,
        "agentId": getattr(workflow, "id", None) if workflow else run.workflow_id,
        "workflowId": run.workflow_id,
        "workflowRunId": run.id,
        "callId": call_id,
        "sessionId": run.id,
        "direction": _first_value(
            initial_context.get("direction"),
            str(run.call_type) if run.call_type else None,
        ),
        "callerPhone": _first_value(
            initial_context.get("caller_number"),
            latest_status.get("from_number"),
            latest_status.get("from"),
        ),
        "calleePhone": _first_value(
            initial_context.get("called_number"),
            initial_context.get("phone_number"),
            latest_status.get("to_number"),
            latest_status.get("to"),
        ),
        "callStatus": _first_value(latest_status.get("status"), run.state),
        "startedAt": run.created_at.isoformat() if run.created_at else None,
        "endedAt": _first_value(
            latest_status.get("timestamp"),
            datetime.now(UTC).isoformat()
            if event_type
            in {
                NoralVoiceAutomationEvent.CALL_COMPLETED,
                NoralVoiceAutomationEvent.MISSED_CALL,
                NoralVoiceAutomationEvent.VOICEMAIL_RECEIVED,
            }
            else None,
        ),
        "durationSeconds": _call_duration_seconds(run, latest_status),
        "recordingUrl": run.recording_url,
        "transcriptUrl": run.transcript_url,
        "summary": summary,
        "disposition": _disposition_from_context(gathered_context),
        "lead": lead_fields or None,
        "appointment": appointment_fields or None,
        "metadata": {
            "sourceProvider": source_provider,
            "rawProviderEventId": _first_value(
                latest_status.get("event_id"),
                latest_status.get("MessageSid"),
                latest_status.get("CallSid"),
                latest_status.get("CallUUID"),
                call_id,
            ),
            "traceId": _first_value(
                gathered_context.get("trace_id"),
                gathered_context.get("traceId"),
                gathered_context.get("trace_url"),
            ),
            "requestId": _first_value(
                gathered_context.get("request_id"),
                gathered_context.get("requestId"),
            ),
            "telephonyConfigurationId": initial_context.get(
                "telephony_configuration_id"
            ),
        },
    }

    if event_type == NoralVoiceAutomationEvent.INBOUND_CALL_RECEIVED:
        payload["callStatus"] = _first_value(payload["callStatus"], "received")
    if event_type == NoralVoiceAutomationEvent.MISSED_CALL:
        payload["callStatus"] = _first_value(payload["callStatus"], "missed")

    if overrides:
        payload.update(overrides)

    return _without_empty_values(payload)


def _without_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: _without_empty_values(item)
            for key, item in value.items()
            if item is not None and item != "" and item != {}
        }
        return cleaned
    if isinstance(value, list):
        return [_without_empty_values(item) for item in value if item is not None]
    return value


def infer_completion_events(run: WorkflowRunModel) -> list[NoralVoiceAutomationEvent]:
    """Infer post-call automation events from completed run context."""
    gathered_context = run.gathered_context or {}
    extracted = gathered_context.get("extracted_variables") or {}
    call_tags = gathered_context.get("call_tags") or []
    disposition = _disposition_from_context(gathered_context)

    events = [NoralVoiceAutomationEvent.CALL_COMPLETED]

    if run.transcript_url:
        events.append(NoralVoiceAutomationEvent.TRANSCRIPT_READY)

    if _summary_from_context(gathered_context):
        events.append(NoralVoiceAutomationEvent.POST_CALL_SUMMARY_CREATED)

    if (
        disposition == EndTaskReason.VOICEMAIL_DETECTED.value
        or "voicemail" in call_tags
        or "voicemail_detected" in call_tags
    ):
        events.append(NoralVoiceAutomationEvent.VOICEMAIL_RECEIVED)

    lead_fields = _extract_mapped_fields(gathered_context, LEAD_FIELD_KEYS)
    if lead_fields:
        events.append(NoralVoiceAutomationEvent.LEAD_CAPTURED)

    appointment_fields = _extract_mapped_fields(
        gathered_context, APPOINTMENT_FIELD_KEYS
    )
    if appointment_fields:
        if appointment_fields.get("confirmedDate") or appointment_fields.get(
            "calendarEventId"
        ):
            events.append(NoralVoiceAutomationEvent.APPOINTMENT_BOOKED)
        else:
            events.append(NoralVoiceAutomationEvent.APPOINTMENT_REQUESTED)

    if _truthy_flag(gathered_context, extracted, "sms_follow_up_requested"):
        events.append(NoralVoiceAutomationEvent.SMS_FOLLOW_UP_REQUESTED)

    if _truthy_flag(gathered_context, extracted, "crm_sync_requested"):
        events.append(NoralVoiceAutomationEvent.CRM_SYNC_REQUESTED)

    if (
        _truthy_flag(gathered_context, extracted, "human_handoff_required")
        or "transfer_success" in call_tags
        or "human_handoff" in call_tags
    ):
        events.append(NoralVoiceAutomationEvent.HUMAN_HANDOFF_REQUIRED)

    if _truthy_flag(gathered_context, extracted, "agent_escalation"):
        events.append(NoralVoiceAutomationEvent.AGENT_ESCALATION)

    return _dedupe_events(events)


def _truthy_flag(
    gathered_context: dict[str, Any],
    extracted: dict[str, Any],
    key: str,
) -> bool:
    camel_key = "".join(
        [
            part if idx == 0 else part.capitalize()
            for idx, part in enumerate(key.split("_"))
        ]
    )
    for source in (gathered_context, extracted):
        if not isinstance(source, dict):
            continue
        value = _first_value(source.get(key), source.get(camel_key))
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "requested"}
        if value is not None:
            return bool(value)
    return False


def _dedupe_events(
    events: list[NoralVoiceAutomationEvent],
) -> list[NoralVoiceAutomationEvent]:
    seen: set[NoralVoiceAutomationEvent] = set()
    result: list[NoralVoiceAutomationEvent] = []
    for event in events:
        if event in seen:
            continue
        seen.add(event)
        result.append(event)
    return result


async def enqueue_n8n_event(
    event_type: NoralVoiceAutomationEvent,
    *,
    workflow_run_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Queue n8n delivery without allowing queue failures to affect callers."""
    try:
        config = load_n8n_config()
        if not config.enabled:
            return

        from api.tasks.arq import enqueue_job
        from api.tasks.function_names import FunctionNames

        await enqueue_job(
            FunctionNames.TRIGGER_N8N_AUTOMATION_EVENT,
            event_type.value,
            workflow_run_id,
            payload or {},
        )
    except N8nConfigurationError:
        logger.exception(
            f"n8n automation event {event_type.value} not queued due to invalid config"
        )
    except Exception:
        logger.exception(
            f"Failed to enqueue n8n automation event {event_type.value}; continuing"
        )
