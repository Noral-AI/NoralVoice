"""API routes for managing webhook credentials."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.enums import WebhookCredentialType
from api.sdk_expose import sdk_expose
from api.services.auth.depends import get_user

router = APIRouter(prefix="/credentials")


# Request/Response schemas
class CreateCredentialRequest(BaseModel):
    """Request schema for creating a webhook credential."""

    name: str
    description: Optional[str] = None
    credential_type: WebhookCredentialType
    credential_data: dict  # Validated based on credential_type


class UpdateCredentialRequest(BaseModel):
    """Request schema for updating a webhook credential."""

    name: Optional[str] = None
    description: Optional[str] = None
    credential_type: Optional[WebhookCredentialType] = None
    credential_data: Optional[dict] = None


class CredentialResponse(BaseModel):
    """Response schema for a webhook credential (never includes sensitive data)."""

    uuid: str
    name: str
    description: Optional[str]
    credential_type: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


def validate_credential_data(
    credential_type: WebhookCredentialType, credential_data: dict
) -> None:
    """Validate that credential_data matches the expected structure for the credential type.

    Args:
        credential_type: The type of credential
        credential_data: The credential data to validate

    Raises:
        HTTPException: If validation fails
    """
    if credential_type == WebhookCredentialType.NONE:
        # No data required
        return

    if credential_type == WebhookCredentialType.API_KEY:
        if "header_name" not in credential_data or "api_key" not in credential_data:
            raise HTTPException(
                status_code=400,
                detail="API Key credential requires 'header_name' and 'api_key' fields",
            )

    elif credential_type == WebhookCredentialType.BEARER_TOKEN:
        if "token" not in credential_data:
            raise HTTPException(
                status_code=400,
                detail="Bearer Token credential requires 'token' field",
            )

    elif credential_type == WebhookCredentialType.BASIC_AUTH:
        if "username" not in credential_data or "password" not in credential_data:
            raise HTTPException(
                status_code=400,
                detail="Basic Auth credential requires 'username' and 'password' fields",
            )

    elif credential_type == WebhookCredentialType.CUSTOM_HEADER:
        if (
            "header_name" not in credential_data
            or "header_value" not in credential_data
        ):
            raise HTTPException(
                status_code=400,
                detail="Custom Header credential requires 'header_name' and 'header_value' fields",
            )


def build_credential_response(credential) -> CredentialResponse:
    """Build a response from a credential model (excluding sensitive data)."""
    return CredentialResponse(
        uuid=credential.credential_uuid,
        name=credential.name,
        description=credential.description,
        credential_type=credential.credential_type,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get(
    "/",
    **sdk_expose(
        method="list_credentials",
        description="List webhook credentials available to the authenticated organization.",
    ),
)
async def list_credentials(
    user: UserModel = Depends(get_user),
) -> List[CredentialResponse]:
    """
    List all webhook credentials for the user's organization.

    Returns:
        List of credentials (without sensitive data)
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    credentials = await db_client.get_credentials_for_organization(
        user.selected_organization_id
    )

    return [build_credential_response(cred) for cred in credentials]


