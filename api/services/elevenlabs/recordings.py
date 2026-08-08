"""Fetch call recordings from ElevenLabs into our own object storage.

Why we keep our own copy rather than linking to the vendor's:

1. **Vendor retention is deliberately short.** Agents are created with a 7-day
   audio retention (see ``routes/agents.py``) precisely so client call content
   does not sit for two years on a shared workspace. A dashboard that linked to
   vendor-hosted audio would show dead players a week later.
2. **Data ownership is the exit strategy.** Plan §9.3 accepts no provider
   abstraction on the explicit condition that our copy stays complete —
   anything that would make it incomplete is a design error.

Storage path is per-client by construction, so one client's recordings can be
enumerated, exported or deleted without touching another's.
"""

from __future__ import annotations

import io

from loguru import logger

from api.services.elevenlabs.client import ElevenLabsAPIError
from api.services.elevenlabs.conversations import get_conversation_audio
from api.services.storage import get_current_storage_backend, get_storage


def recording_path(organization_id: int, conversation_id: str) -> str:
    """Per-client storage prefix for a recording.

    Client id first so the prefix is a real boundary — listing, lifecycle
    rules and per-client export all key off it.
    """
    return f"recordings/org-{organization_id}/{conversation_id}.mp3"


async def store_recording(
    client,
    organization_id: int,
    conversation_id: str,
) -> str | None:
    """Download a conversation's audio and store it under the client's prefix.

    Returns the storage path, or None if there was nothing to store.

    A missing recording is **not** an error. An agent running under Zero
    Retention Mode stores no audio by design, and a call can end before any
    audio exists. Treating those as failures would fill the logs with noise
    and make real failures harder to see.
    """
    try:
        audio = await get_conversation_audio(client, conversation_id)
    except ElevenLabsAPIError as exc:
        if exc.status_code == 404:
            logger.debug(
                f"No recording available for conversation {conversation_id} "
                "(zero-retention agent, or audio not produced)."
            )
            return None
        logger.opt(exception=True).error(
            f"Could not fetch recording for conversation {conversation_id}: {exc!r}"
        )
        return None

    if not audio:
        return None

    path = recording_path(organization_id, conversation_id)
    storage = get_storage()

    stored = await storage.acreate_file(path, io.BytesIO(audio))
    if not stored:
        logger.error(
            f"Failed to write recording for conversation {conversation_id} to "
            f"{path}. The call is ingested but has no playable audio."
        )
        return None

    logger.info(f"Stored recording for conversation {conversation_id} at {path}")
    return path


def storage_backend_name() -> str:
    """Which backend a freshly stored recording landed in."""
    return get_current_storage_backend().value
