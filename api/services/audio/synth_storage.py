"""Storage helpers for one-shot TTS synth outputs.

Phase 6 — see docs/design/phase-6-nv-tts-synthesize.md.

Wraps the active storage backend (:mod:`api.services.storage`) with a
synth-specific path layout + pre-signed URL TTL policy so the
embed-synthesize route doesn't have to repeat that logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from loguru import logger

from api.services.storage import storage_fs


# Path layout — kept short for log readability + future janitor lifecycle.
# Full path: audio/synthesized/<token_id>/<uuid>.<ext>
SYNTH_AUDIO_PREFIX = "audio/synthesized"

# Pre-signed URL TTL. Long enough for slow clients to fetch, short
# enough that leaked links don't stay useful. Audio files themselves
# live in S3 for 24h (lifecycle policy — out of scope, see design §7).
PRESIGNED_URL_TTL_SECONDS = 5 * 60

# Bytes-per-second sanity cap on the input. 20 MB is enough for ~2
# minutes of MP3 at 128kbps; anything larger likely indicates a bug
# upstream (e.g. PCM with wrong sample rate).
MAX_AUDIO_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class SynthUploadResult:
    """Result of uploading a synth output to storage.

    Attributes:
        audio_url: Pre-signed GET URL the browser can use. TTL =
            :data:`PRESIGNED_URL_TTL_SECONDS`.
        storage_path: The bucket-relative path where the file lives.
            Useful for downstream cleanup / janitor jobs.
        content_type: Mirror of the request — set as Content-Type on
            the stored object so the browser plays it correctly.
        expires_at: When the pre-signed URL stops working.
    """

    audio_url: str
    storage_path: str
    content_type: str
    expires_at: datetime


class SynthStorageError(Exception):
    """Raised when the storage layer fails to accept the upload or
    can't return a pre-signed URL. Route layer translates to ``502
    storage_failed``."""


class _AsyncBytesReader:
    """Adapter so ``BaseFileSystem.acreate_file`` can consume bytes.

    The existing filesystem helpers expect a stream-like object whose
    ``read()`` is awaitable (matching aiofiles' shape). A raw
    :class:`io.BytesIO` won't satisfy that, so we wrap the buffer in a
    tiny coroutine-friendly reader.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._consumed = False

    async def read(self) -> bytes:
        # ``acreate_file`` calls read() once with no size arg; return
        # everything on the first call, empty bytes afterwards.
        if self._consumed:
            return b""
        self._consumed = True
        return self._data


async def upload_synth_audio(
    audio_bytes: bytes,
    content_type: str,
    *,
    path_namespace: str,
    extension: Optional[str] = None,
) -> SynthUploadResult:
    """Upload one synth audio output and return a pre-signed GET URL.

    Args:
        audio_bytes: Raw audio bytes from :mod:`tts_one_shot`.
        content_type: HTTP content type to set on the stored object
            (``audio/mpeg`` or ``audio/wav``).
        path_namespace: Short identifier used as the path prefix
            (e.g. ``"token-42"`` for embed_token callers or
            ``"org-7"`` for apiKey-authed callers). Used for path
            layout + future per-caller janitor cleanup. We deliberately
            do NOT use any secret in the path.
        extension: File extension matching the content type. Inferred
            from ``content_type`` if omitted.

    Raises:
        SynthStorageError: if upload fails or the pre-signed URL can't
            be generated.
    """
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise SynthStorageError(
            f"Audio is {len(audio_bytes)} bytes; max allowed is {MAX_AUDIO_BYTES}"
        )

    ext = extension or _extension_for_content_type(content_type)
    storage_path = _build_storage_path(path_namespace, ext)

    upload_ok = await storage_fs.acreate_file(storage_path, _AsyncBytesReader(audio_bytes))
    if not upload_ok:
        logger.warning(
            f"synth_storage: upload to {storage_path} failed via {type(storage_fs).__name__}"
        )
        raise SynthStorageError(
            f"Storage backend rejected synth upload (namespace={path_namespace})"
        )

    # ``force_inline=True`` makes the browser play the audio in-page
    # rather than offering to download it.
    signed_url = await storage_fs.aget_signed_url(
        storage_path,
        expiration=PRESIGNED_URL_TTL_SECONDS,
        force_inline=True,
    )
    if not signed_url:
        raise SynthStorageError(
            f"Storage backend returned no pre-signed URL for {storage_path}"
        )

    expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_TTL_SECONDS)

    return SynthUploadResult(
        audio_url=signed_url,
        storage_path=storage_path,
        content_type=content_type,
        expires_at=expires_at,
    )


def _extension_for_content_type(content_type: str) -> str:
    """Map an HTTP content type to a file extension.

    Limited to the formats this endpoint emits (WAV, MP3). Anything
    else raises rather than silently picking a default.
    """
    if content_type == "audio/wav":
        return "wav"
    if content_type == "audio/mpeg":
        return "mp3"
    raise SynthStorageError(
        f"Unsupported content_type {content_type!r}; expected audio/wav or audio/mpeg"
    )


def _build_storage_path(path_namespace: str, extension: str) -> str:
    """Return the bucket-relative storage path for a new synth output.

    Pure-function helper; testable in isolation. UUID4 for uniqueness;
    ``path_namespace`` for grouping (per embed_token id or per org id).
    """
    return f"{SYNTH_AUDIO_PREFIX}/{path_namespace}/{uuid.uuid4()}.{extension}"
