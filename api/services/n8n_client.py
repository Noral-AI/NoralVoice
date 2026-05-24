"""Hidden n8n automation client for NoralVoice.

n8n is treated strictly as a backend workflow execution engine. This module
does not expose n8n credentials, users, roles, or UI details to customer-facing
code.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import httpx
from loguru import logger

from api.constants import ENVIRONMENT

SECRET_HEADER_NAME = "X-Noral-Webhook-Secret"
DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_RETRY_COUNT = 2
TRANSIENT_STATUS_CODES = {408, 429}

# Per-agent slugs must be lowercase, dash-separated path segments — enforced
# by the DB check constraint on workflows.n8n_automation_slug and re-enforced
# here so URL builders never construct a malformed path even if a future
# caller bypasses DB validation.
AUTOMATION_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_AUTOMATION_SLUG_LENGTH = 64


class N8nConfigurationError(RuntimeError):
    """Raised when n8n is enabled but required server config is missing."""


class UnsupportedN8nEventError(ValueError):
    """Raised when an event is not in the supported NoralVoice automation set."""


class InvalidAutomationSlugError(ValueError):
    """Raised when an automation slug doesn't match the required format."""


def validate_automation_slug(slug: str | None) -> str | None:
    """Return a normalized slug or raise. ``None`` / blank passes through."""
    if slug is None:
        return None
    if not isinstance(slug, str):
        raise InvalidAutomationSlugError(
            f"automation slug must be a string, got {type(slug).__name__}"
        )
    candidate = slug.strip().lower()
    if not candidate:
        return None
    if len(candidate) > MAX_AUTOMATION_SLUG_LENGTH:
        raise InvalidAutomationSlugError(
            f"automation slug exceeds {MAX_AUTOMATION_SLUG_LENGTH} chars"
        )
    if not AUTOMATION_SLUG_PATTERN.match(candidate):
        raise InvalidAutomationSlugError(
            "automation slug must be lowercase alphanumerics separated by single dashes"
        )
    return candidate


class NoralVoiceAutomationEvent(str, Enum):
    INBOUND_CALL_RECEIVED = "INBOUND_CALL_RECEIVED"
    CALL_STARTED = "CALL_STARTED"
    CALL_COMPLETED = "CALL_COMPLETED"
    MISSED_CALL = "MISSED_CALL"
    VOICEMAIL_RECEIVED = "VOICEMAIL_RECEIVED"
    LEAD_CAPTURED = "LEAD_CAPTURED"
    APPOINTMENT_REQUESTED = "APPOINTMENT_REQUESTED"
    APPOINTMENT_BOOKED = "APPOINTMENT_BOOKED"
    SMS_FOLLOW_UP_REQUESTED = "SMS_FOLLOW_UP_REQUESTED"
    CRM_SYNC_REQUESTED = "CRM_SYNC_REQUESTED"
    HUMAN_HANDOFF_REQUIRED = "HUMAN_HANDOFF_REQUIRED"
    POST_CALL_SUMMARY_CREATED = "POST_CALL_SUMMARY_CREATED"
    TRANSCRIPT_READY = "TRANSCRIPT_READY"
    AGENT_ESCALATION = "AGENT_ESCALATION"


SUPPORTED_N8N_EVENTS: tuple[NoralVoiceAutomationEvent, ...] = tuple(
    NoralVoiceAutomationEvent
)


@dataclass(frozen=True)
class N8nConfig:
    enabled: bool
    base_url: str | None
    webhook_secret: str | None
    api_key: str | None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    retry_count: int = DEFAULT_RETRY_COUNT
    environment: str = ENVIRONMENT

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.webhook_secret)

    @property
    def base_url_host(self) -> str | None:
        if not self.base_url:
            return None
        return urlparse(self.base_url).netloc or None


@dataclass
class N8nTriggerOptions:
    request_id: str | None = None
    trace_id: str | None = None
    company_id: int | str | None = None
    account_id: int | str | None = None
    call_id: str | None = None
    session_id: int | str | None = None
    user_id: int | str | None = None
    automation_slug: str | None = None
    occurred_at: datetime | None = None
    include_raw_response: bool = False
    backoff_base_seconds: float = 0.25


