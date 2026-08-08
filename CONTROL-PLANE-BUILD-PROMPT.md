# NoralVoice → ElevenLabs Control Plane — Claude Code Build Prompt

**Run this tier by tier. Verify each phase before moving to the next. Do NOT batch phases — each has a different risk profile and Phase 1 is destructive.**

---

## Mission

Transform this repository from a **self-hosted Pipecat/Dograh voice engine** into a **thin multi-tenant control plane over ElevenLabs Agents**.

We manage voice agents *for clients*. We do NOT want to run a real-time voice pipeline ever again — it was unreliable, confusing, and calls failed. ElevenLabs Agents is now a full managed platform (agent CRUD, telephony, KB/RAG, tools, testing, versioning, conversations API). We rent that engine via its API and build only the layer that is genuinely ours:

- A branded UI to **create, edit, and publish** each client's agents.
- **Reporting, call recordings, and transcripts** ingested into our own database.
- **Per-client isolation** and usage/billing rollups.

This is the opposite of what this repo currently does. Treat the existing code as a **shell to salvage**, not a system to preserve.

## Prime directive (read before writing any code)

1. **Rent the engine. Never rebuild it.** All real-time voice — STT, LLM, TTS, turn-taking, telephony media, WebRTC, TURN — belongs to ElevenLabs. If you ever find yourself re-adding a media server, streaming audio, or turn-detection logic, STOP: you are rebuilding the thing we are deleting.
2. **Keep the control plane thin.** It is CRUD + API proxying + webhook ingestion + dashboards + auth. Nothing more.
3. **The escape valve is BYO-LLM.** If a client ever needs behavior ElevenLabs can't express, use ElevenLabs' custom-LLM / bring-your-own-LLM hook — do NOT bring the media stack back in-house.
4. **This fork diverges permanently from upstream Dograh.** Prior rebrand notes tried to preserve upstream sync — that goal is superseded for anything in the voice-engine path. Deleting the engine is expected and correct.

## Operating rules for you (Claude Code)

- **Phase 0 is recon only — no code changes.** Confirm every assumption in this document against the actual repo before deleting anything. This prompt was written from a partial snapshot; the repo is ground truth.
- Work **one phase at a time**. After each phase: run the app, run tests, and produce a short written summary of what changed and what you verified. Wait for my go-ahead before the next phase.
- **Commit per phase** on a dedicated branch (e.g. `feat/control-plane-phase-N`). Never force-push. Never touch other branches or worktrees.
- **Ask before any destructive or irreversible action** beyond what a phase explicitly authorizes (dropping DB tables, deleting directories, removing services).
- Write or update **tests** for every new backend capability. A phase is not "done" until its acceptance criteria pass.
- Prefer **editing the existing shell** (auth, org models, UI scaffolding, reporting) over greenfield rewrites. Reuse what already works.
- Keep secrets out of code and git. Provider keys live in env / a secrets store, never in the repo.

## Decisions to confirm with me at Phase 0

- **Tenancy model:** start MVP as **single ElevenLabs workspace, agents tagged per client**, but design the data model for the target state of **one workspace per client under Consolidated Billing (Enterprise)**. Confirm which we're building first.
- **Client access:** do clients log into the platform directly, or is editing Noral-internal only for now? (Default: Noral-internal only; client-facing read dashboards later.)
- **Recording storage:** store our own copy of call audio in MinIO (already in the stack) vs. keep ElevenLabs signed URLs. (Default: download + store in MinIO for retention control.)

---

## Target architecture

```
        ┌──────────────────────── NoralVoice Control Plane (this repo) ─────────────────────────┐
        │                                                                                        │
Noral   │   Next.js UI ──────────────►  FastAPI backend  ──────────►  Postgres (our data)        │
staff   │   • client switcher            • ElevenLabs API client       • clients / tenants        │
        │   • agent editor               • webhook ingestion           • agent↔workspace map      │
        │   • dashboards / player        • usage + billing rollups     • conversations (metadata) │
        │                                • auth / RBAC                  • transcripts             │
        │                                        │                     MinIO (call recordings)    │
        └────────────────────────────────────────┼───────────────────────────────────────────────┘
                                                  │ REST API  +  post-call webhooks
                                                  ▼
                        ┌──────────────── ElevenLabs Agents (rented engine) ────────────────┐
                        │  agents · KB/RAG · tools · native Twilio (in/out) · batch calls    │
                        │  turn-taking · conversation recordings/transcripts · analysis      │
                        └────────────────────────────────────────────────────────────────────┘
```

