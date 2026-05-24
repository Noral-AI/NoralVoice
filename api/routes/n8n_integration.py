"""Internal diagnostics for the hidden n8n automation layer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.services.auth.depends import get_superuser
from api.services.n8n_client import (
    NoralVoiceAutomationEvent,
    get_n8n_status,
    trigger_n8n_workflow,
)

router = APIRouter(prefix="/integrations/n8n", tags=["integrations"])


class N8nTestEventRequest(BaseModel):
    event_type: str = Field(
        default=NoralVoiceAutomationEvent.POST_CALL_SUMMARY_CREATED.value,
        alias="eventType",
    )
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
async def n8n_status(
    _user: UserModel = Depends(get_superuser),
) -> dict[str, Any]:
    """Return non-secret n8n configuration and health diagnostics."""
    return get_n8n_status()


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
            "request_id": payload["metadata"].get("requestId"),
        },
    )
    return result.to_dict()
