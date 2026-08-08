"""Phone-number management — import from Twilio, assign to agents.

The documented failure mode in this project is a number whose configuration is
never actually updated: it keeps silently serving its old destination while
everything else looks correct. :func:`assign_agent` therefore reads the number
back after writing and returns the observed state rather than assuming success.
"""

from __future__ import annotations

from typing import Any

from api.services.elevenlabs.client import ElevenLabsClient

PHONE_NUMBERS_PATH = "/v1/convai/phone-numbers"


class PhoneNumberAssignmentError(RuntimeError):
    """Raised when a number's agent assignment did not take effect.

    Deliberately loud. A silently unassigned number is the failure that looks
    like success right up until a real caller reaches the wrong destination.
    """


async def list_phone_numbers(client: ElevenLabsClient) -> list[dict[str, Any]]:
    return await client.get(PHONE_NUMBERS_PATH)


async def get_phone_number(
    client: ElevenLabsClient, phone_number_id: str
) -> dict[str, Any]:
    return await client.get(f"{PHONE_NUMBERS_PATH}/{phone_number_id}")


async def import_twilio_number(
    client: ElevenLabsClient,
    *,
    phone_number: str,
    label: str,
    twilio_account_sid: str,
    twilio_auth_token: str,
) -> dict[str, Any]:
    """Register an existing Twilio number with ElevenLabs.

    The Twilio credentials are passed straight through to the vendor and are
    never logged here. They come from the calling organization's own telephony
    configuration, not from the environment.
    """
    return await client.post(
        PHONE_NUMBERS_PATH,
        json={
            "phone_number": phone_number,
            "label": label,
            "sid": twilio_account_sid,
            "token": twilio_auth_token,
            "provider": "twilio",
        },
    )


async def assign_agent(
    client: ElevenLabsClient,
    phone_number_id: str,
    agent_id: str | None,
) -> dict[str, Any]:
    """Point a number at an agent, then verify it actually points there.

    Pass ``agent_id=None`` to unassign.

    Raises:
        PhoneNumberAssignmentError: if the read-back does not match what was
            requested. Better a loud failure at cutover than a number that
            keeps answering with the previous configuration.
    """
    await client.patch(
        f"{PHONE_NUMBERS_PATH}/{phone_number_id}",
        json={"agent_id": agent_id},
    )

    observed = await get_phone_number(client, phone_number_id)
    assigned = (observed.get("assigned_agent") or {}).get("agent_id")

    if assigned != agent_id:
        raise PhoneNumberAssignmentError(
            f"Phone number {phone_number_id} still resolves to agent "
            f"{assigned!r} after requesting {agent_id!r}. The number has NOT "
            "been cut over — it is still serving its previous destination."
        )

    return observed


async def delete_phone_number(client: ElevenLabsClient, phone_number_id: str) -> None:
    await client.delete(f"{PHONE_NUMBERS_PATH}/{phone_number_id}")
