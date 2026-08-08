"""Inbound webhooks from ElevenLabs.

Two endpoints with very different characters:

**Post-call** (``/post-call``) sits outside the call path. It can be strict:
verify the signature, reject anything that fails, and let ElevenLabs retry.

**Conversation initiation** (``/conversation-initiation``) sits *inside* the
call path — ElevenLabs calls it while the caller is hearing the dial tone, and
waits for the dynamic variables before the first turn. It must be fast and it
must **fail open**: if we cannot enrich the call, the caller should still reach
a working agent with default variables rather than hear the line drop. An
outage in our enrichment must not become an outage in the client's phone line.

Neither endpoint is authenticated by a user session — they are called by the
vendor, so the signature is the authentication, and the organization is derived
from the payload rather than from a caller identity.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request, Response, status
from loguru import logger

from api.db.database import async_session
from api.services.elevenlabs import (
    MissingCredentialError,
    get_client_for_organization,
)
from api.services.elevenlabs.ingestion import (
    WebhookVerificationError,
    attach_recording,
    ingest_conversation,
    resolve_organization_for_agent,
    verify_webhook_signature,
)

router = APIRouter(prefix="/elevenlabs")

#: Shared secret ElevenLabs signs post-call webhooks with. This is the vendor's
#: signing secret, not an API key — it authenticates the vendor to us, and
#: cannot be used to call ElevenLabs.
WEBHOOK_SECRET_ENV_VAR = "ELEVENLABS_WEBHOOK_SECRET"

SIGNATURE_HEADER = "elevenlabs-signature"


@router.post("/post-call")
async def post_call_webhook(request: Request) -> Response:
    """Ingest a completed conversation.

    Returns 200 for anything successfully processed *or* already known —
    a duplicate is a success from the sender's point of view, and returning an
    error would make ElevenLabs retry something that is already stored.
    """
    body = await request.body()
    secret = os.getenv(WEBHOOK_SECRET_ENV_VAR, "")

    try:
        verify_webhook_signature(body, request.headers.get(SIGNATURE_HEADER), secret)
    except WebhookVerificationError as exc:
        # Logged without the body: an unverified payload is attacker-controlled
        # and should not be written to our logs verbatim.
        logger.warning(f"Rejected ElevenLabs webhook: {exc}")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    payload: dict[str, Any] = await request.json()

    # Post-call webhooks are enveloped: {"type": ..., "data": {...}}
    event_type = payload.get("type")
    data = payload.get("data") or payload

    if event_type and event_type not in {"post_call_transcription", None}:
        # Audio and failure events arrive on the same endpoint; acknowledge
        # them rather than 4xx-ing, which would trigger pointless retries.
        logger.debug(f"Ignoring ElevenLabs webhook of type {event_type}")
        return Response(status_code=status.HTTP_200_OK)

    async with async_session() as session:
        # Resolved up front rather than read back off the run, because the run
        # carries a workflow_id and the recording fetch needs the organization
        # to resolve a credential and to build the per-client storage prefix.
        agent_id = (data or {}).get("agent_id")
        organization_id = (
            await resolve_organization_for_agent(session, agent_id)
            if agent_id
            else None
        )

        run, created = await ingest_conversation(
            session, data, organization_id=organization_id
        )

        if created and run is not None and organization_id is not None:
            # Best-effort. A call with a transcript and no audio is still a
            # useful record, and reconciliation will not retry the download
            # because the run already exists — so this is logged, not raised.
            try:
                client = await get_client_for_organization(organization_id)
                await attach_recording(session, client, run, organization_id)
            except MissingCredentialError:
                logger.warning(
                    f"Ingested conversation {run.elevenlabs_conversation_id} but "
                    "could not fetch its recording: no credential for "
                    f"organization {organization_id}."
                )

        await session.commit()

    if run is None:
        # Unattributable. 200 so the vendor stops retrying — retrying will not
        # make the agent resolvable — but loud in our logs.
        return Response(status_code=status.HTTP_200_OK)

    return Response(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@router.post("/conversation-initiation")
async def conversation_initiation_webhook(request: Request) -> dict[str, Any]:
    """Supply dynamic variables before the first turn of an inbound call.

    **Fails open by design.** Every failure path returns an empty-but-valid
    payload rather than an error status, because this endpoint is in the call
    path: a 500 here risks the caller hearing nothing. A call that connects
    without enrichment is a degraded call; a call that does not connect is a
    lost customer.
    """
    empty: dict[str, Any] = {"dynamic_variables": {}}

    try:
        payload = await request.json()
    except Exception:
        logger.warning("ElevenLabs initiation webhook received an unparseable body")
        return empty

    agent_id = payload.get("agent_id")
    caller_id = payload.get("caller_id")
    called_number = payload.get("called_number")

    try:
        async with async_session() as session:
            organization_id = (
                await resolve_organization_for_agent(session, agent_id)
                if agent_id
                else None
            )

        if organization_id is None:
            logger.warning(
                f"Initiation webhook: no organization for agent {agent_id}; "
                "returning defaults so the call still connects."
            )
            return empty

        # Variables available to the agent's prompt on the first turn. Kept
        # deliberately small — anything slow belongs nowhere near this path.
        return {
            "dynamic_variables": {
                "caller_id": caller_id or "",
                "called_number": called_number or "",
            }
        }
    except Exception as exc:
        # Broad by intent. Whatever went wrong, the call must still connect.
        logger.opt(exception=True).error(
            f"Initiation webhook failed, returning defaults so the call "
            f"connects: {exc!r}"
        )
        return empty