@router.post("/")
async def create_credential(
    request: CreateCredentialRequest,
    user: UserModel = Depends(get_user),
) -> CredentialResponse:
    """
    Create a new webhook credential.

    Args:
        request: The credential creation request

    Returns:
        The created credential (without sensitive data)
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    # Validate credential data structure
    validate_credential_data(request.credential_type, request.credential_data)

    try:
        credential = await db_client.create_credential(
            organization_id=user.selected_organization_id,
            user_id=user.id,
            name=request.name,
            description=request.description,
            credential_type=request.credential_type.value,
            credential_data=request.credential_data,
        )

        return build_credential_response(credential)

    except Exception as e:
        # Handle unique constraint violation
        if "unique_org_credential_name" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A credential with the name '{request.name}' already exists",
            )
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Provider credentials
#
# One credential per organization per provider ("elevenlabs"), set and rotated
# through the UI and never through env or code. The secret goes in and never
# comes back out: reads return last_four only (plan §9.1).
# ---------------------------------------------------------------------------

SUPPORTED_PROVIDERS = {"elevenlabs"}


class SetProviderCredentialRequest(BaseModel):
    """Request schema for installing or rotating a provider secret."""

    secret: str


class ProviderCredentialResponse(BaseModel):
    """What a read of a provider credential is allowed to disclose.

    Deliberately has no field that could carry the secret. This is the schema
    that enforces §9.1 — if a future change wants to return more, it has to add
    a field here, which is a visible decision rather than an accident.
    """

    provider: str
    configured: bool
    last_four: Optional[str] = None
    rotated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


def _require_supported_provider(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider '{provider}'",
        )
    return provider


def _require_organization(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )
    return user.selected_organization_id


@router.get("/providers/{provider}")
async def get_provider_credential(
    provider: str,
    user: UserModel = Depends(get_user),
) -> ProviderCredentialResponse:
    """Report whether a provider credential is installed, and show its last four.

    Never returns the secret. An organization with no credential gets
    `configured: false` rather than a 404, because "not set up yet" is a normal
    state the settings page renders, not an error.
    """
    organization_id = _require_organization(user)
    _require_supported_provider(provider)

    credential = await db_client.get_provider_credential(organization_id, provider)

    if not credential:
        return ProviderCredentialResponse(provider=provider, configured=False)

    return ProviderCredentialResponse(
        provider=provider,
        configured=True,
        last_four=credential.last_four,
        rotated_at=credential.rotated_at,
        created_at=credential.created_at,
    )


@router.put("/providers/{provider}")
async def set_provider_credential(
    provider: str,
    request: SetProviderCredentialRequest,
    user: UserModel = Depends(get_user),
) -> ProviderCredentialResponse:
    """Install or rotate the secret for a provider.

    Rotation is the same call as installation — there is no separate rotate
    endpoint, because a rotate that behaved differently from a set is a second
    code path handling the same secret, and one of the two would rot.
    """
    organization_id = _require_organization(user)
    _require_supported_provider(provider)

    secret = request.secret.strip()
    if not secret:
        raise HTTPException(status_code=422, detail="Secret must not be empty")

    credential = await db_client.set_provider_credential(
        organization_id=organization_id,
        user_id=user.id,
        provider=provider,
        secret=secret,
    )

    return ProviderCredentialResponse(
        provider=provider,
        configured=True,
        last_four=credential.last_four,
        rotated_at=credential.rotated_at,
        created_at=credential.created_at,
    )


@router.delete("/providers/{provider}", status_code=204)
async def revoke_provider_credential(
    provider: str,
    user: UserModel = Depends(get_user),
) -> None:
    """Revoke the active credential for a provider.

    Soft delete, so the row survives for audit. Revoking when nothing is
    installed is a 404 rather than a silent success — the caller asked to
    revoke something specific and it was not there.
    """
    organization_id = _require_organization(user)
    _require_supported_provider(provider)

    revoked = await db_client.revoke_provider_credential(organization_id, provider)
    if not revoked:
        raise HTTPException(
            status_code=404,
            detail=f"No active {provider} credential to revoke",
        )


@router.get("/{credential_uuid}")
async def get_credential(
    credential_uuid: str,
    user: UserModel = Depends(get_user),
) -> CredentialResponse:
    """
    Get a specific webhook credential by UUID.

    Args:
        credential_uuid: The UUID of the credential

    Returns:
        The credential (without sensitive data)
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    credential = await db_client.get_credential_by_uuid(
        credential_uuid, user.selected_organization_id
    )

    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    return build_credential_response(credential)


@router.put("/{credential_uuid}")
async def update_credential(
    credential_uuid: str,
    request: UpdateCredentialRequest,
    user: UserModel = Depends(get_user),
) -> CredentialResponse:
    """
    Update a webhook credential.

    Args:
        credential_uuid: The UUID of the credential to update
        request: The update request

    Returns:
        The updated credential (without sensitive data)
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    # Validate credential data if provided
    if request.credential_type and request.credential_data:
        validate_credential_data(request.credential_type, request.credential_data)

    try:
        credential = await db_client.update_credential(
            credential_uuid=credential_uuid,
            organization_id=user.selected_organization_id,
            name=request.name,
            description=request.description,
            credential_type=request.credential_type.value
            if request.credential_type
            else None,
            credential_data=request.credential_data,
        )

        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")

        return build_credential_response(credential)

    except HTTPException:
        raise
    except Exception as e:
        if "unique_org_credential_name" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A credential with the name '{request.name}' already exists",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{credential_uuid}")
async def delete_credential(
    credential_uuid: str,
    user: UserModel = Depends(get_user),
) -> dict:
    """
    Delete (soft delete) a webhook credential.

    Args:
        credential_uuid: The UUID of the credential to delete

    Returns:
        Success message
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    deleted = await db_client.delete_credential(
        credential_uuid, user.selected_organization_id
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")

    return {"status": "deleted", "uuid": credential_uuid}
