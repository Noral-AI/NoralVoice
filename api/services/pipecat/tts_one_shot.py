"""One-shot TTS synthesis wrapper around Pipecat's streaming TTSService.

Phase 6 — see docs/design/phase-6-nv-tts-synthesize.md for the full design.

Pipecat TTS services are designed for streaming pipelines: each service's
``run_tts(text, context_id)`` is an async generator that yields
``TTSStartedFrame`` → ``TTSAudioRawFrame`` (one or more) → ``TTSStoppedFrame``.

This module wraps that pattern for one-shot use: take a user_config + text,
run the iterator to completion, concatenate the audio frames into a single
byte buffer, and return ``(audio_bytes, content_type, sample_rate, ...)``
so the caller can upload to storage and return a URL to the client.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from api.services.configuration.registry import ServiceProviders
from api.services.pipecat.audio_config import AudioConfig
from api.services.pipecat.service_factory import create_tts_service
from pipecat.frames.frames import (
    EndFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)

if TYPE_CHECKING:
    from api.schemas.user_configuration import UserConfiguration


# Every Pipecat TTS service in NV's catalog yields raw 16-bit signed PCM via
# TTSAudioRawFrame, so synthesize() WAV-wraps all of them before returning audio
# to the browser. This explicitly includes ElevenLabs (the WS service requests
# ``output_format=pcm_*``) and OpenAI (``response_format="pcm"``): an earlier
# design assumed those two emit MP3, but the streaming services that are wired
# up never do — that assumption shipped raw PCM mislabeled as ``audio/mpeg``,
# which browsers can't decode (or play at the wrong rate).


@dataclass(frozen=True)
class SynthesisResult:
    """Result of a one-shot TTS synthesis.

    Attributes:
        audio_bytes: Raw audio data in the format described by `content_type`.
        content_type: HTTP content type (``audio/mpeg`` for MP3, ``audio/wav``
            for WAV).
        sample_rate_hz: Sample rate of the audio. For WAV-wrapped output the
            header carries the rate; for MP3 it's informational (the file
            self-describes).
        duration_seconds: Approximate duration. Computed from audio length +
            sample rate; ballpark for MP3 (compressed) but accurate for PCM.
        provider: Which TTS provider produced the audio (mirrors
            ``user_config.tts.provider``).
        char_count: ``len(text)``. Returned for billing / quota attribution.
    """

    audio_bytes: bytes
    content_type: str
    sample_rate_hz: int
    duration_seconds: float
    provider: str
    char_count: int


class TTSOneShotError(Exception):
    """Raised when the wrapper itself fails (not the underlying provider).

    Route layer turns these into ``500 synthesis_failed`` responses.
    """


async def synthesize(
    user_config: "UserConfiguration",
    text: str,
    *,
    sample_rate_hz: int = 16000,
) -> SynthesisResult:
    """Run a Pipecat TTSService one-shot.

    Caller MUST validate text length before calling; this function does not
    enforce limits.

    The Pipecat lifecycle (``start(StartFrame)`` → iterate ``run_tts`` →
    ``stop(EndFrame)``) is required even outside a pipeline: ``start`` is
    what sets the service's internal sample rate, and ``stop`` is what
    closes long-lived WebSocket connections (ElevenLabs, Cartesia). Skipping
    either leaks resources or yields empty audio.
    """
    provider = user_config.tts.provider

    audio_config = AudioConfig(
        transport_in_sample_rate=sample_rate_hz,
        transport_out_sample_rate=sample_rate_hz,
        vad_sample_rate=sample_rate_hz,
        pipeline_sample_rate=sample_rate_hz,
    )
    service = create_tts_service(user_config, audio_config)

    start_frame = StartFrame(
        audio_in_sample_rate=sample_rate_hz,
        audio_out_sample_rate=sample_rate_hz,
    )

    audio_chunks: list[bytes] = []
    observed_sample_rate = sample_rate_hz
    observed_channels = 1
    context_id = str(uuid.uuid4())

    try:
        await service.start(start_frame)
        async for frame in service.run_tts(text, context_id):
            if isinstance(frame, TTSAudioRawFrame):
                audio_chunks.append(frame.audio)
                # First audio frame wins for the rate/channel info we
                # report; providers don't change mid-stream.
                if len(audio_chunks) == 1:
                    observed_sample_rate = frame.sample_rate or sample_rate_hz
                    observed_channels = frame.num_channels or 1
            elif isinstance(frame, (TTSStartedFrame, TTSStoppedFrame)):
                # Control frames — ignored, we just need the audio.
                continue
            # Any other frame type (ErrorFrame, etc.) is silently dropped
            # here; provider errors raise before the iterator yields.
    except Exception as exc:
        logger.warning(
            f"tts_one_shot: provider={provider} run_tts raised {type(exc).__name__}: {exc}"
        )
        # Best-effort cleanup; ignore stop errors if we're already in a
        # broken state.
        try:
            await service.stop(EndFrame())
        except Exception:
            pass
        raise
    else:
        try:
            await service.stop(EndFrame())
        except Exception as exc:
            logger.debug(
                f"tts_one_shot: provider={provider} stop() raised "
                f"{type(exc).__name__}; audio was already collected"
            )

    if not audio_chunks:
        raise TTSOneShotError(
            f"Provider {provider!r} returned zero audio frames for text of length {len(text)}"
        )

    raw_audio = b"".join(audio_chunks)
    content_type = _provider_native_content_type(provider)

    if content_type == "audio/wav":
        # Raw PCM from the provider. Wrap in a WAV header so the
        # browser can play it without a decoder.
        if observed_channels != 1:
            raise TTSOneShotError(
                f"Provider {provider!r} returned multi-channel PCM "
                f"(num_channels={observed_channels}); the WAV-wrap helper "
                "is mono-only. Either configure the provider for mono or "
                "extend _wrap_pcm_as_wav."
            )
        audio_bytes = _wrap_pcm_as_wav(raw_audio, observed_sample_rate)
        # PCM duration is exact: bytes / (rate * 2 bytes/sample * channels)
        duration_seconds = len(raw_audio) / (observed_sample_rate * 2)
    else:
        # Provider emitted self-describing MP3; pass through.
        audio_bytes = raw_audio
        # MP3 duration estimate from byte size at typical 128kbps. Good
        # enough for the response (caller uses it for UX hinting, not
        # billing).
        duration_seconds = len(raw_audio) * 8 / 128_000

    return SynthesisResult(
        audio_bytes=audio_bytes,
        content_type=content_type,
        sample_rate_hz=observed_sample_rate,
        duration_seconds=duration_seconds,
        provider=provider,
        char_count=len(text),
    )


def _provider_native_content_type(provider: str) -> str:
    """Return the HTTP Content-Type ``synthesize()`` emits for this provider.

    Every provider in NV's catalog streams raw PCM via TTSAudioRawFrame (see the
    module note above), so this always resolves to WAV. The function only guards
    against a provider outside the catalog; the Pydantic discriminator on
    TTSConfig already rejects those, so reaching the raise means the catalog grew
    without this list being updated.

    Raises:
        TTSOneShotError: if ``provider`` isn't in NV's TTS catalog.
    """
    known_pcm_providers = {
        ServiceProviders.ELEVENLABS.value,
        ServiceProviders.OPENAI.value,
        ServiceProviders.CARTESIA.value,
        ServiceProviders.DEEPGRAM.value,
        ServiceProviders.SARVAM.value,
        ServiceProviders.RIME.value,
        ServiceProviders.DOGRAH.value,
        ServiceProviders.SPEACHES.value,
        ServiceProviders.CAMB.value,
    }
    if provider not in known_pcm_providers:
        raise TTSOneShotError(
            f"Unknown TTS provider {provider!r} — extend _provider_native_content_type."
        )
    return "audio/wav"


def _wrap_pcm_as_wav(pcm_bytes: bytes, sample_rate_hz: int) -> bytes:
    """Prepend a 44-byte WAV header (PCM 16-bit mono) to a raw PCM buffer.

    Used by providers that emit raw PCM. ElevenLabs + OpenAI are
    pass-through MP3.

    Bit depth (16) and channels (1) are hard-coded; if a provider ever
    returns different shapes ``synthesize()`` raises rather than emitting
    silently-wrong audio.
    """
    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate_hz * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_bytes)
    # RIFF chunk size = 36 + data_size (total file size - 8 for "RIFF" + size field)
    riff_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",            # ChunkID
        riff_size,          # ChunkSize
        b"WAVE",            # Format
        b"fmt ",            # Subchunk1ID
        16,                 # Subchunk1Size (PCM)
        1,                  # AudioFormat (PCM = 1)
        num_channels,       # NumChannels
        sample_rate_hz,     # SampleRate
        byte_rate,          # ByteRate
        block_align,        # BlockAlign
        bits_per_sample,    # BitsPerSample
        b"data",            # Subchunk2ID
        data_size,          # Subchunk2Size
    )
    return header + pcm_bytes
