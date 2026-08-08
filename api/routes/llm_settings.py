"""Platform-level LLM selection.

One choice per organization, inherited by every agent it creates — not a
per-agent setting. Changing it here changes what new agents run on.

**Two different things, deliberately kept apart:**

*Hosted models* — Claude, GPT, Gemini, Qwen — run on ElevenLabs' own
infrastructure. Selecting one is a config string. You do **not** supply an API
key for these; ElevenLabs bills them through your existing account. This is the
normal path and it costs nothing to switch between them.

*Custom endpoint (BYO-LLM)* — your own inference endpoint in the voice path.
This does need a URL and a key, and it is infrastructure the prime directive
otherwise forbids, so plan §9.2 caps it at two clients behind a stated latency
budget. The cap is enforced here rather than left to memory.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.enums import OrganizationConfigurationKey
from api.services.auth.depends import get_user
from api.services.elevenlabs.llms import (
    CUSTOM_LLM,
    catalogue_payload,
    is_known,
)

router = APIRouter(prefix="/llm")

#: Plan §9.2. Reaching for a third is a signal to re-examine the vendor
#: choice, not to raise the number.
BYO_LLM_CLIENT_CAP = 2

#: Used when an organization has not chosen. Low latency, low cost, and
#: capable enough for the inbound-reception work that dominates the portfolio.
DEFAULT_LLM = "gemini-2.5-flash"


class LLMSelection(BaseModel):
    identifier: str
    custom_url: Optional[str] = None
    custom_model_id: Optional[str] = None


class LLMSelectionResponse(BaseModel):
    identifier: str
    is_default: bool
    is_known: bool
    custom_url: Optional[str] = None
    custom_model_id: Optional[str] = None


def _require_organization(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )
    return user.selected_organization_id


async def get_selected_llm(organization_id: int) -> dict:
    """The LLM this organization's agents run on, with defaults applied.

    Callers that create agents use this rather than reading the config
    directly, so an organization that has never chosen still gets a sensible
    model instead of whatever the vendor defaults to.
    """
    stored = await db_client.get_configuration_value(
        organization_id, OrganizationConfigurationKey.LLM_SELECTION.value
    )
    if not stored or not isinstance(stored, dict) or not stored.get("identifier"):
        return {"identifier": DEFAULT_LLM, "is_default": True}

    return {**stored, "is_default": False}


async def _count_byo_llm_organizations(exclude_organization_id: int) -> int:
    """How many *other* organizations are already on a custom endpoint."""
    rows = await db_client.get_all_configurations_by_key(
        OrganizationConfigurationKey.LLM_SELECTION.value
    )
    return sum(
        1
        for row in rows
        if row["organization_id"] != exclude_organization_id
        and isinstance(row.get("value"), dict)
        and row["value"].get("identifier") == CUSTOM_LLM
    )


@router.get("/catalogue")
async def list_llms(user: UserModel = Depends(get_user)) -> list[dict[str, str]]:
    """The models available to choose from.

    Advisory, not exhaustive — the API accepts any identifier, so a model the
    vendor ships tomorrow works without waiting on a deploy from us.
    """
    _require_organization(user)
    return catalogue_payload()


@router.get("/selection")
async def get_llm_selection(
    user: UserModel = Depends(get_user),
) -> LLMSelectionResponse:
    organization_id = _require_organization(user)
    selection = await get_selected_llm(organization_id)

    return LLMSelectionResponse(
        identifier=selection["identifier"],
        is_default=selection.get("is_default", False),
        is_known=is_known(selection["identifier"]),
        custom_url=selection.get("custom_url"),
        custom_model_id=selection.get("custom_model_id"),
    )


@router.put("/selection")
async def set_llm_selection(
    request: LLMSelection,
    user: UserModel = Depends(get_user),
) -> LLMSelectionResponse:
    """Choose the LLM for this organization.

    An unrecognised identifier is accepted with a warning rather than rejected.
    The catalogue is a snapshot and the vendor's list moves faster than our
    releases; rejecting anything unlisted would make every new model wait on a
    deploy. A typo shows up immediately as a failing agent, which is a cheaper
    failure than a blocked upgrade.
    """
    organization_id = _require_organization(user)
    identifier = request.identifier.strip()

    if not identifier:
        raise HTTPException(status_code=422, detail="An LLM must be selected")

    if identifier == CUSTOM_LLM:
        if not request.custom_url:
            raise HTTPException(
                status_code=422,
                detail="A custom endpoint URL is required for BYO-LLM",
            )

        already = await _count_byo_llm_organizations(organization_id)
        if already >= BYO_LLM_CLIENT_CAP:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"BYO-LLM is capped at {BYO_LLM_CLIENT_CAP} organizations and "
                    f"{already} already use it. Running inference in the voice "
                    "path is infrastructure, not configuration — a third case "
                    "is a decision to re-examine the vendor choice, not to "
                    "raise the cap."
                ),
            )

    if not is_known(identifier):
        logger.warning(
            f"Organization {organization_id} selected LLM '{identifier}', which "
            "is not in our catalogue. Accepting it — the vendor ships models "
            "faster than we release — but verify it is spelled correctly."
        )

    value = {"identifier": identifier}
    if identifier == CUSTOM_LLM:
        value["custom_url"] = request.custom_url
        if request.custom_model_id:
            value["custom_model_id"] = request.custom_model_id

    await db_client.upsert_configuration(
        organization_id,
        OrganizationConfigurationKey.LLM_SELECTION.value,
        value,
    )

    logger.info(f"Organization {organization_id} selected LLM '{identifier}'")

    return LLMSelectionResponse(
        identifier=identifier,
        is_default=False,
        is_known=is_known(identifier),
        custom_url=value.get("custom_url"),
        custom_model_id=value.get("custom_model_id"),
    )
