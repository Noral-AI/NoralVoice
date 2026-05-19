"""
Native Google OAuth 2.0 (with PKCE) for NoralVoice.

Independent of the NoralOS SSO flow: this gives a direct path for users
who don't have a NoralOS account (or are signing in while
agent.noral.ai is unreachable). The minted session is identical in
shape to the local email/password flow, so `_handle_oss_auth` in
`depends.py` validates it without modification.

Flow:

  1. Browser hits /api/v1/auth/google/start.
     We generate a random `state` and a PKCE code_verifier, persist them
     in Redis under the state key, 302 the browser to Google's authorize
     endpoint with state + code_challenge.

  2. User logs in at Google, approves the scopes.
     Google 302s back to /api/v1/auth/google/callback with code + state.

  3. We look up the state in Redis (atomic GETDEL — single-use).
     POST to Google's token endpoint with the code + code_verifier.
     GET userinfo with the resulting access token.
     Validate email_verified (refuse otherwise — anyone could "claim" an
     unverified Gmail address by signing up for it).

  4. Find-or-create the local NoralVoice user. Link by email if an
     account already exists (matches our agent.noral.ai/Better Auth
     pattern). Mint a JWT with `sub=user.id` so subsequent requests
     authenticate via the existing `_handle_oss_auth` path.

  5. Set HttpOnly session cookies (matching the names + options from
     ui/src/app/api/auth/session/route.ts so the existing Next.js
     middleware reads them transparently) and 302 the browser to
     /after-sign-in.

Security notes:

  - state: CSRF defense. Random 32 bytes, URL-safe, single-use via
    Redis GETDEL, 10-min TTL. An attacker who tricks a user into
    visiting a malicious callback URL gets nothing — the state won't
    match anything in our store.
  - PKCE (S256): defense-in-depth against authorization-code
    interception. Required by Google for public clients; harmless
    overhead for confidential ones like ours.
  - email_verified: Google guarantees this is true only when the user
    has demonstrated control of the address (clicked a verify link, or
    Google federated from a domain Google owns like @gmail.com). We
    refuse the sign-in otherwise to prevent email-squatting attacks
    where someone claims an email address they don't own.
  - Client secret: never sent to the browser. Lives in env only.
  - Session cookies: HttpOnly (XSS can't exfiltrate), Secure (TLS-only
    in prod), SameSite=Lax (mitigates CSRF on session-bound endpoints),
    host-only (matches the existing email/password cookie scope —
    doesn't leak to other .noral.ai subdomains).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from loguru import logger

from api.constants import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_OAUTH_ENABLED,
    GOOGLE_OAUTH_POST_LOGIN_REDIRECT,
    GOOGLE_OAUTH_REDIRECT_URI,
)
from api.db import db_client
from api.enums import PostHogEvent
from api.services.auth import oauth_state
from api.services.posthog_client import capture_event
from api.utils.auth import create_jwt_token

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# openid + email + profile gets us the verified email and Google's stable
# `sub` user id. No additional scopes — Google flags broader scopes as
# "sensitive" or "restricted", forcing verification we don't need.
GOOGLE_SCOPES = "openid email profile"

# Cookie names mirror ui/src/app/api/auth/session/route.ts EXACTLY so the
# Next.js middleware reads either source transparently. The legacy
# dograh_* names exist for the PHASE-5 cookie-migration dual-write window.
TOKEN_COOKIE = "noralvoice_auth_token"
USER_COOKIE = "noralvoice_auth_user"
LEGACY_TOKEN_COOKIE = "dograh_auth_token"
LEGACY_USER_COOKIE = "dograh_auth_user"

# 30 days, same as the Next.js route.
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _require_enabled() -> None:
    """Operator-opt-in guard. 503 if the feature is off or misconfigured."""
    if not GOOGLE_OAUTH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not enabled on this instance.",
        )
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        # If the operator flipped the flag but didn't set credentials, fail
        # loudly rather than 302ing the user to a broken Google page.
        logger.error(
            "GOOGLE_OAUTH_ENABLED=true but GOOGLE_CLIENT_ID/SECRET are unset"
        )
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is misconfigured on this instance.",
        )


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 with S256."""
    # 32 random bytes → 43-char URL-safe verifier (well within RFC's
    # 43-128 char range).
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _is_secure_cookie() -> bool:
    """Secure flag in non-local environments only."""
    # Mirror the Next.js route's logic so dev (HTTP) and prod (HTTPS)
    # both work without per-env cookie tuning.
    return os.getenv("ENVIRONMENT", "local").lower() != "local"


