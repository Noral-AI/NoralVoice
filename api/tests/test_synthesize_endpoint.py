"""Tests for POST /embed/synthesize.

Phase 6 — WIP skeleton. The route currently returns ``501 Not
Implemented`` and the helpers
(``api.services.pipecat.tts_one_shot.synthesize`` and
``api.services.audio.synth_storage.upload_synth_audio``) raise
``NotImplementedError``.

This test file ships with:
  - **One PASSING test** that asserts the skeleton route returns 501.
    Locks the contract until the real implementation arrives.
  - **Pydantic model validation tests** that assert the request body
    schema rejects out-of-range / partial inputs. These work today and
    catch regressions in the schema layer.
  - **Three SKIPPED tests** marked ``@pytest.mark.skip`` that document
    the smoke surface for the eventual implementation. Each carries
    the reason ``"WIP — implementation pending"``; unskip when the
    real handler lands.

See ``docs/design/phase-6-nv-tts-synthesize.md`` §8 for the full
testing strategy.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Pydantic schema tests (work TODAY — locks the request shape).
# ---------------------------------------------------------------------------


def test_synthesize_request_accepts_minimal_body():
    """Token + text + no override = valid."""
    from api.routes.embed import SynthesizeRequest

    body = SynthesizeRequest(token="emb_test", text="Hello.")
    assert body.token == "emb_test"
    assert body.text == "Hello."
    assert body.voice_override is None


def test_synthesize_request_accepts_full_voice_override():
    """All three override fields present = valid."""
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
    """Missing model in voice_override → 422 from Pydantic."""
    from api.routes.embed import SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(
            token="emb_test",
            text="Hello.",
            voice_override={"provider": "elevenlabs", "voice_id": "rachel"},
        )


def test_synthesize_request_rejects_text_too_long():
    """Text > SYNTHESIZE_TEXT_MAX_CHARS → 422."""
    from api.routes.embed import SYNTHESIZE_TEXT_MAX_CHARS, SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(
            token="emb_test",
            text="a" * (SYNTHESIZE_TEXT_MAX_CHARS + 1),
        )


def test_synthesize_request_rejects_empty_text():
    """Empty text → 422."""
    from api.routes.embed import SynthesizeRequest

    with pytest.raises(ValidationError):
        SynthesizeRequest(token="emb_test", text="")


# ---------------------------------------------------------------------------
# Route-level test (passes today, asserts the skeleton contract).
# ---------------------------------------------------------------------------


def test_synthesize_route_returns_501_in_skeleton_state(client: TestClient):
    """Locks the WIP contract until the real implementation arrives.

    When the real handler lands, this test should fail (good — it
    means the handler is no longer a stub). Update or remove this test
    at that point in favor of the happy/error-path tests below (which
    are currently skipped).
    """
    resp = client.post(
        "/api/v1/embed/synthesize",
        json={"token": "emb_test", "text": "Hello."},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert "WIP" in body["detail"] or "wip" in body["detail"].lower()


# ---------------------------------------------------------------------------
# Skipped — to be unskipped + filled in when the real handler lands.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="WIP — implementation pending; see design doc §8")
def test_synthesize_happy_path_returns_audio_url():
    """End-to-end with mocked Pipecat service + mocked storage.

    Plan:
      1. Patch ``tts_one_shot.synthesize`` to return a fake
         :class:`SynthesisResult` with known bytes.
      2. Patch ``synth_storage.upload_synth_audio`` to return a known URL.
      3. POST with a valid (mocked) token.
      4. Assert response shape matches :class:`SynthesizeResponse`,
         ``audio_url`` is what the mock returned, ``provider`` matches
         the user_config TTS provider.
    """


@pytest.mark.skip(reason="WIP — implementation pending; see design doc §8")
def test_synthesize_rejects_invalid_token():
    """401 ``invalid_embed_token`` when the token doesn't resolve.

    Plan:
      1. Patch ``db_client.get_embed_token_by_token`` to return None.
      2. POST with any token string.
      3. Assert 401 + ``code: invalid_embed_token``.
    """


@pytest.mark.skip(reason="WIP — implementation pending; see design doc §8")
def test_synthesize_rejects_unallowed_origin():
    """403 ``origin_not_allowed`` when Origin header isn't in token's allowlist.

    Plan:
      1. Patch ``db_client.get_embed_token_by_token`` to return a token
         with ``allowed_domains=["https://allowed.example.com"]``.
      2. POST with ``Origin: https://evil.example.com``.
      3. Assert 403 + ``code: origin_not_allowed``.
    """