@dataclass
class N8nTriggerResult:
    success: bool
    status_code: int | None = None
    execution_id: str | None = None
    message: str = ""
    raw_response: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": self.success,
            "statusCode": self.status_code,
            "executionId": self.execution_id,
            "message": self.message,
        }
        if self.raw_response is not None:
            result["rawResponse"] = self.raw_response
        return result


@dataclass
class N8nLastKnownStatus:
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lastSuccessAt": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "lastFailureAt": (
                self.last_failure_at.isoformat() if self.last_failure_at else None
            ),
            "lastFailureMessage": self.last_failure_message,
        }


_last_known_status = N8nLastKnownStatus()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Ignoring invalid integer value for {name}")
        return default


def load_n8n_config() -> N8nConfig:
    """Read n8n configuration from server-side environment variables."""
    enabled = _env_bool("N8N_ENABLED", default=False)
    base_url = (os.getenv("N8N_BASE_URL") or "").strip().rstrip("/") or None
    webhook_secret = (os.getenv("N8N_WEBHOOK_SECRET") or "").strip() or None
    api_key = (os.getenv("N8N_API_KEY") or "").strip() or None
    timeout_ms = max(1, _env_int("N8N_TIMEOUT_MS", DEFAULT_TIMEOUT_MS))
    retry_count = max(0, _env_int("N8N_RETRY_COUNT", DEFAULT_RETRY_COUNT))

    config = N8nConfig(
        enabled=enabled,
        base_url=base_url,
        webhook_secret=webhook_secret,
        api_key=api_key,
        timeout_ms=timeout_ms,
        retry_count=retry_count,
        environment=os.getenv("ENVIRONMENT", ENVIRONMENT),
    )
    if enabled and not config.configured:
        missing = []
        if not base_url:
            missing.append("N8N_BASE_URL")
        if not webhook_secret:
            missing.append("N8N_WEBHOOK_SECRET")
        raise N8nConfigurationError(
            f"n8n is enabled but missing required config: {', '.join(missing)}"
        )
    return config


def normalize_event_name(event_type: str) -> str:
    """Convert internal event names to URL-safe webhook slugs.

    Example: ``CALL_COMPLETED`` -> ``call-completed``.
    """
    value = str(event_type or "").strip()
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    return value.strip("-").lower()


def resolve_event_type(
    event_type: NoralVoiceAutomationEvent | str,
) -> NoralVoiceAutomationEvent:
    if isinstance(event_type, NoralVoiceAutomationEvent):
        return event_type

    raw = str(event_type or "").strip()
    if not raw:
        raise UnsupportedN8nEventError("event type is required")

    if raw in NoralVoiceAutomationEvent.__members__:
        return NoralVoiceAutomationEvent[raw]

    for supported in SUPPORTED_N8N_EVENTS:
        if raw == supported.value or normalize_event_name(raw) == normalize_event_name(
            supported.value
        ):
            return supported

    raise UnsupportedN8nEventError(f"unsupported n8n automation event: {raw}")


def get_webhook_url(
    event_type: NoralVoiceAutomationEvent | str,
    config: N8nConfig | None = None,
    automation_slug: str | None = None,
) -> str:
    """Build the n8n webhook URL.

    When ``automation_slug`` is set, the URL is namespaced by that slug:
    ``/webhook/noralvoice/{automation_slug}/{event-slug}``. This lets each
    NoralVoice agent route to its own dedicated n8n workflow instead of
    every agent sharing one webhook per event type. When the slug is
    ``None``, the legacy unnamespaced path is used so existing single-agent
    deployments continue working without reconfiguring n8n.
    """
    cfg = config or load_n8n_config()
    event = resolve_event_type(event_type)
    if not cfg.base_url:
        raise N8nConfigurationError("N8N_BASE_URL is required")
    event_slug = quote(normalize_event_name(event.value), safe="")
    normalized_namespace = validate_automation_slug(automation_slug)
    if normalized_namespace:
        ns = quote(normalized_namespace, safe="")
        return f"{cfg.base_url}/webhook/noralvoice/{ns}/{event_slug}"
    return f"{cfg.base_url}/webhook/noralvoice/{event_slug}"


