"""Conversation retrieval — the read side of call ingestion.

The webhook (Phase 2) is the primary path; these functions back the
reconciliation job that catches whatever the webhook missed, and the on-demand
fetches the dashboard needs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.services.elevenlabs.client import ElevenLabsClient

CONVERSATIONS_PATH = "/v1/convai/conversations"


async def list_conversations(
    client: ElevenLabsClient,
    *,
    agent_id: str | None = None,
    page_size: int = 100,
    cursor: str | None = None,
    call_start_after_unix: int | None = None,
    call_start_before_unix: int | None = None,
) -> dict[str, Any]:
    """List conversations, newest first.

    ``call_start_after_unix`` is what makes reconciliation cheap — the job asks
    only for the window it might have missed rather than paging all history.
    """
    params: dict[str, Any] = {"page_size": page_size}
    if agent_id:
        params["agent_id"] = agent_id
    if cursor:
        params["cursor"] = cursor
    if call_start_after_unix is not None:
        params["call_start_after_unix"] = call_start_after_unix
    if call_start_before_unix is not None:
        params["call_start_before_unix"] = call_start_before_unix

    return await client.get(CONVERSATIONS_PATH, params=params)


async def iter_conversations_since(
    client: ElevenLabsClient,
    since: datetime,
    *,
    agent_id: str | None = None,
    page_size: int = 100,
    max_pages: int = 50,
):
    """Yield every conversation started since ``since``, following pagination.

    ``max_pages`` bounds the walk so a bad cursor or an unexpectedly large
    window cannot spin forever inside a scheduled job.
    """
    cursor: str | None = None
    pages = 0
    after_unix = int(since.timestamp())

    while pages < max_pages:
        payload = await list_conversations(
            client,
            agent_id=agent_id,
            page_size=page_size,
            cursor=cursor,
            call_start_after_unix=after_unix,
        )

        for conversation in payload.get("conversations", []) or []:
            yield conversation

        cursor = payload.get("next_cursor")
        if not payload.get("has_more") or not cursor:
            return
        pages += 1


async def get_conversation(
    client: ElevenLabsClient, conversation_id: str
) -> dict[str, Any]:
    """Fetch one conversation in full — transcript, analysis, metadata."""
    return await client.get(f"{CONVERSATIONS_PATH}/{conversation_id}")


async def get_conversation_audio(
    client: ElevenLabsClient, conversation_id: str
) -> bytes:
    """Fetch the recording.

    Note this returns nothing useful for an agent running under Zero Retention
    Mode, which stores no recordings by design. Callers that must work under
    ZRM should take audio from the post-call audio webhook instead.
    """
    return await client.get_bytes(f"{CONVERSATIONS_PATH}/{conversation_id}/audio")


def extract_run_fields(conversation: dict[str, Any]) -> dict[str, Any]:
    """Flatten a conversation payload into the fields we store on a run.

    Kept as a pure function so both the webhook and the reconciliation job
    write identical rows — if the two diverged, reconciliation would create
    subtly different records for the calls it recovered.
    """
    metadata = conversation.get("metadata") or {}
    analysis = conversation.get("analysis") or {}

    return {
        "elevenlabs_conversation_id": conversation.get("conversation_id"),
        "elevenlabs_agent_id": conversation.get("agent_id"),
        "status": conversation.get("status"),
        "duration_seconds": metadata.get("call_duration_secs"),
        "started_at_unix": metadata.get("start_time_unix_secs"),
        "transcript": conversation.get("transcript"),
        "gathered_context": analysis.get("data_collection_results") or {},
        "call_successful": analysis.get("call_successful"),
        "transcript_summary": analysis.get("transcript_summary"),
    }