### Data model (our Postgres — adapt existing org/models where possible)

- `client` (tenant): id, name, status, `elevenlabs_workspace_id`, billing plan, created_at. **Reuse/rename the existing organization model if it fits.**
- `client_api_credential`: client_id → encrypted ElevenLabs API key (per-workspace), Twilio SID/token if client-owned. Store encrypted; never log.
- `managed_agent`: id, client_id, `elevenlabs_agent_id`, name, use_case, current_version, status. Mirror of the ElevenLabs agent for listing/search; source of truth for config stays in ElevenLabs.
- `phone_number`: id, client_id, e164, `elevenlabs_phone_number_id`, provider, direction (inbound/outbound).
- `conversation`: id, client_id, agent_id, `elevenlabs_conversation_id`, started_at, duration_seconds, direction, outcome, sentiment, cost_estimate, `recording_object_key` (MinIO), created_at.
- `conversation_transcript`: conversation_id → full transcript JSON (turns, roles, tool calls, RAG attribution).
- `extracted_data`: conversation_id → key/value fields defined per agent (data-collection results).
- `usage_rollup`: client_id, period, minutes, calls, cost. Feeds billing/margin reporting.

### Integration layer (`api/services/elevenlabs/`)

A single typed client wrapping the ElevenLabs REST API. Cover, at minimum:

- **Agents:** create / get / list / update / duplicate; drafts + branches + deployments for a safe **edit → draft → publish** flow.
- **Knowledge base:** create-from-file/url/text, list, delete, compute RAG index.
- **Tools:** webhook tools, client tools, MCP tools; system tools (transfer-to-number for human handoff, voicemail detection, end-call).
- **Phone numbers:** import Twilio number, list, assign to agent; outbound call; **batch calling** (submit/list/get/export/cancel).
- **Conversations:** list, get details (transcript), get audio, get signed URL; conversation analysis (sentiment, success eval, data collection).
- **Workspace:** secrets, environment variables (for per-client config), dashboard settings.

### Webhook ingestion (`api/routes/elevenlabs_webhooks.py`)

- Endpoint that receives ElevenLabs **post-call webhooks**, verifies signature, resolves the client from the agent/workspace, and writes: `conversation` row, `conversation_transcript`, `extracted_data`, updates `usage_rollup`.
- If recording storage = MinIO: fetch the call audio via the conversation audio / signed-URL endpoint and store it under a per-client key; save `recording_object_key`.
- Idempotent on `elevenlabs_conversation_id`.

### UI (Next.js — reuse existing shell)

- **Client switcher** (tenant scope on everything).
- **Agent editor:** system prompt, voice, language, tools, knowledge base, conversation-flow settings; **Save as draft → Publish** using ElevenLabs branches/deployments.
- **Calls dashboard:** table of conversations per client with an inline **audio player**, transcript view, sentiment, extracted fields, duration.
- **Usage/billing view:** minutes, calls, and cost per client per period.

---

## Multi-tenancy

- **Target (recommended for real client work):** one ElevenLabs **workspace per client**, all linked under **Consolidated Billing (Enterprise)** → single invoice, per-workspace usage caps, clean isolation of agents, phone numbers, secrets, and conversation data. Our `client.elevenlabs_workspace_id` + per-client API credential drive this.
- **MVP (if not on Enterprise yet):** single workspace, agents named/tagged per client, and the control plane enforces the client boundary on every read/write. Acceptable for a few low-sensitivity clients; migrate to workspace-per-client before scaling or onboarding any regulated client.
- Enforce tenant scoping in **every** query and every ElevenLabs API call. No endpoint returns cross-client data.

---

## Phased execution plan

