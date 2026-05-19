# Phase 6 — NoralVoice TTS synth endpoint (design)

**Status:** Design + skeleton. NOT yet implemented end-to-end.
**Target PR:** `feat/phase-6-nv-tts-synthesize` against `rebrand/noralvoice`
**Pairs with:** Phase 6 PR-A on NoralOS (`feat/phase-6a-conf-room-nv-tts`), which depends on this endpoint being deployed first.

---

## 1. Goal

Expose a public, embed-token-authenticated HTTP endpoint that takes text + voice settings, runs it through NoralVoice's existing 9-provider TTS catalog (the Pipecat services in `api/services/pipecat/service_factory.py`), uploads the resulting audio to S3/MinIO, and returns a pre-signed URL the browser can play.

This is the missing piece in Phase 6's plan: NoralOS Conference Room sessions need a way to get NV TTS audio for agent replies without spinning up a full workflow_run. Today, voice-cascade does this with a private 2-provider TTS layer; Phase 6 retires that and routes through NV.

## 2. Non-goals

- **Not a streaming endpoint.** This is text → audio file, one-shot. Streaming TTS happens inside live workflow_runs via Pipecat pipelines, which is the existing path and remains untouched.
- **Not a TTS-as-a-service offering.** This endpoint is for embed-authenticated callers (NoralOS Conference Room, future embed widgets). It is NOT intended as a generic public TTS API.
- **Not authenticated by API key.** The existing `/api/v1/integration-webhooks` etc. are API-key-authed. This endpoint reuses the embed-token model (same as `/api/v1/public/embed/init`) so the NoralOS plugin can call it with the same lifecycle a Conference Room session uses.

## 3. Endpoint contract

### Route
`POST /api/v1/public/embed/synthesize`

### Request body
```json
{
  "token": "embed_token_<random>",
  "text": "Hello world",
  "voice_override": {
    "provider": "elevenlabs",
    "voice_id": "rachel",
    "model": "eleven_turbo_v2_5"
  }
}
```

