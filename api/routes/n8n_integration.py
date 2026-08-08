"""Internal diagnostics for the hidden n8n automation layer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.services.auth.depends import get_superuser, get_user
from api.services.n8n_client import (
    N8nConfigurationError,
    NoralVoiceAutomationEvent,
    get_n8n_status,
    load_n8n_config,
    trigger_n8n_workflow,
)

router = APIRouter(prefix="/integrations/n8n", tags=["integrations"])


class N8nTestEventRequest(BaseModel):
    event_type: str = Field(
        default=NoralVoiceAutomationEvent.POST_CALL_SUMMARY_CREATED.value,
        alias="eventType",
    )
    automation_slug: str | None = Field(
        default=None,
        alias="automationSlug",
        description=(
            "Optional per-agent namespace. When set, hits "
            "/webhook/noralvoice/{automationSlug}/{event-slug}."
        ),
    )
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
async def n8n_status(
    _user: UserModel = Depends(get_superuser),
) -> dict[str, Any]:
    """Return non-secret n8n configuration and health diagnostics."""
    return get_n8n_status()


@router.get("/webhook-info")
async def n8n_webhook_info(
    _user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Return the n8n base URL so the UI can render accurate webhook examples.

    Available to any authenticated user (not just superusers) because workflow
    owners need to see the URL pattern for their own automation slug.
    """
    try:
        config = load_n8n_config()
        return {
            "enabled": config.enabled,
            "configured": config.configured,
            "baseUrl": config.base_url,
        }
    except N8nConfigurationError:
        return {"enabled": False, "configured": False, "baseUrl": None}


@router.post("/test")
async def send_n8n_test_event(
    request_body: N8nTestEventRequest,
    request: Request,
    user: UserModel = Depends(get_superuser),
) -> dict[str, Any]:
    """Trigger a safe synthetic event for internal admins."""
    payload = {
        "test": True,
        "companyId": user.selected_organization_id,
        "accountId": user.selected_organization_id,
        "userId": user.id,
        "metadata": {
            "requestId": request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id"),
            "sourceProvider": "diagnostic",
        },
        **request_body.payload,
    }
    result = await trigger_n8n_workflow(
        request_body.event_type,
        payload,
        options={
            "company_id": user.selected_organization_id,
            "account_id": user.selected_organization_id,
            "user_id": user.id,
            "automation_slug": request_body.automation_slug,
            "request_id": payload["metadata"].get("requestId"),
        },
    )
    return result.to_dict()