### Phase 0 — Recon (no code changes)
- Map the repo: confirm which directories are the voice engine (candidates to remove) vs. the reusable shell.
  - **Likely REMOVE (voice engine):** `pipecat/`, `api/services/pipecat`, `api/services/audio`, `api/services/smart_turn`, `coturn` service, `api/routes/webrtc_signaling.py`, `api/routes/agent_stream.py`, `api/routes/turn_credentials.py`, `api/services/looptalk`, `native/rnnoise`, `dograh_pcm_cache`.
  - **Likely KEEP (shell):** `ui/` (Next.js), `api/` FastAPI app + `api/db` clients, auth (`api/routes/auth*`, `api/services/auth`), organization/org models (→ `client`), `api/db/reports_client.py` + `api/routes/reports.py`, `api/routes/knowledge_base.py` (re-point to ElevenLabs KB), `api/routes/integration_webhooks.py`, n8n wiring (optional post-call automation), docker services `postgres`/`redis`/`minio`/`nginx`.
- Produce a written **keep / cut / re-point** table and the tenancy + storage decisions above. **Stop and confirm with me.**
- **Acceptance:** accurate inventory; no files changed.

### Phase 1 — Remove the engine (destructive)
- Delete the voice-engine directories/services confirmed in Phase 0. Remove `coturn` and WebRTC/turn/streaming routes and the Pipecat services. Update `docker-compose` to drop engine-only services.
- App must still boot (UI + API + Postgres + MinIO) with the engine gone. Expect and fix broken imports.
- **Acceptance:** `docker compose up` runs; UI loads; API health check passes; no references to Pipecat/coturn remain; test suite green (minus deleted-feature tests, which you remove).

### Phase 2 — ElevenLabs integration + tenancy model
- Build `api/services/elevenlabs/` client (agents, KB, tools, phone numbers, conversations, workspace).
- Add/repurpose data model: `client`, `client_api_credential` (encrypted), `managed_agent`, `phone_number`. Alembic migration.
- Secure secrets storage for per-client API keys.
- **Acceptance:** can list a client's agents from a real ElevenLabs workspace through our API; credentials encrypted at rest; unit tests with a mocked ElevenLabs client.

### Phase 3 — Agent management UI
- UI: client switcher + agent list + agent editor (prompt, voice, tools, KB, flow settings) with **draft → publish** via ElevenLabs branches/deployments.
- **Acceptance:** create an agent, edit its prompt, publish, and confirm the change is live in ElevenLabs; all scoped to the selected client.

### Phase 4 — Conversation ingestion (reporting/recordings/transcripts)
- Post-call webhook endpoint (signature-verified, idempotent) → `conversation`, `conversation_transcript`, `extracted_data`, `usage_rollup`.
- Recording handling per the storage decision (MinIO download or stored signed URL).
- **Acceptance:** place a real test call; within seconds the call appears in our DB with transcript, recording playable in the UI, sentiment + duration captured, correctly attributed to the client.

### Phase 5 — Dashboards + usage/billing
- Calls dashboard (table + audio player + transcript + extracted fields), and usage/billing view (minutes, calls, cost per client per period).
- **Acceptance:** dashboards render real ingested data per client; numbers reconcile with ElevenLabs' own history for a sample period.

### Phase 6 — Isolation hardening + RBAC
- Enforce tenant scoping on every query/API call; add RBAC (Noral admin vs. per-client scope). If on Enterprise, wire workspace-per-client mapping.
- **Acceptance:** automated test proving no endpoint returns cross-client data; role checks enforced.

### Phase 7 — Cleanup, docs, deploy
- Remove dead code/config from the old platform, update `README`, refresh `deploy/noral` for the slimmer stack, update CI.
- **Acceptance:** clean build, green CI, deploy to `voice.noral.ai` succeeds, one end-to-end call → dashboard verified in production.

---

## Do NOT
- Do NOT reintroduce any real-time media path (Pipecat, WebRTC, coturn, audio streaming, turn detection).
- Do NOT store provider API keys or Twilio tokens in the repo, logs, or client-side code.
- Do NOT return or render data across client boundaries anywhere.
- Do NOT preserve upstream Dograh compatibility at the cost of keeping engine code.
- Do NOT expand scope into "just a small" custom voice feature — use ElevenLabs BYO-LLM instead.

## Definition of done
A Noral operator logs in, picks a client, creates/edits/publishes that client's ElevenLabs agent from our branded UI, the client's phone number takes and makes calls (handled entirely by ElevenLabs), and every call lands in our dashboard with a playable recording, full transcript, sentiment, extracted fields, and usage that rolls up into per-client billing — with zero real-time voice infrastructure running in this repo.
