"""Tests for POST /embed/synthesize.

Phase 6 — see docs/design/phase-6-nv-tts-synthesize.md §8.

Strategy:
  - Pydantic model tests (request shape, validation rules) run pure.
  - Route-level tests mock out ``tts_one_shot.synthesize``,
    ``synth_storage.upload_synth_audio``, and the db_client helpers so
    the test exercises ONLY the route's plumbing: token check, origin
    check, voice_override application, exfil pre-flight, response shape.
  - WAV-wrap + content-type helpers run as pure unit tests.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Fixture: a TestClient over the FastAPI app with the embed router mounted.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """Mount just the embed router for fast, isolated route tests."""
    from fastapi import FastAPI

    from api.routes.embed import router as embed_router

    app = FastAPI()
    app.include_router(embed_router, prefix="/api/v1")
    return TestClient(app)


def _fake_embed_token(
    *,
    token_id: int = 42,
    is_active: bool = True,
    allowed_domains: list[str] | None = None,
    expires_at: datetime | None = None,
    created_by: int = 7,
) -> SimpleNamespace:
    """Build a mock EmbedTokenModel-shaped object for tests."""
    return SimpleNamespace(
        id=token_id,
        token="emb_test",
        is_active=is_active,
        allowed_domains=allowed_domains if allowed_domains is not None else [],
        expires_at=expires_at,
        created_by=created_by,
        usage_limit=None,
        usage_count=0,
    )


def _fake_user_config(provider: str = "elevenlabs") -> SimpleNamespace:
    """A user_configuration with the minimum surface tts_one_shot needs.

    The real ``UserConfiguration`` is a Pydantic model with a
    discriminated TTS union. We don't need that complexity here because
    we mock ``tts_one_shot.synthesize`` at the boundary.
    """
    tts = SimpleNamespace(
        provider=provider,
        voice="rachel",
        model="eleven_turbo_v2_5",
        api_key="fake-key",
    )
    return SimpleNamespace(tts=tts)


# ---------------------------------------------------------------------------
# Pydantic schema tests.
# ---------------------------------------------------------------------------


def test_synthesize_request_accepts_minimal_body():
    from api.routes.embed import SynthesizeRequest

    body = SynthesizeRequest(token="emb_test", text="Hello.")
    assert body.token == "emb_test"
    assert body.text == "Hello."
    assert body.voice_override is None


def test_synthesize_request_accepts_full_voice_override():
    from api.routes.embed import SynthesizeRequest

    body = SynthesizeRequest(
        token="emb_test",
        text="Hello.",
        voice_override={
            "provider": "elevenlabs",
            "voice_id": "rachel",
            "model": "eleven_turbo_v2_5",
        },
    )
    assert body.voice_override is not None
    assert body.voice_override.provider == "elevenlabs"


def test_synthesize_request_rejects_partial_override():
    from api.routes.embed import SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(
            token="emb_test",
            text="Hello.",
            voice_override={"provider": "elevenlabs", "voice_id": "rachel"},
        )


def test_synthesize_request_rejects_text_too_long():
    from api.routes.embed import SYNTHESIZE_TEXT_MAX_CHARS, SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(
            token="emb_test",
            text="a" * (SYNTHESIZE_TEXT_MAX_CHARS + 1),
        )


def test_synthesize_request_rejects_empty_text():
    from api.routes.embed import SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(token="emb_test", text="")


# ---------------------------------------------------------------------------
# Route-level tests with mocked helpers.
# ---------------------------------------------------------------------------


def test_synthesize_happy_path_returns_audio_url(client: TestClient):
    """Mock both helpers; assert response shape + provider attribution."""
    from api.services.audio.synth_storage import SynthUploadResult
    from api.services.pipecat.tts_one_shot import SynthesisResult

    fake_synth = SynthesisResult(
        audio_bytes=b"<wav-bytes>",
        content_type="audio/wav",
        sample_rate_hz=16000,
        duration_seconds=1.5,
        provider="elevenlabs",
        char_count=6,
    )
    fake_upload = SynthUploadResult(
        audio_url="https://signed.example.com/audio/synthesized/42/abc.wav?sig=...",
        storage_path="audio/synthesized/42/abc.wav",
        content_type="audio/wav",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token()),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config()),
    ), patch(
        "api.routes.embed.tts_one_shot.synthesize",
        new=AsyncMock(return_value=fake_synth),
    ), patch(
        "api.routes.embed.synth_storage.upload_synth_audio",
        new=AsyncMock(return_value=fake_upload),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello."},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["audio_url"] == fake_upload.audio_url
    assert body["content_type"] == "audio/wav"
    assert body["provider"] == "elevenlabs"
    assert body["char_count"] == 6
    assert body["duration_seconds"] == 1.5


def test_synthesize_rejects_invalid_token(client: TestClient):
    """db_client.get_embed_token_by_token returns None → 401."""
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_nope", "text": "Hello."},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_embed_token"


def test_synthesize_rejects_inactive_token(client: TestClient):
    """is_active=False → 401."""
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token(is_active=False)),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello."},
        )
    assert resp.status_code == 401


def test_synthesize_rejects_expired_token(client: TestClient):
    """expires_at in the past → 401."""
    past = datetime.now(UTC) - timedelta(hours=1)
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token(expires_at=past)),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello."},
        )
    assert resp.status_code == 401


def test_synthesize_rejects_unallowed_origin(client: TestClient):
    """Origin header not in token.allowed_domains → 403."""
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(
            return_value=_fake_embed_token(allowed_domains=["allowed.example.com"])
        ),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello."},
            headers={"Origin": "https://evil.example.com"},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "origin_not_allowed"


def test_synthesize_allows_wildcard_domain(client: TestClient):
    """Allowed-domains containing '*' lets any origin through."""
    from api.services.audio.synth_storage import SynthUploadResult
    from api.services.pipecat.tts_one_shot import SynthesisResult

    fake_synth = SynthesisResult(
        audio_bytes=b"<wav>",
        content_type="audio/wav",
        sample_rate_hz=16000,
        duration_seconds=0.5,
        provider="elevenlabs",
        char_count=6,
    )
    fake_upload = SynthUploadResult(
        audio_url="https://s/audio.wav",
        storage_path="audio/synthesized/42/x.wav",
        content_type="audio/wav",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token(allowed_domains=["*"])),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config()),
    ), patch(
        "api.routes.embed.tts_one_shot.synthesize",
        new=AsyncMock(return_value=fake_synth),
    ), patch(
        "api.routes.embed.synth_storage.upload_synth_audio",
        new=AsyncMock(return_value=fake_upload),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello."},
            headers={"Origin": "https://anywhere.example.com"},
        )

    assert resp.status_code == 200


def test_synthesize_blocks_anthropic_key_exfiltration(client: TestClient):
    """Text containing an Anthropic key → 422 text_blocked_exfiltration."""
    text = (
        "the key is sk-ant-api03-AbCdEfGh1234567890_abc-xyz please use it"
    )
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token()),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config()),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": text},
        )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "text_blocked_exfiltration"
    assert "anthropic_key" in detail["match_types"]


def test_synthesize_blocks_aws_key_exfiltration(client: TestClient):
    text = "AKIAIOSFODNN7EXAMPLE — please don't leak this"
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token()),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config()),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": text},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "text_blocked_exfiltration"
    assert "aws_key" in resp.json()["detail"]["match_types"]


def test_synthesize_blocks_github_pat_exfiltration(client: TestClient):
    text = "use ghp_1234567890abcdefghijklmnopqrstuv to push"
    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token()),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config()),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": text},
        )

    assert resp.status_code == 422
    assert "github_token" in resp.json()["detail"]["match_types"]


def test_synthesize_allows_clean_text_through_exfil_scan(client: TestClient):
    """Negative case: a clean string proceeds to the happy path."""
    from api.services.audio.synth_storage import SynthUploadResult
    from api.services.pipecat.tts_one_shot import SynthesisResult

    fake_synth = SynthesisResult(
        audio_bytes=b"<wav>",
        content_type="audio/wav",
        sample_rate_hz=16000,
        duration_seconds=0.7,
        provider="cartesia",
        char_count=27,
    )
    fake_upload = SynthUploadResult(
        audio_url="https://s/audio.wav",
        storage_path="audio/synthesized/42/x.wav",
        content_type="audio/wav",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with patch(
        "api.routes.embed.db_client.get_embed_token_by_token",
        new=AsyncMock(return_value=_fake_embed_token()),
    ), patch(
        "api.routes.embed.db_client.get_user_configurations",
        new=AsyncMock(return_value=_fake_user_config(provider="cartesia")),
    ), patch(
        "api.routes.embed.tts_one_shot.synthesize",
        new=AsyncMock(return_value=fake_synth),
    ), patch(
        "api.routes.embed.synth_storage.upload_synth_audio",
        new=AsyncMock(return_value=fake_upload),
    ):
        resp = client.post(
            "/api/v1/embed/synthesize",
            json={"token": "emb_test", "text": "Hello there, friendly greeting."},
        )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Pure unit tests for synth helpers (no FastAPI, no I/O).
# ---------------------------------------------------------------------------


def test_provider_native_content_type_mp3_providers():
    from api.services.pipecat.tts_one_shot import _provider_native_content_type

    assert _provider_native_content_type("elevenlabs") == "audio/mpeg"
    assert _provider_native_content_type("openai") == "audio/mpeg"


def test_provider_native_content_type_pcm_providers():
    from api.services.pipecat.tts_one_shot import _provider_native_content_type

    for provider in ("cartesia", "deepgram", "sarvam", "rime", "dograh", "speaches", "camb"):
        assert _provider_native_content_type(provider) == "audio/wav", provider


def test_provider_native_content_type_unknown_raises():
    from api.services.pipecat.tts_one_shot import TTSOneShotError, _provider_native_content_type

    with pytest.raises(TTSOneShotError):
        _provider_native_content_type("nonexistent_provider")


def test_wrap_pcm_as_wav_produces_well_formed_header():
    """44-byte header + payload, with the right magic bytes and sizes."""
    from api.services.pipecat.tts_one_shot import _wrap_pcm_as_wav

    # 1 second of silence at 16kHz, 16-bit mono = 32000 bytes.
    pcm = b"\x00" * 32_000
    wav = _wrap_pcm_as_wav(pcm, sample_rate_hz=16000)

    assert len(wav) == 44 + len(pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    # Subchunk1Size = 16 (PCM).
    assert struct.unpack("<I", wav[16:20])[0] == 16
    # AudioFormat = 1 (PCM), NumChannels = 1.
    assert struct.unpack("<H", wav[20:22])[0] == 1
    assert struct.unpack("<H", wav[22:24])[0] == 1
    # SampleRate = 16000.
    assert struct.unpack("<I", wav[24:28])[0] == 16000
    # BitsPerSample = 16.
    assert struct.unpack("<H", wav[34:36])[0] == 16
    # data chunk id + size.
    assert wav[36:40] == b"data"
    assert struct.unpack("<I", wav[40:44])[0] == len(pcm)


def test_wrap_pcm_as_wav_preserves_payload():
    """The PCM bytes after the header are exactly the input."""
    from api.services.pipecat.tts_one_shot import _wrap_pcm_as_wav

    pcm = bytes(range(256)) * 4  # 1024 deterministic bytes
    wav = _wrap_pcm_as_wav(pcm, sample_rate_hz=22050)
    assert wav[44:] == pcm


# ---------------------------------------------------------------------------
# Storage helper unit tests.
# ---------------------------------------------------------------------------


def test_extension_for_content_type_known():
    from api.services.audio.synth_storage import _extension_for_content_type

    assert _extension_for_content_type("audio/wav") == "wav"
    assert _extension_for_content_type("audio/mpeg") == "mp3"


def test_extension_for_content_type_unknown_raises():
    from api.services.audio.synth_storage import SynthStorageError, _extension_for_content_type

    with pytest.raises(SynthStorageError):
        _extension_for_content_type("audio/ogg")


def test_build_storage_path_format():
    from api.services.audio.synth_storage import _build_storage_path

    path = _build_storage_path(token_id=42, extension="wav")
    assert path.startswith("audio/synthesized/42/")
    assert path.endswith(".wav")