def supported_event_descriptors() -> list[dict[str, str]]:
    return [
        {"name": event.value, "webhookSlug": normalize_event_name(event.value)}
        for event in SUPPORTED_N8N_EVENTS
    ]


def get_last_known_status() -> dict[str, Any]:
    return _last_known_status.to_dict()


def get_n8n_status() -> dict[str, Any]:
    try:
        config = load_n8n_config()
        config_error = None
    except N8nConfigurationError as exc:
        config = N8nConfig(
            enabled=True,
            base_url=(os.getenv("N8N_BASE_URL") or "").strip().rstrip("/") or None,
            webhook_secret=(os.getenv("N8N_WEBHOOK_SECRET") or "").strip() or None,
            api_key=(os.getenv("N8N_API_KEY") or "").strip() or None,
            timeout_ms=max(1, _env_int("N8N_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)),
            retry_count=max(0, _env_int("N8N_RETRY_COUNT", DEFAULT_RETRY_COUNT)),
            environment=os.getenv("ENVIRONMENT", ENVIRONMENT),
        )
        config_error = str(exc)

    return {
        "enabled": config.enabled,
        "configured": config.configured,
        "baseUrlHost": config.base_url_host,
        "supportedEvents": supported_event_descriptors(),
        "lastKnownStatus": get_last_known_status(),
        "configurationError": config_error,
    }


def _coerce_options(options: N8nTriggerOptions | Mapping[str, Any] | None):
    if options is None:
        return N8nTriggerOptions()
    if isinstance(options, N8nTriggerOptions):
        return options
    return N8nTriggerOptions(**dict(options))


def _metadata(
    event: NoralVoiceAutomationEvent,
    payload: Mapping[str, Any],
    options: N8nTriggerOptions,
    config: N8nConfig,
) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    occurred_at = options.occurred_at or datetime.now(UTC)

    def first_value(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None

    metadata.update(
        {
            "eventType": event.value,
            "source": "noralvoice",
            "occurredAt": occurred_at.isoformat(),
            "requestId": first_value(options.request_id, metadata.get("requestId")),
            "traceId": first_value(options.trace_id, metadata.get("traceId")),
            "companyId": first_value(
                options.company_id, payload.get("companyId"), payload.get("company_id")
            ),
            "accountId": first_value(
                options.account_id, payload.get("accountId"), payload.get("account_id")
            ),
            "callId": first_value(
                options.call_id, payload.get("callId"), payload.get("call_id")
            ),
            "sessionId": first_value(
                options.session_id, payload.get("sessionId"), payload.get("session_id")
            ),
            "userId": first_value(
                options.user_id, payload.get("userId"), payload.get("user_id")
            ),
            "automationSlug": first_value(
                options.automation_slug, metadata.get("automationSlug")
            ),
            "environment": config.environment,
        }
    )
    return {key: value for key, value in metadata.items() if value is not None}


def build_n8n_request_body(
    event_type: NoralVoiceAutomationEvent | str,
    payload: Mapping[str, Any] | None = None,
    options: N8nTriggerOptions | Mapping[str, Any] | None = None,
    config: N8nConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_n8n_config()
    event = resolve_event_type(event_type)
    payload_dict = dict(payload or {})
    opts = _coerce_options(options)
    return {
        "eventType": event.value,
        "source": "noralvoice",
        "occurredAt": (opts.occurred_at or datetime.now(UTC)).isoformat(),
        "metadata": _metadata(event, payload_dict, opts, cfg),
        "payload": payload_dict,
    }


def _extract_execution_id(response: httpx.Response, response_json: Any) -> str | None:
    header_id = response.headers.get("x-n8n-execution-id")
    if header_id:
        return header_id
    if isinstance(response_json, dict):
        for key in ("executionId", "execution_id", "id"):
            value = response_json.get(key)
            if value is not None:
                return str(value)
        data = response_json.get("data")
        if isinstance(data, dict):
            for key in ("executionId", "execution_id", "id"):
                value = data.get(key)
                if value is not None:
                    return str(value)
    return None


def _result_from_response(
    response: httpx.Response, include_raw_response: bool
) -> N8nTriggerResult:
    response_json: Any | None = None
    response_text: str | None = None
    try:
        response_json = response.json()
    except ValueError:
        response_text = response.text[:500] if response.text else None

    execution_id = _extract_execution_id(response, response_json)
    success = 200 <= response.status_code < 300
    raw_response = None
    if include_raw_response:
        raw_response = response_json if response_json is not None else response_text

    return N8nTriggerResult(
        success=success,
        status_code=response.status_code,
        execution_id=execution_id,
        message=(
            "n8n workflow triggered"
            if success
            else f"n8n webhook returned HTTP {response.status_code}"
        ),
        raw_response=raw_response,
    )


def _should_retry_result(result: N8nTriggerResult) -> bool:
    if result.success:
        return False
    if result.status_code is None:
        return True
    if result.status_code in TRANSIENT_STATUS_CODES:
        return True
    return result.status_code >= 500


def _record_result(result: N8nTriggerResult) -> None:
    now = datetime.now(UTC)
    if result.success:
        _last_known_status.last_success_at = now
        return
    _last_known_status.last_failure_at = now
    _last_known_status.last_failure_message = result.message[:500]


async def trigger_n8n_workflow(
    event_type: NoralVoiceAutomationEvent | str,
    payload: Mapping[str, Any] | None = None,
    options: N8nTriggerOptions | Mapping[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> N8nTriggerResult:
    """Trigger a hidden n8n webhook workflow.

    Returns a normalized result and absorbs configuration/request failures so
    callers can use this as a non-blocking automation side effect.
    """
    try:
        config = load_n8n_config()
    except N8nConfigurationError as exc:
        result = N8nTriggerResult(success=False, message=str(exc))
        _record_result(result)
        logger.warning(f"n8n trigger skipped: {exc}")
        return result

    if not config.enabled:
        return N8nTriggerResult(success=False, message="n8n integration disabled")

    try:
        event = resolve_event_type(event_type)
    except UnsupportedN8nEventError as exc:
        result = N8nTriggerResult(success=False, message=str(exc))
        _record_result(result)
        logger.warning(f"n8n trigger rejected: {exc}")
        return result

    opts = _coerce_options(options)
    try:
        url = get_webhook_url(event, config, automation_slug=opts.automation_slug)
    except InvalidAutomationSlugError as exc:
        result = N8nTriggerResult(success=False, message=str(exc))
        _record_result(result)
        logger.warning(f"n8n trigger rejected: {exc}")
        return result
    body = build_n8n_request_body(event, payload, opts, config)
    headers = {
        "Content-Type": "application/json",
        SECRET_HEADER_NAME: config.webhook_secret or "",
        "X-Noral-Event-Type": event.value,
    }
    if opts.automation_slug:
        headers["X-Noral-Automation-Slug"] = opts.automation_slug

    attempts = config.retry_count + 1
    timeout_seconds = config.timeout_ms / 1000
    result = N8nTriggerResult(success=False, message="n8n webhook not attempted")
    delay = opts.backoff_base_seconds

    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(url, json=body, headers=headers)
                result = _result_from_response(response, opts.include_raw_response)
            except httpx.TimeoutException:
                result = N8nTriggerResult(success=False, message="n8n webhook timed out")
            except httpx.RequestError as exc:
                result = N8nTriggerResult(
                    success=False,
                    message=f"n8n webhook request failed: {type(exc).__name__}",
                )

            if result.success or not _should_retry_result(result):
                break

            if attempt < attempts:
                await asyncio.sleep(delay)
                delay *= 2

    _record_result(result)
    if result.success:
        logger.info(
            f"n8n trigger succeeded event={event.value} status={result.status_code} "
            f"execution_id={result.execution_id}"
        )
    else:
        logger.warning(
            f"n8n trigger failed event={event.value} status={result.status_code} "
            f"message={result.message}"
        )
    return result
