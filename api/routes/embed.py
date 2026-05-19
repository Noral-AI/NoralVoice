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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.constants import BACKEND_API_ENDPOINT, ENVIRONMENT, UI_APP_URL
from api.db import db_client
from api.db.embed_exchange_token_client import hash_exchange_token
from api.db.models import UserModel
from api.enums import Environment
from api.routes.public_embed import validate_origin
from api.services.audio import synth_storage
from api.services.audio.exfiltration_guard import scan_for_secrets
from api.services.auth.depends import _handle_api_key_auth, get_user
from api.services.pipecat import tts_one_shot
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


# ---------------------------------------------------------------------------
# Phase 6 — POST /embed/synthesize (WIP skeleton)
#
# Public TTS-as-an-HTTP-endpoint, embed-token authenticated. Designed for
# NoralOS Conference Room sessions that need NV's 9-provider TTS catalog
# without spinning up a full workflow_run.
#
# This is a SKELETON for design review. The handler currently returns
# ``501 Not Implemented`` — full implementation lands in a follow-up PR
# against this same branch. See:
#
#     docs/design/phase-6-nv-tts-synthesize.md
#
# Pairs with NoralOS PR-A (`feat/phase-6a-conf-room-nv-tts`) which depends
# on this endpoint being live before its Conference Room dual-path can flip
# the flag to "new" in production.
# ---------------------------------------------------------------------------


# Hard cap on synth text length. Matches voice-cascade's
# SPOKEN_RESPONSE_CAP_CHARS; anything longer is almost certainly a bug
# (the calling agent forgot to truncate) and would be expensive to
# synthesize.
SYNTHESIZE_TEXT_MAX_CHARS = 4000


class SynthesizeVoiceOverride(BaseModel):
    """Optional per-call voice override. All three fields required when present.

    If omitted from the request body, the synth uses the embed_token
    owner's stored ``user_configurations.tts`` settings.
    """

    provider: str = Field(
        ...,
        description=(
            "TTS provider id matching NoralVoice's catalog "
            "(elevenlabs | cartesia | deepgram | openai | sarvam | rime | "
            "dograh | speaches | camb)."
        ),
        min_length=1,
        max_length=32,
    )
    voice_id: str = Field(
        ...,
        description="Provider-specific voice identifier.",
        min_length=1,
        max_length=128,
    )
    model: str = Field(
        ...,
        description="Provider-specific model identifier.",
        min_length=1,
        max_length=64,
    )


class SynthesizeRequest(BaseModel):
    """POST /embed/synthesize body.

    Authentication: pass EITHER an ``X-API-Key`` header (canonical
    NoralOS↔NoralVoice server-to-server credential) OR the ``token``
    field (embed_token for browser embed widgets). If both are present,
    ``X-API-Key`` wins and ``token`` is ignored.
    """

    token: str | None = Field(
        default=None,
        description=(
            "embed_token previously minted via the operator dashboard or "
            "POST /embed/exchange-token. Validated against is_active, "
            "expires_at, and allowed_domains (vs request Origin). Optional "
            "when X-API-Key header is supplied."
        ),
        max_length=512,
    )
    text: str = Field(
        ...,
        description=f"Text to synthesize. Caller MUST keep this ≤ {SYNTHESIZE_TEXT_MAX_CHARS} chars.",
        min_length=1,
        max_length=SYNTHESIZE_TEXT_MAX_CHARS,
    )
    voice_override: SynthesizeVoiceOverride | None = Field(
        default=None,
        description=(
            "Optional per-call voice override. If omitted, the embed "
            "token's owning user's stored TTS settings are used."
        ),
    )


class SynthesizeResponse(BaseModel):
    """POST /embed/synthesize response body."""

    audio_url: str = Field(
        ...,
        description="Pre-signed GET URL to the synthesized audio. Valid for ~5 minutes.",
    )
    expires_at: datetime = Field(
        ...,
        description="When the pre-signed URL stops working. UTC.",
    )
    content_type: str = Field(
        ...,
        description="HTTP Content-Type of the audio (audio/wav or audio/mpeg).",
    )
    duration_seconds: float = Field(
        ...,
        description="Approximate duration of the synthesized audio.",
    )
    char_count: int = Field(
        ...,
        description="Length of the input text. Returned for billing / audit.",
    )
    provider: str = Field(
        ...,
        description="Which provider actually synthesized the audio.",
    )