def _set_session_cookies(response: RedirectResponse, token: str, user_payload: dict) -> None:
    """Write the auth cookies onto the redirect response in the format the
    existing Next.js middleware already reads."""
    import json as _json

    user_json = _json.dumps(user_payload)
    secure = _is_secure_cookie()
    common: dict[str, Any] = {
        "max_age": COOKIE_MAX_AGE_SECONDS,
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(TOKEN_COOKIE, token, **common)
    response.set_cookie(USER_COOKIE, user_json, **common)
    # PHASE-5 dual-write: legacy cookie names, same options. Drop when the
    # main session route drops them.
    response.set_cookie(LEGACY_TOKEN_COOKIE, token, **common)
    response.set_cookie(LEGACY_USER_COOKIE, user_json, **common)


async def start_oauth(request: Request) -> RedirectResponse:
    """Initiate the OAuth flow. Returns a 302 to Google's authorize URL."""
    _require_enabled()

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()

    await oauth_state.put(state, {"code_verifier": code_verifier})

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # access_type=offline would request a refresh token, but we don't
        # need one — the session is JWT-based and lasts 30 days.
        "prompt": "select_account",
    }
    return RedirectResponse(
        url=f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}",
        status_code=302,
    )


async def _exchange_code_for_token(code: str, code_verifier: str) -> str:
    """Trade an authorization code for an access token. Returns the token
    string; raises HTTPException on Google-side errors."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as e:
            logger.error(f"Google token endpoint network failure: {e}")
            raise HTTPException(
                status_code=502,
                detail="Could not reach Google to complete sign-in.",
            )

    if response.status_code != 200:
        # Google returns 4xx with a JSON body like
        # {"error": "invalid_grant", "error_description": "..."}.
        # The most common cause is a stale or already-used code; log the
        # detail but don't surface Google's wording to the user.
        logger.warning(
            f"Google token exchange failed: HTTP {response.status_code} "
            f"body={response.text[:300]}"
        )
        raise HTTPException(
            status_code=400,
            detail="Google sign-in failed. Please try again.",
        )

    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Malformed token response from Google.")

    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=502, detail="Google did not return an access token.")
    return access_token


async def _fetch_userinfo(access_token: str) -> dict[str, Any]:
    """GET Google's userinfo endpoint. Returns the JSON dict."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.RequestError as e:
            logger.error(f"Google userinfo network failure: {e}")
            raise HTTPException(
                status_code=502,
                detail="Could not reach Google to complete sign-in.",
            )

    if response.status_code != 200:
        logger.warning(
            f"Google userinfo failed: HTTP {response.status_code} "
            f"body={response.text[:300]}"
        )
        raise HTTPException(
            status_code=502,
            detail="Could not fetch Google profile for sign-in.",
        )

    try:
        return response.json()
    except ValueError:
        raise HTTPException(
            status_code=502, detail="Malformed userinfo response from Google."
        )


async def _find_or_create_user(google_sub: str, email: str):
    """Find the local user by email (linking), else create with a
    google-namespaced provider_id. Returns (user, was_created)."""
    existing = await db_client.get_user_by_email(email)
    if existing is not None:
        return existing, False
    provider_id = f"google:{google_sub}"
    user = await db_client.create_user_with_provider(
        email=email, provider_id=provider_id
    )
    return user, True


async def handle_callback(code: Optional[str], state: Optional[str]) -> RedirectResponse:
    """Complete the OAuth flow. Validates state, exchanges code, fetches
    userinfo, find-or-creates the local user, sets session cookies,
    redirects to the UI landing page."""
    _require_enabled()

    if not code or not state:
        raise HTTPException(
            status_code=400, detail="Missing code or state in Google callback."
        )

    payload = await oauth_state.pop(state)
    if payload is None:
        # Either expired, never existed, or already used. All three are
        # the same answer from the user's perspective: the link's no good.
        raise HTTPException(
            status_code=400,
            detail="Sign-in session expired or invalid. Please try again.",
        )
    code_verifier = payload.get("code_verifier")
    if not isinstance(code_verifier, str):
        # State store corruption or developer error; treat as invalid.
        raise HTTPException(status_code=400, detail="Malformed sign-in state.")

    access_token = await _exchange_code_for_token(code, code_verifier)
    userinfo = await _fetch_userinfo(access_token)

    email = userinfo.get("email")
    email_verified = userinfo.get("email_verified")
    google_sub = userinfo.get("sub")

    if not isinstance(email, str) or not email:
        raise HTTPException(
            status_code=403,
            detail="Your Google account did not return an email address.",
        )
    if email_verified is not True:
        raise HTTPException(
            status_code=403,
            detail="Your Google account must have a verified email to sign in.",
        )
    if not isinstance(google_sub, str) or not google_sub:
        raise HTTPException(
            status_code=502, detail="Google did not return a user id."
        )

    user, was_created = await _find_or_create_user(google_sub, email)

    capture_event(
        distinct_id=str(user.provider_id),
        event=PostHogEvent.SIGNED_UP if was_created else PostHogEvent.SIGNED_IN,
        properties={
            "organization_id": user.selected_organization_id,
            "auth_provider": "google",
        },
    )

    token = create_jwt_token(user.id, email)
    user_payload = {
        "id": user.id,
        "email": email,
        "organization_id": user.selected_organization_id,
        "provider_id": user.provider_id,
    }

    response = RedirectResponse(
        url=GOOGLE_OAUTH_POST_LOGIN_REDIRECT, status_code=302
    )
    _set_session_cookies(response, token, user_payload)
    return response
