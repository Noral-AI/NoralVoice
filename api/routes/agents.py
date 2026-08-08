"""Agent management — the control plane's own CRUD over ElevenLabs agents.

Every route resolves an ElevenLabs client from the caller's organization. There
is no route here that takes an agent id and acts on it without that resolution,
because on a shared workspace the vendor would happily serve another client's
agent to whoever asks. Ownership is enforced against **our** database — an
agent id the caller's organization does not have a workflow row for is a 404,
regardless of whether it exists vendor-side.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.routes.llm_settings import get_selected_llm
from api.services.auth.depends import get_user
from api.services.elevenlabs import (
    ElevenLabsAPIError,
    MissingCredentialError,
    create_agent,
    delete_agent,
    get_agent,
    get_client_for_organization,
    set_agent_retention,
    update_agent,
)

router = APIRouter(prefix="/agents")

#: Vendor-side retention defaults, in days.
#:
#: The platform default is two years. That is a long time to hold client call
#: content on a shared workspace, and our own Postgres and MinIO are the
#: durable copy — vendor retention only has to outlive successful ingestion
#: plus the reconciliation window. Audio gets the shorter life of the two
#: because it is the higher-risk artifact.
DEFAULT_TRANSCRIPT_RETENTION_DAYS = 30
DEFAULT_AUDIO_RETENTION_DAYS = 7


class CreateAgentRequest(BaseModel):
    name: str
    prompt: str
    first_message: Optional[str] = None
    language: str = "en"
    voice_id: Optional[str] = None
    data_collection: Optional[dict[str, Any]] = None
    # No `llm` field by design. The model is a platform-level choice made once
    # under Settings -> LLM and inherited by every agent, so it is not
    # something to get wrong per agent or to drift between them.


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    first_message: Optional[str] = None
    language: Optional[str] = None
    voice_id: Optional[str] = None
    data_collection: Optional[dict[str, Any]] = None


class AgentSummary(BaseModel):
    workflow_id: int
    agent_id: Optional[str]
    name: str


def _require_organization(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )
    return user.selected_organization_id


async def _resolve_client(organization_id: int):
    try:
        return await get_client_for_organization(organization_id)
    except MissingCredentialError as exc:
        # 409 rather than 500: nothing is broken, the operator has not finished
        # setting up. The message says exactly where to go.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _owned_workflow(organization_id: int, agent_id: str):
    """Return the caller's workflow row for an agent, or 404.

    Ownership is checked against our database rather than the vendor's, because
    on a shared workspace the vendor's answer is "yes, that agent exists" for
    every client's agent.
    """
    workflow = await db_client.get_workflow_by_elevenlabs_agent_id(
        organization_id, agent_id
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Agent not found")
    return workflow


@router.get("/")
async def list_organization_agents(
    user: UserModel = Depends(get_user),
) -> list[AgentSummary]:
    """List this organization's agents, from our own records.

    Deliberately sourced from our database rather than from the vendor: the
    vendor list is workspace-wide and would show every client's agents.
    """
    organization_id = _require_organization(user)
    workflows = await db_client.get_elevenlabs_workflows(organization_id)

    return [
        AgentSummary(
            workflow_id=w.id, agent_id=w.elevenlabs_agent_id, name=w.name
        )
        for w in workflows
    ]


@router.get("/{agent_id}")
async def get_organization_agent(
    agent_id: str,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    organization_id = _require_organization(user)
    await _owned_workflow(organization_id, agent_id)
    client = await _resolve_client(organization_id)

    try:
        return await get_agent(client, agent_id)
    except ElevenLabsAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/")
async def create_organization_agent(
    request: CreateAgentRequest,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Create an agent and record it against this organization.

    Retention is set immediately after creation rather than left at the
    vendor's two-year default — see the constants above.
    """
    organization_id = _require_organization(user)
    client = await _resolve_client(organization_id)

    # Inherited from the organization's choice rather than passed in, so every
    # agent this platform creates runs on the model the operator selected once.
    selection = await get_selected_llm(organization_id)

    try:
        created = await create_agent(
            client,
            name=request.name,
            prompt=request.prompt,
            first_message=request.first_message,
            language=request.language,
            voice_id=request.voice_id,
            llm=selection["identifier"],
            data_collection=request.data_collection,
        )
    except ElevenLabsAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    agent_id = created.get("agent_id")

    if agent_id:
        try:
            await set_agent_retention(
                client,
                agent_id,
                transcript_retention_days=DEFAULT_TRANSCRIPT_RETENTION_DAYS,
                audio_retention_days=DEFAULT_AUDIO_RETENTION_DAYS,
            )
        except ElevenLabsAPIError:
            # Non-fatal: the agent exists and works. Loud, because it means
            # this agent is sitting on the two-year default.
            from loguru import logger

            logger.opt(exception=True).error(
                f"Agent {agent_id} was created but retention could not be set; "
                "it is on the vendor default. Set it before real traffic."
            )

        await db_client.create_elevenlabs_workflow(
            organization_id=organization_id,
            user_id=user.id,
            name=request.name,
            elevenlabs_agent_id=agent_id,
        )

    return created


@router.patch("/{agent_id}")
async def update_organization_agent(
    agent_id: str,
    request: UpdateAgentRequest,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    organization_id = _require_organization(user)
    workflow = await _owned_workflow(organization_id, agent_id)
    client = await _resolve_client(organization_id)

    agent_config: dict[str, Any] = {}
    if request.prompt is not None:
        agent_config["prompt"] = {"prompt": request.prompt}
    if request.first_message is not None:
        agent_config["first_message"] = request.first_message
    if request.language is not None:
        agent_config["language"] = request.language

    conversation_config: dict[str, Any] = {}
    if agent_config:
        conversation_config["agent"] = agent_config
    if request.voice_id is not None:
        conversation_config["tts"] = {"voice_id": request.voice_id}

    platform_settings = (
        {"data_collection": request.data_collection}
        if request.data_collection is not None
        else None
    )

    try:
        updated = await update_agent(
            client,
            agent_id,
            name=request.name,
            conversation_config=conversation_config or None,
            platform_settings=platform_settings,
        )
    except ElevenLabsAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if request.name and request.name != workflow.name:
        await db_client.rename_workflow(workflow.id, organization_id, request.name)

    return updated


@router.delete("/{agent_id}", status_code=204)
async def delete_organization_agent(
    agent_id: str,
    user: UserModel = Depends(get_user),
) -> None:
    organization_id = _require_organization(user)
    workflow = await _owned_workflow(organization_id, agent_id)
    client = await _resolve_client(organization_id)

    try:
        await delete_agent(client, agent_id)
    except ElevenLabsAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Archived, not deleted — historical runs reference this workflow row.
    await db_client.archive_workflow(workflow.id, organization_id)
