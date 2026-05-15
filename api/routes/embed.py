"""Cross-domain iframe auth bridge for NoralVoice deep pages.

An external integration (the NoralOS plugin in Phase 4) authenticates
to ``POST /embed/exchange-token`` with its NoralVoice API key. The
response is a single-use, short-lived token wrapped in an embed URL.
The integration drops that URL into an iframe; the user's browser hits
``GET /embed-login``, which validates + consumes the token, sets a
session cookie scoped to the NoralVoice domain, and redirects to the
target path. The user then has a normal authenticated session in the
embedded NoralVoice UI.

Phase 1 ships just the contract; Phase 4 builds the parent surface.
"""

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urljoin

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.constants import BACKEND_API_ENDPOINT, ENVIRONMENT, UI_APP_URL
from api.db import db_client
from api.db.embed_exchange_token_client import hash_exchange_token
from api.db.models import UserModel
from api.enums import Environment
from api.services.auth.depends import get_user
from api.utils.auth import create_jwt_token

router = APIRouter(prefix="/embed", tags=["embed"])

# UI cookie names must match ui/src/lib/auth/server.ts and ui/src/middleware.ts.
# These are the brand-prefixed cookie names from Phase 0 brand tokens.
COOKIE_TOKEN = "noralvoice_auth_token"
COOKIE_USER = "noralvoice_auth_user"
# PHASE-5 COOKIE-MIGRATION — also write the legacy `dograh_*` cookies
# so a session embedded via the legacy iframe path keeps working
# through the dual-write window. Reader paths fall back to these.
# Remove in a follow-up after one release.
LEGACY_COOKIE_TOKEN = "dograh_auth_token"
LEGACY_COOKIE_USER = "dograh_auth_user"

# Exchange-token TTL clamps. The default is intentionally tight: the
# token is used immediately on iframe load; longer windows just widen
# the leak blast radius.
TTL_MIN_SECONDS = 30
TTL_MAX_SECONDS = 300
TTL_DEFAULT_SECONDS = 90


class ExchangeTokenRequest(BaseModel):
    target_user_email: str = Field(
        ..., description="Email of the NoralVoice user to log the iframe in as."
    )
    target_path: str = Field(
        ...,
        description="Relative path inside NoralVoice the user lands on, e.g. '/workflow/<uuid>'.",
        min_length=1,
        max_length=2048,
    )
    ttl_seconds: int = Field(
        TTL_DEFAULT_SECONDS,
        ge=TTL_MIN_SECONDS,
        le=TTL_MAX_SECONDS,
        description=f"Token lifetime in seconds (clamped {TTL_MIN_SECONDS}–{TTL_MAX_SECONDS}).",
    )


class ExchangeTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    embed_url: str


def _embed_base_url() -> str:
    """Where ``/embed-login`` lives. Prefers BACKEND_API_ENDPOINT for the
    parent (which served the API call) so the iframe origin matches the
    NoralVoice deployment exactly."""
    return BACKEND_API_ENDPOINT.rstrip("/")


def _resolve_target_user_in_org(
    email: str, organization_id: int
) -> "tuple[UserModel | None, bool]":
    """Sentinel — see async version below. Sync stub keeps mypy happy."""
    raise NotImplementedError


async def _resolve_target_user_in_org_async(
    email: str, organization_id: int
) -> "tuple[UserModel | None, bool]":
    """Look up a user by email and confirm they're in ``organization_id``.

    Returns ``(user, in_org)``. ``user`` is None if no such email exists.
    ``in_org`` distinguishes "no such user" from "user exists but not in
    your org" so the route can return a precise 403 vs 404 if it wants
    to — but we collapse both into 404 to avoid leaking which emails
    exist on the platform.
    """
    user = await db_client.get_user_by_email(email)
    if user is None:
        return None, False

    # Membership check: the user must either have the org as their
    # selected_organization_id or appear in the many-to-many
    # organization_users_association. selected_organization_id is the
    # fast path; the association table covers users that haven't
    # switched into the org as their default.
    if user.selected_organization_id == organization_id:
        return user, True

    # SELECT 1 FROM organization_users_association WHERE ...
    from api.db.models import organization_users_association  # local import

    async with db_client.async_session() as session:  # type: ignore[attr-defined]
        result = await session.execute(
            select(organization_users_association.c.organization_id).where(
                organization_users_association.c.user_id == user.id,
                organization_users_association.c.organization_id == organization_id,
            )
        )
        if result.first() is not None:
            return user, True

    return user, False


