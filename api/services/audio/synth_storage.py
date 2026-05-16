"""Storage helpers for one-shot TTS synth outputs.

Phase 6 — see docs/design/phase-6-nv-tts-synthesize.md.

Wraps the existing :class:`api.services.filesystem.s3.S3FileSystem`
helpers with a synth-specific path layout + pre-signed URL TTL policy
so the embed-synthesize route doesn't have to repeat that logic.

STATUS: WIP — skeleton only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional


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
    """

    audio_url: str
    storage_path: str
    content_type: str


class SynthStorageError(Exception):
    """Raised when the storage layer fails to accept the upload or
    can't return a pre-signed URL. Route layer translates to ``502
    storage_failed``."""


async def upload_synth_audio(
    audio_bytes: bytes,
    content_type: str,
    *,
    token_id: int,
    extension: Optional[str] = None,
) -> SynthUploadResult:
    """Upload one synth audio output and return a pre-signed GET URL.

    Args:
        audio_bytes: Raw audio bytes from :mod:`tts_one_shot`. See
            :data:`MAX_AUDIO_BYTES` for the upper bound.
        content_type: HTTP content type to set on the stored object
            (e.g. ``audio/mpeg`` or ``audio/wav``).
        token_id: Integer PK of the embed_token making the request.
            Used for path layout + future per-token janitor cleanup.
            We deliberately do NOT use the token secret in the path —
            secrets in URLs are an anti-pattern.
        extension: File extension matching the content type. Inferred
            from ``content_type`` if omitted (``audio/wav`` → ``wav``,
            ``audio/mpeg`` → ``mp3``).

    Returns:
        :class:`SynthUploadResult` with the pre-signed URL + the
        storage-path for downstream bookkeeping.

    Raises:
        SynthStorageError: if upload fails or the pre-signed URL can't
            be generated. Route layer turns this into ``502
            storage_failed``.

    Implementation plan (skeleton — see design doc §7):

      1. Validate ``len(audio_bytes) <= MAX_AUDIO_BYTES``; otherwise
         raise.
      2. Resolve the active filesystem via
         ``api.services.storage.get_filesystem()`` (existing helper).
      3. Build ``storage_path = f"{SYNTH_AUDIO_PREFIX}/{token_id}/{uuid4()}.{ext}"``.
      4. Wrap ``audio_bytes`` in a ``BytesIO`` and call
         ``await fs.acreate_file(storage_path, content)``.
      5. Generate pre-signed URL with
         ``await fs.aget_signed_url(storage_path,
         expiration=PRESIGNED_URL_TTL_SECONDS)``.
      6. Return :class:`SynthUploadResult`.
    """
    raise NotImplementedError(
        "synth_storage.upload_synth_audio is WIP. See "
        "docs/design/phase-6-nv-tts-synthesize.md §7."
    )


def _extension_for_content_type(content_type: str) -> str:
    """Map an HTTP content type to a file extension.

    Limited to the formats this endpoint emits (WAV, MP3). Anything
    else raises rather than silently picking a default.
    """
    raise NotImplementedError(
        "_extension_for_content_type is WIP. WAV / MP3 only."
    )


def _build_storage_path(token_id: int, extension: str) -> str:
    """Return the bucket-relative storage path for a new synth output.

    Pure-function helper; testable in isolation. UUID4 for uniqueness;
    token_id for namespacing per embed token.
    """
    return f"{SYNTH_AUDIO_PREFIX}/{token_id}/{uuid.uuid4()}.{extension}"
