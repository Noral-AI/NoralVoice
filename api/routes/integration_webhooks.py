"""Registration endpoints for outbound integration webhooks.

External integrations (the NoralOS plugin in Phase 1B+) call these to
register a callback URL for ``run.completed`` / ``run.failed`` /
``campaign.progress``. The firing path itself lives in
``api/services/integration_webhooks.py`` and runs as an arq task.

The per-registration HMAC secret is generated server-side and returned
in the ``POST`` response exactly once. Subsequent ``GET`` only returns
metadata.
"""

import secrets
from datetime import datetime
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field, HttpUrl

from api.db import db_client
from api.db.integration_webhook_client import ALLOWED_EVENT_TYPES
from api.db.models import UserModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/integration-webhooks", tags=["integration-webhooks"])


EventTypeLiteral = Literal["run.completed", "run.failed", "campaign.progress"]


class IntegrationWebhookCreate(BaseModel):
    event_type: EventTypeLiteral = Field(
        ..., description="Which run / campaign event to subscribe to."
    )
    target_url: HttpUrl = Field(
        ..., description="HTTPS endpoint to POST the signed payload to."
    )
    # Phase 5d — optional reverse-RPC config. Plugin clients that want
    # to receive ``noralos://<plugin_id>/<tool_name>`` callbacks from
    # workflow Agent nodes register their callback URL here. If
    # ``reverse_rpc_secret`` is omitted the server generates one and
    # returns it in the create response (same one-shot reveal as the
    # outbound webhook ``secret``).
    reverse_rpc_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Optional HTTPS endpoint NoralVoice will POST to when a "
            "workflow Agent node invokes a `noralos://` tool. One per "
            "organization is sufficient; if multiple rows carry a value, "
            "the first non-null wins."
        ),
    )
    reverse_rpc_secret: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional pre-shared HMAC-SHA256 key for the reverse-RPC "
            "direction. Server generates one and returns it once if "
            "omitted. Distinct from the outbound `secret`."
        ),
    )


class IntegrationWebhookResponse(BaseModel):
    """Returned on list / get. ``secret`` and ``reverse_rpc_secret`` are
    OMITTED here — they're returned exactly once on create."""

    id: int
    event_type: EventTypeLiteral
    target_url: str
    created_at: datetime
    last_fired_at: datetime | None = None
    last_status: str | None = None
    # Phase 5d — expose the URL on read (lets operators verify their
    # plugin install). The secret itself is still write-only.
    reverse_rpc_url: str | None = None


class IntegrationWebhookCreateResponse(IntegrationWebhookResponse):
    """One-shot reveal of the per-registration HMAC secrets. Returned
    only on the POST response; the integration must persist them client-
    side. ``GET`` and ``LIST`` redact them."""

    secret: str
    reverse_rpc_secret: str | None = None


def _to_response(row, include_secret: bool = False):
    base = {
        "id": row.id,
        "event_type": row.event_type,
        "target_url": row.target_url,
        "created_at": row.created_at,
        "last_fired_at": row.last_fired_at,
        "last_status": row.last_status,
        "reverse_rpc_url": row.reverse_rpc_url,
    }
    if include_secret:
        return IntegrationWebhookCreateResponse(
            **base,
            secret=row.secret,
            reverse_rpc_secret=row.reverse_rpc_secret,
        )
    return IntegrationWebhookResponse(**base)


@router.post(
    "",
    response_model=IntegrationWebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration_webhook(
    request: IntegrationWebhookCreate,
    user: UserModel = Depends(get_user),
) -> IntegrationWebhookCreateResponse:
    """Register an outbound webhook.

    The caller's API-key org binding determines the subscription's org;
    we do NOT accept an `organization_id` parameter — that would be a
    cross-org write hazard.
    """
    if user.selected_organization_id is None:
        raise HTTPException(status_code=400, detail="Caller has no organization context")
    if request.event_type not in ALLOWED_EVENT_TYPES:
        # Should never hit — Pydantic Literal catches it — defensive.
        raise HTTPException(status_code=400, detail="Unknown event_type")

    secret = secrets.token_urlsafe(32)
    # Reverse-RPC config is optional. If a URL is supplied without a
    # secret, generate one server-side; if neither is supplied, leave
    # both NULL so the row participates only in the outbound path.
    reverse_rpc_url = str(request.reverse_rpc_url) if request.reverse_rpc_url else None
    reverse_rpc_secret: str | None = None
    if reverse_rpc_url:
        reverse_rpc_secret = request.reverse_rpc_secret or secrets.token_urlsafe(32)
    row = await db_client.create_integration_webhook(
        organization_id=user.selected_organization_id,
        event_type=request.event_type,
        target_url=str(request.target_url),
        secret=secret,
        reverse_rpc_url=reverse_rpc_url,
        reverse_rpc_secret=reverse_rpc_secret,
    )
    logger.info(
        f"integration_webhook registered id={row.id} org={user.selected_organization_id} "
        f"event={request.event_type} reverse_rpc={'on' if reverse_rpc_url else 'off'}"
    )
    return _to_response(row, include_secret=True)


@router.get("", response_model=List[IntegrationWebhookResponse])
async def list_integration_webhooks(
    user: UserModel = Depends(get_user),
) -> List[IntegrationWebhookResponse]:
    if user.selected_organization_id is None:
        raise HTTPException(status_code=400, detail="Caller has no organization context")
    rows = await db_client.list_integration_webhooks(user.selected_organization_id)
    return [_to_response(r) for r in rows]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_webhook(
    webhook_id: int,
    user: UserModel = Depends(get_user),
) -> None:
    if user.selected_organization_id is None:
        raise HTTPException(status_code=400, detail="Caller has no organization context")
    deleted = await db_client.delete_integration_webhook(
        webhook_id=webhook_id, organization_id=user.selected_organization_id
    )
    if not deleted:
        # Org-scoped delete — same response for "not yours" and "doesn't
        # exist" so the endpoint isn't an ID-enumeration oracle across
        # tenants.
        raise HTTPException(status_code=404, detail="Webhook not found")
