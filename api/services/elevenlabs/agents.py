"""Agent CRUD against the ElevenLabs Agents API.

Every function takes a resolved :class:`ElevenLabsClient`, which is what binds
the call to an organization. None of them accept an API key, and none resolve
one themselves — that is deliberate, so the credential path stays in one place.
"""

from __future__ import annotations

from typing import Any

from api.services.elevenlabs.client import ElevenLabsClient

AGENTS_PATH = "/v1/convai/agents"


async def list_agents(
    client: ElevenLabsClient,
    *,
    page_size: int = 30,
    cursor: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """List agents in the workspace this organization's key belongs to."""
    params: dict[str, Any] = {"page_size": page_size}
    if cursor:
        params["cursor"] = cursor
    if search:
        params["search"] = search

    return await client.get(AGENTS_PATH, params=params)


async def get_agent(client: ElevenLabsClient, agent_id: str) -> dict[str, Any]:
    return await client.get(f"{AGENTS_PATH}/{agent_id}")


async def create_agent(
    client: ElevenLabsClient,
    *,
    name: str,
    prompt: str,
    first_message: str | None = None,
    language: str = "en",
    voice_id: str | None = None,
    llm: str | None = None,
    data_collection: dict[str, Any] | None = None,
    tool_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create an agent.

    ``data_collection`` maps directly onto the capability the migration audit
    identified as our dominant pattern — structured extraction. Note the
    platform caps these at 25 items per agent (40 on Trial/Enterprise); this
    function does not enforce that, because the vendor's error is clearer than
    a guess at which tier the caller is on.
    """
    agent_config: dict[str, Any] = {
        "prompt": {"prompt": prompt},
        "language": language,
    }
    if first_message is not None:
        agent_config["first_message"] = first_message
    if llm:
        agent_config["prompt"]["llm"] = llm
    if tool_ids:
        agent_config["prompt"]["tool_ids"] = tool_ids

    conversation_config: dict[str, Any] = {"agent": agent_config}
    if voice_id:
        conversation_config["tts"] = {"voice_id": voice_id}

    body: dict[str, Any] = {
        "name": name,
        "conversation_config": conversation_config,
    }
    if data_collection:
        body["platform_settings"] = {
            "data_collection": data_collection,
        }

    return await client.post(AGENTS_PATH, json=body)


async def update_agent(
    client: ElevenLabsClient,
    agent_id: str,
    *,
    name: str | None = None,
    conversation_config: dict[str, Any] | None = None,
    platform_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch an agent. Only the fields supplied are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if conversation_config is not None:
        body["conversation_config"] = conversation_config
    if platform_settings is not None:
        body["platform_settings"] = platform_settings

    return await client.patch(f"{AGENTS_PATH}/{agent_id}", json=body)


async def delete_agent(client: ElevenLabsClient, agent_id: str) -> None:
    await client.delete(f"{AGENTS_PATH}/{agent_id}")


async def set_agent_retention(
    client: ElevenLabsClient,
    agent_id: str,
    *,
    transcript_retention_days: int,
    audio_retention_days: int,
) -> dict[str, Any]:
    """Set how long ElevenLabs keeps this agent's transcripts and audio.

    Worth calling deliberately on every agent we create. The platform default
    is **two years**, which is a long time to hold client call content on a
    shared workspace. ``0`` means delete immediately, ``-1`` means keep
    forever.

    Our own Postgres and MinIO are the durable copy, so vendor-side retention
    only has to outlive successful ingestion plus the reconciliation window —
    days, not years.
    """
    return await update_agent(
        client,
        agent_id,
        platform_settings={
            "privacy": {
                "transcript_retention_days": transcript_retention_days,
                "audio_retention_days": audio_retention_days,
            }
        },
    )
