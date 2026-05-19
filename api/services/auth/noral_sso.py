"""
Cross-product SSO: validate a Better Auth session cookie issued by
agent.noral.ai and map it to a local NoralVoice user.

This is Phase 2 of the cross-product SSO design. Phase 1 (agent side)
ships a `.noral.ai`-scoped session cookie via `BETTER_AUTH_COOKIE_DOMAIN`,
so the browser sends agent.noral.ai's cookie to voice.noral.ai too.

Module contract:

    Given the inbound `Cookie` header from the request, forward it to
    agent.noral.ai's Better Auth `/api/auth/get-session` endpoint. If the
    session is valid, get the user info back, find-or-create a local
    NoralVoice user keyed by Better Auth user id, return the local
    UserModel.

Resilience: agent.noral.ai going down must NOT silently mis-authorize
requests. On network failure we return None (caller responds 401) — never
an unauthenticated-but-passing path.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from loguru import logger

from api.db import db_client
from api.db.models import UserModel

# Default points at the canonical agent.noral.ai Better Auth endpoint.
# Override per-deployment via `NORALOS_SESSION_VALIDATE_URL`. Useful for
# staging environments or testing against a local NoralOS instance.
DEFAULT_VALIDATE_URL = "https://agent.noral.ai/api/auth/get-session"

# Short timeout — auth checks run on every request. 3s caps the impact
# when agent.noral.ai is slow; anything beyond that is a hard failure.
VALIDATE_TIMEOUT_S = 3.0


def _resolve_validate_url() -> str:
    """Read the validate URL from env each call so tests can override."""
    return os.getenv("NORALOS_SESSION_VALIDATE_URL", DEFAULT_VALIDATE_URL)


async def get_user_from_noralos_session(
    cookie_header: Optional[str],
) -> Optional[UserModel]:
    """
    Look up a local user from a Better Auth session cookie shared via the
    `.noral.ai` parent domain.

    Args:
        cookie_header: the raw `Cookie` header from the inbound request.
            We forward verbatim — Better Auth picks out its own
            session-token cookie by name (e.g. `noralos-default.session_token`).

    Returns:
        UserModel for the user behind the session, or None if the cookie
        is missing/invalid/expired, agent.noral.ai is unreachable, or the
        returned payload is malformed.

    Side effect: creates a local NoralVoice user record (via
    `get_or_create_user_by_provider_id` with `provider_id="noralos:{id}"`)
    when an agent.noral.ai user is seen for the first time. The new user
    starts with no organization assigned; the caller is responsible for
    assigning one before workflow access works.
    """
    if not cookie_header:
        return None

    validate_url = _resolve_validate_url()
    try:
        async with httpx.AsyncClient(timeout=VALIDATE_TIMEOUT_S) as client:
            response = await client.get(
                validate_url,
                headers={"Cookie": cookie_header},
            )
    except httpx.RequestError as e:
        # Network / DNS / timeout. agent.noral.ai might be down. Refuse
        # the auth (so we don't ever silently pass) but log loudly so the
        # operator can see the dependency failed.
        logger.warning(
            f"NoralOS SSO validate request failed (network): {e}"
        )
        return None

    if response.status_code == 401:
        # Cookie missing or session expired. Expected when the user isn't
        # signed in to agent.noral.ai. Not an error.
        return None

    if response.status_code != 200:
        logger.warning(
            f"NoralOS SSO validate returned HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )
        return None

    try:
        payload = response.json()
    except ValueError:
        logger.warning("NoralOS SSO validate returned non-JSON body")
        return None

    user_info = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user_info, dict):
        return None

    noralos_user_id = user_info.get("id")
    if not isinstance(noralos_user_id, str) or not noralos_user_id:
        return None

    email = user_info.get("email") if isinstance(user_info.get("email"), str) else None

    # Use a namespaced provider_id so we never collide with Stack Auth's
    # ids (which are also strings but in their own namespace).
    provider_id = f"noralos:{noralos_user_id}"
    user, was_created = await db_client.get_or_create_user_by_provider_id(
        provider_id=provider_id,
    )

    # Mirror the Stack Auth path's email-sync behaviour.
    if email and user.email != email:
        await db_client.update_user_email(user.id, email)
        user.email = email

    if was_created:
        logger.info(
            f"NoralOS SSO: provisioned local user id={user.id} "
            f"for noralos_user_id={noralos_user_id} email={email}"
        )

    return user
