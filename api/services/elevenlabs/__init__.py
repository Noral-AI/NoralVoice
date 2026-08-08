"""ElevenLabs Agents integration.

This package is the whole of our coupling to the vendor. There is deliberately
no provider abstraction behind it (plan §9.3): switching vendors would mean
rewriting this package, and the mitigation for that is data ownership — every
conversation, transcript, extracted field and recording lands in our own
Postgres and MinIO — not indirection.

**No ambient credential.** Import :func:`get_client_for_organization` and
resolve a client for the organization you are acting on. There is no
module-level client here and no environment fallback, by design; see
``client.py`` for why.
"""

from api.services.elevenlabs.agents import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    set_agent_retention,
    update_agent,
)
from api.services.elevenlabs.client import (
    PROVIDER,
    ElevenLabsAPIError,
    ElevenLabsClient,
    ElevenLabsError,
    MissingCredentialError,
    get_client_for_organization,
)
from api.services.elevenlabs.conversations import (
    extract_run_fields,
    get_conversation,
    get_conversation_audio,
    iter_conversations_since,
    list_conversations,
)
from api.services.elevenlabs.phone_numbers import (
    PhoneNumberAssignmentError,
    assign_agent,
    delete_phone_number,
    get_phone_number,
    import_twilio_number,
    list_phone_numbers,
)

__all__ = [
    "PROVIDER",
    "ElevenLabsAPIError",
    "ElevenLabsClient",
    "ElevenLabsError",
    "MissingCredentialError",
    "PhoneNumberAssignmentError",
    "assign_agent",
    "create_agent",
    "delete_agent",
    "delete_phone_number",
    "extract_run_fields",
    "get_agent",
    "get_client_for_organization",
    "get_conversation",
    "get_conversation_audio",
    "get_phone_number",
    "import_twilio_number",
    "iter_conversations_since",
    "list_agents",
    "list_conversations",
    "list_phone_numbers",
    "set_agent_retention",
    "update_agent",
]
