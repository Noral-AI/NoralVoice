"""One-shot TTS synthesis wrapper around Pipecat's streaming TTSService.

Phase 6 — see docs/design/phase-6-nv-tts-synthesize.md for the full design.

Pipecat TTS services are designed for streaming pipelines: each service's
``run_tts(text)`` is an async generator that yields
``TTSStartedFrame`` → ``TTSAudioRawFrame`` (one or more) → ``TTSStoppedFrame``.

This module wraps that pattern for one-shot use: take a user_config + text,
run the iterator to completion, concatenate the audio frames into a single
byte buffer, and return ``(audio_bytes, content_type, sample_rate)`` so the
caller can upload to storage and return a URL to the client.

STATUS: WIP — skeleton only. The ``synthesize()`` function below raises
``NotImplementedError`` pending implementation. The signature and docstrings
are stable; the implementation lands in a follow-up PR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.schemas.user_configuration import UserConfiguration


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynthesisResult:
    """Result of a one-shot TTS synthesis.

    Attributes:
        audio_bytes: Raw audio data in the format described by `content_type`.
        content_type: HTTP content type (e.g. ``audio/mpeg`` for MP3,
            ``audio/wav`` for WAV).
        sample_rate_hz: Sample rate of the audio. Useful when the format
            is raw PCM and the client must know the rate to play it.
        duration_seconds: Approximate duration. Computed from audio
            length + sample rate; may be slightly off for compressed
            formats.
        provider: Which TTS provider produced the audio
            (e.g. ``"elevenlabs"``). Mirrors
            ``user_config.tts.provider`` for caller-side logging.
        char_count: ``len(text)``. Returned for billing / quota
            attribution.
    """

    audio_bytes: bytes
    content_type: str
    sample_rate_hz: int
    duration_seconds: float
    provider: str
    char_count: int


class TTSOneShotError(Exception):
    """Raised when the wrapper itself fails (not the underlying provider).

    Typical causes: unsupported provider, malformed frames, downstream
    pipecat exception that the wrapper can't recover from. The route
    layer turns these into ``500 synthesis_failed`` responses with a
    short ``detail`` message.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def synthesize(
    user_config: "UserConfiguration",
    text: str,
    *,
    sample_rate_hz: int = 16000,
) -> SynthesisResult:
    """Run a Pipecat TTSService one-shot.

    Args:
        user_config: User configuration with `tts.provider`, `tts.api_key`,
            `tts.voice`, `tts.model`, etc. — the same shape
            ``service_factory.create_tts_service`` expects.
        text: Text to synthesize. Caller MUST validate length before
            calling; this function does not enforce limits.
        sample_rate_hz: Target sample rate for the pipeline / output.
            Defaults to 16000 (matches existing pipeline default).
            Some providers ignore this and emit at their native rate;
            the actual rate is reported back in the result.

    Returns:
        A :class:`SynthesisResult` with the audio bytes + metadata.

    Raises:
        TTSOneShotError: if the wrapper can't run the provider
            (unsupported, malformed config, etc.).
        Exception: bubbled-through pipecat provider errors (auth, rate
            limit, etc.). Route layer must catch and translate.

    Implementation plan (skeleton — see design doc §5):

      1. Build an ``AudioConfig`` with the requested sample rate.
      2. Call ``service_factory.create_tts_service(user_config, audio_config)``.
      3. ``async for frame in service.run_tts(text):`` collect frame types:
          - ``TTSStartedFrame`` — start marker; record provider start time.
          - ``TTSAudioRawFrame`` — append ``frame.audio`` to a bytearray.
          - ``TTSStoppedFrame`` — end marker; compute duration.
      4. Normalize the output:
          - If the provider emits raw PCM: prepend a WAV header so the
            browser can play it without a decoder.
          - If the provider emits MP3 (ElevenLabs, OpenAI): pass through
            with ``content_type="audio/mpeg"``.
          - The format-per-provider table is in the design doc §5.
      5. Return ``SynthesisResult``.

    Per-provider quirks live in private helpers below (``_wrap_pcm_as_wav``,
    ``_provider_native_content_type``).
    """
    raise NotImplementedError(
        "tts_one_shot.synthesize is WIP. See "
        "docs/design/phase-6-nv-tts-synthesize.md for the implementation plan."
    )


# ---------------------------------------------------------------------------
# Private helpers (stubs)
# ---------------------------------------------------------------------------


def _provider_native_content_type(provider: str) -> str:
    """Return the HTTP Content-Type the provider's native output uses.

    Per design doc §5: ElevenLabs + OpenAI emit MP3; everything else
    emits raw PCM that the wrapper then wraps in a WAV header.
    """
    raise NotImplementedError(
        "_provider_native_content_type is WIP. See design doc §5."
    )


def _wrap_pcm_as_wav(pcm_bytes: bytes, sample_rate_hz: int) -> bytes:
    """Prepend a 44-byte WAV header (PCM 16-bit mono) to a raw PCM buffer.

    Used by providers that emit raw PCM (Cartesia, Deepgram, Sarvam,
    Rime, Dograh, Speaches, Camb). ElevenLabs + OpenAI are pass-through
    MP3.

    The header is standard PCM WAVE: 16-bit signed, mono, with the
    sample rate the caller specifies. Bit depth / channels are
    intentionally not configurable here; if a provider ever returns
    different shapes the wrapper will fail loudly rather than emit
    silently-wrong audio.
    """
    raise NotImplementedError(
        "_wrap_pcm_as_wav is WIP. Standard 44-byte PCM WAVE header — "
        "see design doc §5."
    )