@router.post("/exchange-token", response_model=ExchangeTokenResponse)
async def create_exchange_token(
    request: ExchangeTokenRequest,
    user: UserModel = Depends(get_user),
) -> ExchangeTokenResponse:
    """Issue a one-shot iframe-login token.

    Caller auth: standard ``X-API-Key`` (or bearer). The caller's
    ``selected_organization_id`` defines which org the target user must
    belong to. We never trust the caller's email — only their key's org
    binding.
    """
    if user.selected_organization_id is None:
        raise HTTPException(status_code=400, detail="Caller has no organization context")

    target_user, in_org = await _resolve_target_user_in_org_async(
        request.target_user_email, user.selected_organization_id
    )
    if target_user is None or not in_org:
        # Collapse "no user" and "wrong org" into the same response so
        # the endpoint isn't a user-enumeration oracle.
        raise HTTPException(status_code=404, detail="Target user not found in your organization")

    if not request.target_path.startswith("/"):
        raise HTTPException(
            status_code=400,
            detail="target_path must be a relative path starting with '/'",
        )

    # 32 url-safe bytes → 43 chars; prefixed for readability in logs / UI.
    plaintext = f"emx_{secrets.token_urlsafe(32)}"
    token_hash = hash_exchange_token(plaintext)

    row = await db_client.create_embed_exchange_token(
        token_hash=token_hash,
        organization_id=user.selected_organization_id,
        target_user_id=target_user.id,
        target_path=request.target_path,
        ttl_seconds=request.ttl_seconds,
    )

    # ``safe=""`` forces percent-encoding of '/' so the path doesn't get
    # half-interpreted by intermediate URL parsers (proxies, sentry,
    # logging) that may treat it as a path delimiter.
    embed_url = (
        f"{_embed_base_url()}/api/v1/embed/embed-login"
        f"?token={quote(plaintext, safe='')}&path={quote(request.target_path, safe='')}"
    )

    logger.info(
        f"Exchange token issued for org={user.selected_organization_id} "
        f"target_user_id={target_user.id} ttl={request.ttl_seconds}s"
    )
    return ExchangeTokenResponse(
        token=plaintext,
        expires_at=row.expires_at,
        embed_url=embed_url,
    )


@router.get("/embed-login")
async def embed_login(
    token: str = Query(..., min_length=8, max_length=128),
    path: str = Query("/", min_length=1, max_length=2048),
) -> Response:
    """Validate + consume an exchange token, set session cookies, redirect.

    Called by the user's browser on iframe load. The handler runs inside
    the user's first-party context for ``voice.noral.ai`` (the iframe's
    own origin), so cookies set here are read by subsequent same-origin
    NoralVoice navigation as the user clicks around the embedded UI.
    """
    token_hash = hash_exchange_token(token)
    row = await db_client.consume_embed_exchange_token(token_hash)
    if row is None:
        # 410 Gone: the token was either never valid, already consumed,
        # or expired. We deliberately don't distinguish — same reasoning
        # as the 404 on exchange-token.
        raise HTTPException(
            status_code=410, detail="Embed token is invalid, expired, or already consumed"
        )

    if row.target_path != path:
        # The path the integration committed to at issuance must match
        # what the browser asks for. Catches a misuse where the iframe
        # tries to swap path post-issuance.
        raise HTTPException(
            status_code=410, detail="Embed token path mismatch"
        )

    target_user = await db_client.get_user_by_id(row.target_user_id)
    if target_user is None:
        raise HTTPException(status_code=410, detail="Embed token target user no longer exists")

    jwt_token = create_jwt_token(target_user.id, target_user.email or "")
    user_payload = {
        "id": target_user.id,
        "email": target_user.email,
        "organization_id": target_user.selected_organization_id,
        "provider_id": target_user.provider_id,
    }

    secure = ENVIRONMENT != Environment.LOCAL.value
    # SameSite=None is required for the iframe (cross-site context).
    # Browsers require Secure when SameSite=None; in local dev where
    # cookies travel http://localhost only, fall back to Lax so the
    # cookie still sets without TLS.
    samesite = "none" if secure else "lax"

    redirect_target = urljoin(UI_APP_URL.rstrip("/") + "/", path.lstrip("/"))
    response = RedirectResponse(url=redirect_target, status_code=302)
    common_cookie_kwargs = {
        "secure": secure,
        "samesite": samesite,
        "path": "/",
        "max_age": 60 * 60 * 24 * 7,  # mirror the auth flow's 7-day window
    }
    response.set_cookie(
        key=COOKIE_TOKEN,
        value=jwt_token,
        httponly=True,
        **common_cookie_kwargs,
    )
    response.set_cookie(
        key=COOKIE_USER,
        value=json.dumps(user_payload),
        # User payload is readable so client code can render display
        # name without an extra /auth/me round-trip; the token cookie
        # stays HttpOnly so JS can't ship it elsewhere.
        httponly=False,
        **common_cookie_kwargs,
    )
    # PHASE-5 COOKIE-MIGRATION — dual-write the legacy names.
    response.set_cookie(
        key=LEGACY_COOKIE_TOKEN,
        value=jwt_token,
        httponly=True,
        **common_cookie_kwargs,
    )
    response.set_cookie(
        key=LEGACY_COOKIE_USER,
        value=json.dumps(user_payload),
        httponly=False,
        **common_cookie_kwargs,
    )
    logger.info(
        f"Embed-login redirected target_user_id={target_user.id} to {redirect_target}"
    )
    return response