- `token` (required) — an embed_token previously minted via `POST /api/v1/embed/exchange-token` or the operator dashboard. Validated against `embed_tokens.is_active`, `embed_tokens.expires_at`, and `embed_tokens.allowed_domains` (against the request's `Origin` header).
- `text` (required, 1 ≤ len ≤ 4000) — text to synthesize. Hard upper bound matches voice-cascade's `SPOKEN_RESPONSE_CAP_CHARS`.
- `voice_override` (optional) — if absent, uses the token's owning user's `user_configurations.tts` settings. If present, must specify all three fields (provider + voice_id + model); partial overrides are rejected with 422.

### Response (2xx)
```json
{
  "audio_url": "https://voice-audio.s3.us-east-1.amazonaws.com/audio/synthesized/<token>/<uuid>.wav?X-Amz-Signature=...",
  "expires_at": "2026-05-15T23:35:00Z",
  "content_type": "audio/wav",
  "duration_seconds": 1.42,
  "char_count": 11,
  "provider": "elevenlabs"
}
```

Pre-signed URL TTL: **5 minutes**. Audio file TTL in S3: **24 hours** (after which a janitor job deletes — see §7).

### Errors
| Status | Code | Meaning |
|---|---|---|
| 401 | `invalid_embed_token` | Token not found, inactive, or expired |
| 403 | `origin_not_allowed` | Request origin not in token's allowed_domains |
| 422 | `invalid_voice_override` | Partial override; provider/voice_id/model not all present |
| 422 | `text_too_long` | `len(text)` > 4000 |
| 429 | `rate_limited` | Per-token rate limit (see §6) |
| 500 | `synthesis_failed` | Provider error after retries |
| 502 | `storage_failed` | S3/MinIO upload failed |

## 4. Architecture flow

```
┌──── Caller ────┐
│ NoralOS plugin │   POST /public/embed/synthesize  {token, text, voice_override?}
│ (or embed widget)
└────────┬───────┘
         │ HTTPS
         ▼
┌──────────────── NoralVoice (api/routes/embed.py) ────────────────┐
│                                                                  │
│  1. Validate embed_token (existing helper)                       │
│     ├─ Look up by token hash                                     │
│     ├─ Check is_active, expires_at                               │
│     └─ Domain check vs Origin header                             │
│                                                                  │
│  2. Resolve user → user_configurations.tts                       │
│     └─ If voice_override supplied, overlay onto stored config    │
│                                                                  │
│  3. Pre-flight checks                                            │
│     ├─ text length validation                                    │
│     ├─ rate limit check (Redis-backed token bucket)              │
│     └─ org quota check (charge per-char synth credits)           │
│                                                                  │
│  4. Synthesize (api/services/pipecat/tts_one_shot.py)            │
│     ├─ create_tts_service(user_config, audio_config)             │
│     ├─ async for frame in service.run_tts(text):                 │
│     │      collect TTSStartedFrame / TTSAudioRawFrame / TTSStopped│
│     ├─ Concatenate audio bytes                                   │
│     └─ Wrap PCM in WAV header (or pass through MP3 from provider)│
│                                                                  │
│  5. Upload to S3/MinIO (api/services/filesystem/s3.py)           │
│     ├─ Path: audio/synthesized/<token_id>/<uuid>.<ext>           │
│     └─ Returns presigned GET url with 5-min TTL                  │
│                                                                  │
│  6. Record usage (charge org quota)                              │
│     └─ INSERT INTO synth_usage (token_id, char_count, provider)  │
│                                                                  │
│  7. Return JSON                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 5. Per-provider audio format quirks

This is where the "9-provider" promise is genuinely complex. Each Pipecat service emits audio in its own format:

| Provider | Native output | Container needed | Notes |
|---|---|---|---|
| ElevenLabs | MP3 (configurable) | None | Pass through as audio/mpeg |
| Cartesia | Raw PCM | WAV header wrap | 16kHz typical |
| Deepgram | Raw PCM | WAV header wrap | 16kHz |
| OpenAI | MP3 | None | Pass through |
| Sarvam | Raw PCM | WAV header wrap | 22050Hz |
| Rime | Raw PCM | WAV header wrap | 22050Hz |
| Dograh | Raw PCM | WAV header wrap | (Phase-B3 rename pending) |
| Speaches | Raw PCM | WAV header wrap | 16kHz |
| Camb | Raw PCM | WAV header wrap | 16kHz |

Implementation strategy: a `normalize_audio()` helper inspects the first frame's metadata, decides WAV-wrap vs pass-through, and returns `(bytes, content_type, extension)`.

## 6. Rate limiting + quota

**Rate limiting** (per-token, per-org):
- Token bucket: 30 requests / minute / token, burst 10.
- Backed by Redis (existing `WorkerSyncManager` Redis client).
- Returns 429 with `Retry-After` header on overflow.

**Org quota** (per-synth-character):
- Each synth call charges `len(text)` "synth credits" to the token's owning org.
- Org's `quota_*` fields gain a `quota_synth_credits` column (separate Alembic migration; might wait for Phase B3's column-rename PR).
- Below-quota: serve; over-quota: 402 Payment Required (or 429 with quota-exceeded reason).

For the **first cut (skeleton)**, both rate limit and quota integration are stubbed — the route accepts requests but doesn't enforce limits. These come in follow-up PRs after the basic synth path is proven.

## 7. Storage layout

- Bucket: `MINIO_BUCKET` env (dev) or `S3_BUCKET` env (prod). Same bucket as recordings.
- Path: `audio/synthesized/<token_id>/<uuid>.<ext>` where `token_id` is the integer PK of the embed_token (NOT the secret).
- Pre-signed URL TTL: 5 minutes.
- File TTL: 24 hours. A lifecycle policy on the bucket auto-deletes objects under `audio/synthesized/` after 24h. (Configured via Terraform / one-time `aws s3api put-bucket-lifecycle-configuration` — out of scope for this PR; documented for ops.)

## 8. Testing strategy

### Skeleton PR ships with:
- Pydantic model unit tests (request/response shape, validation rules).
- A mock-based unit test for `tts_one_shot.synthesize()` — passes a fake Pipecat service that yields preset frames, asserts the right audio bytes come back.
- Route-level test with mocked `synthesize_text()` — asserts 401 on bad token, 422 on bad input, happy path returns expected response shape.

### Deferred to a follow-up PR:
- Per-provider integration tests (need real provider API keys; gated by `pytest.mark.skipif(env unset)`).
- E2E test against MinIO local container.
- Latency / load test (single synth call should complete in < 2s for text ≤ 200 chars).

## 9. Open questions

1. **Audio format choice for ElevenLabs/OpenAI**: pass through MP3 vs convert to WAV for uniform browser playback. Recommendation: pass through native format and let the browser handle (browsers handle both well). Sets `Content-Type` accordingly.

2. **Voice override authority**: should embed_token holders be allowed to override the voice settings stored against the token's owning user? Recommendation: yes, but log it for audit. Alternative: restrict overrides to a whitelist baked into the token.

3. **Caching**: same `(text, voice_settings)` tuple → identical audio. Worth caching? Recommendation: not in this PR — caching is a perf optimization, and there's no clear hit rate yet. Add later when metrics show the same string being synthesized repeatedly.

4. **Provider failover**: voice-cascade had ElevenLabs → Google serial fallback. Should this endpoint? Recommendation: NO. Provider selection is the caller's choice via `voice_override`; if it fails, the caller decides what to do. Keeps the endpoint stateless + predictable.

## 10. Out of scope / followups

- Bucket lifecycle policy for auto-deletion (ops one-shot).
- Real per-provider integration tests with API keys.
- Org-quota Alembic migration (`quota_synth_credits` column).
- Redis rate-limiter implementation (skeleton has stub).
- Caching layer (see open Q 3).
- The NoralOS plugin side that CALLS this endpoint (PR-A on NoralOS — separate session).

## 11. File-level plan

| File | New / Modified | Purpose |
|---|---|---|
| `docs/design/phase-6-nv-tts-synthesize.md` | NEW | This document |
| `api/services/pipecat/tts_one_shot.py` | NEW | One-shot wrapper around Pipecat TTSService |
| `api/services/audio/synth_storage.py` | NEW | MinIO/S3 upload + presigned URL for synth outputs |
| `api/routes/embed.py` | MODIFIED | Add `POST /synthesize` route + Pydantic models |
| `api/schemas/synth.py` | NEW (alternative) | If route models grow, move to a dedicated schema module |
| `api/tests/test_synthesize_endpoint.py` | NEW | Mocked unit tests for the route |
| `api/tests/test_tts_one_shot.py` | NEW | Mocked unit tests for the synth helper |

## 12. Risks

- **Pipecat services may not behave well outside a pipeline.** The framework expects pipelines and may have internal state assumptions. Mitigation: skeleton's mocked tests prove the run_tts iterator pattern; real-provider testing in follow-up.
- **Audio format normalization across 9 providers is real work.** ~80-150 LOC. Mitigated by per-provider table in §5.
- **No org-quota enforcement in the first cut.** This is fine for the Conference Room caller (NoralOS plugin) which is single-tenant per company, but is a security risk if the endpoint ever becomes more public. Document clearly; gate behind a feature flag.

---

**Next step:** review this design, then execute the skeleton implementation. The skeleton ships scaffolded code that compiles + has mocked tests passing, but raises `NotImplementedError` for the real synth/upload paths. A follow-up PR fills in the implementation against the documented design.