@router.post(
    "/synthesize",
    response_model=SynthesizeResponse,
    responses={
        401: {"description": "Invalid or expired credential (X-API-Key or embed_token)."},
        403: {"description": "Request origin not in token's allowed_domains."},
        422: {"description": "Invalid voice_override, text_too_long, or text matched exfiltration scan."},
        429: {"description": "Per-token rate limit exceeded."},
        500: {"description": "Synthesis failed after provider retries."},
        502: {"description": "Storage upload failed."},
    },
)
async def synthesize(
    request: SynthesizeRequest,
    http_request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> SynthesizeResponse:
    """One-shot TTS synthesis via NoralVoice's 9-provider catalog.

    Dual auth: ``X-API-Key`` header (server-to-server canonical credential)
    OR the ``token`` body field (embed_token for browser widgets). API
    key wins if both are supplied; domain check is skipped under apiKey
    auth (apiKeys aren't domain-scoped — they're trusted-server credentials).

    See ``docs/design/phase-6-nv-tts-synthesize.md`` for the full design.
    """
    # 1. Authenticate. apiKey path skips embed_token + domain checks.
    user_id_for_config: int
    path_namespace: str
    auth_method: str
    if x_api_key:
        try:
            user = await _handle_api_key_auth(x_api_key)
        except HTTPException:
            # Re-raise as-is; helper returns the right 401.
            raise
        user_id_for_config = user.id
        path_namespace = f"org-{user.selected_organization_id}"
        auth_method = "apiKey"
    else:
        if not request.token:
            raise HTTPException(
                status_code=401,
                detail="Authentication required: provide X-API-Key header or token field",
            )
        embed_token = await db_client.get_embed_token_by_token(request.token)
        if (
            embed_token is None
            or not embed_token.is_active
            or (embed_token.expires_at is not None and embed_token.expires_at < datetime.now(UTC))
        ):
            # Collapse {missing, inactive, expired} into a single 401 so the
            # endpoint isn't a token-state oracle.
            raise HTTPException(status_code=401, detail="invalid_embed_token")

        # 2. Domain-check the request origin against the token's allowlist.
        origin = http_request.headers.get("origin") or http_request.headers.get("referer") or ""
        if not validate_origin(origin, embed_token.allowed_domains or []):
            logger.warning(
                f"Synthesize: origin {origin!r} not in allowed_domains "
                f"{embed_token.allowed_domains} for token_id={embed_token.id}"
            )
            raise HTTPException(status_code=403, detail="origin_not_allowed")

        user_id_for_config = embed_token.created_by
        path_namespace = f"token-{embed_token.id}"
        auth_method = "embed_token"

    # 3. Resolve user → user_configurations.tts.
    user_config = await db_client.get_user_configurations(user_id_for_config)
    if user_config.tts is None:
        raise HTTPException(
            status_code=500,
            detail="synthesis_failed: caller has no TTS configuration",
        )

    # 4. Overlay voice_override (Pydantic already rejected partials).
    if request.voice_override is not None:
        override = request.voice_override
        # Pydantic discriminator on TTSConfig will reject unknown
        # providers; let the validation error bubble as 500 if the
        # caller picks one outside NV's catalog.
        try:
            user_config = user_config.model_copy(
                update={
                    "tts": user_config.tts.model_copy(
                        update={
                            "provider": override.provider,
                            "voice": override.voice_id,
                            "model": override.model,
                        }
                    )
                }
            )
        except Exception as exc:
            logger.warning(f"Synthesize: voice_override invalid: {exc}")
            raise HTTPException(status_code=422, detail="invalid_voice_override")
        logger.info(
            f"Synthesize: voice_override applied "
            f"(provider={override.provider}, voice_id={override.voice_id}, model={override.model})"
        )

    # 5. Exfiltration pre-flight. Block-on-match.
    secret_matches = scan_for_secrets(request.text)
    if secret_matches:
        match_types = sorted({m.type for m in secret_matches})
        logger.warning(
            f"Synthesize: text_blocked_exfiltration auth={auth_method} "
            f"namespace={path_namespace} types={match_types} count={len(secret_matches)}"
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "text_blocked_exfiltration",
                "match_types": match_types,
            },
        )

    # 6. Synthesize.
    try:
        synth_result = await tts_one_shot.synthesize(user_config, request.text)
    except tts_one_shot.TTSOneShotError as exc:
        logger.warning(f"Synthesize: tts_one_shot error: {exc}")
        raise HTTPException(status_code=500, detail="synthesis_failed")
    except Exception as exc:
        logger.warning(f"Synthesize: provider error {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="synthesis_failed")

    # 7. Upload to storage.
    try:
        upload_result = await synth_storage.upload_synth_audio(
            synth_result.audio_bytes,
            synth_result.content_type,
            path_namespace=path_namespace,
        )
    except synth_storage.SynthStorageError as exc:
        logger.warning(f"Synthesize: storage error (auth={auth_method}): {exc}")
        raise HTTPException(status_code=502, detail="storage_failed")

    return SynthesizeResponse(
        audio_url=upload_result.audio_url,
        expires_at=upload_result.expires_at,
        content_type=synth_result.content_type,
        duration_seconds=synth_result.duration_seconds,
        char_count=synth_result.char_count,
        provider=synth_result.provider,
    )
