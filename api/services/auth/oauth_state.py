"""
Single-use Redis store for OAuth state tokens.

Used by the Google OAuth flow to defend against CSRF: the start endpoint
generates a random `state` value, stores the matching PKCE code_verifier
under that state, then includes the state in the redirect to Google. When
Google redirects back, the callback looks the state up, deletes it, and
uses the code_verifier to complete the token exchange.

Single-use semantics matter: an attacker who somehow learns a state value
must not be able to replay it. The `pop` operation reads + deletes
atomically; a second `pop` for the same state returns None.

TTL bounds the window an unfinished flow occupies — abandoned starts get
garbage-collected automatically.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import REDIS_URL

# Namespace prefix keeps these keys distinct from anything else in Redis.
KEY_PREFIX = "oauth:google:state:"

# 10 minutes: more than enough for the user to complete Google's login,
# short enough that abandoned states don't linger.
DEFAULT_TTL_SECONDS = 600


_client: Optional[aioredis.Redis] = None


async def _get_client() -> aioredis.Redis:
    """Lazily create + cache a Redis client. Caller doesn't close it."""
    global _client
    if _client is None:
        _client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _key(state: str) -> str:
    return f"{KEY_PREFIX}{state}"


async def put(state: str, payload: dict[str, Any], ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    """Store the payload keyed by state, expiring after ttl_seconds."""
    client = await _get_client()
    await client.set(_key(state), json.dumps(payload), ex=ttl_seconds)


async def pop(state: str) -> Optional[dict[str, Any]]:
    """Atomically read and delete the payload for `state`.

    Returns None if no such state exists (expired, already consumed, or
    never stored). The atomicity is important: it makes replay impossible
    even under concurrent callback requests for the same state.
    """
    client = await _get_client()
    # GETDEL is atomic at the Redis level (single command); the alternative
    # (GET then DEL) leaves a race where two callers could both succeed.
    raw = await client.getdel(_key(state))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(f"OAuth state {state[:8]}... had unparseable payload")
        return None
