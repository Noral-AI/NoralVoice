# NoralVoice → Managed-Engine Control Plane — Build Plan v2

**Supersedes** `CONTROL-PLANE-BUILD-PROMPT.md` (v1) in the repo root.
**Basis:** Phase 0 recon — [control-plane-phase-0-recon.md](./control-plane-phase-0-recon.md).
**Status:** plan approved for revision; **Phase 1 is gated on the vendor decision in §3.**

---

## 1. Mission (unchanged from v1)

Transform this repository from a self-hosted Pipecat/Dograh voice engine into a thin multi-tenant **control plane** over a managed voice-agent platform.

We manage voice agents for clients. We do not want to run a real-time voice pipeline again — it was unreliable and calls failed. We rent the engine via its API and build only the layer that is genuinely ours:

- A branded UI to create, edit, and publish each client's agents.
- Reporting, call recordings, and transcripts ingested into our own database.
- Per-client isolation and usage/billing rollups.

### Prime directive

1. **Rent the engine. Never rebuild it.** All real-time voice — STT, LLM, TTS, turn-taking, telephony media, WebRTC, TURN — belongs to the vendor. If you find yourself re-adding a media server, streaming audio, or turn-detection logic: **stop**, you are rebuilding the thing being deleted.
2. **Keep the control plane thin.** CRUD + API proxying + webhook ingestion + dashboards + auth. Nothing more.
3. **The escape valve is BYO-LLM.** If a client needs behavior the vendor can't express, use the vendor's custom-LLM hook. Never bring the media stack back in-house.
4. **This fork diverges permanently from upstream Dograh.** Prior rebrand notes tried to preserve upstream sync; that goal is superseded for anything in the voice-engine path.

---

## 2. What changed from v1, and why

| # | v1 said | v2 says | Reason |
|---|---|---|---|
| 1 | Phase 1 = delete the engine, then build the replacement | **Destructive delete moves to Phase 5**, after a real client is live on the managed engine | `voice.noral.ai` is in production taking real calls. v1 creates an outage window of unknown length with zero proof the vendor covers the workload. Strangler, not big-bang. |
| 2 | Create tables `client`, `conversation`, `usage_rollup`, … | **Extend existing tables**: `organizations`→client, `workflow_runs`→conversation, `organization_usage_cycles`→usage_rollup | ~80% of the target schema already exists with the right columns. v1 would create a parallel schema and a pointless migration. |
| 3 | Engine ≈ `pipecat/` + a handful of dirs | Engine = **106 files**, incl. 12k lines of telephony across 7 providers and ~20k lines of node-graph agent authoring | Recon §2. The graph editor has no ElevenLabs counterpart and was entirely absent from v1's scope. |
| 4 | (silent on NoralOS) | **Explicit cross-repo gate** at Phase 3 | The shipped `noralai.noralvoice` plugin (32 tools, live on `agent.noral.ai`) and both typed SDKs author workflow graphs. Deleting workflows breaks production in another repo. |
| 5 | (silent on Synthflow) | **Vendor decision is a hard gate before Phase 1** (§3) | 91 agents / 14 subaccounts already run on a managed platform of exactly this shape. |
| 6 | (silent) | **Phase 0.5: working-tree hygiene** | 13 uncommitted files, untracked features, ~12 cloud-sync conflict duplicates. Not safe to start deleting on top of that. |
| 7 | Acceptance = "app boots, tests green" | Acceptance = **a real inbound + outbound call, from a real client number, appearing in our dashboard** | Booting proves nothing about a voice product. |
| 8 | "Provider keys live in env / a secrets store" | **The API key is entered and rotated in the platform UI**, stored encrypted in the DB. Only the encryption key lives in env | Operator requirement. Keys must be manageable per client without a redeploy. |
| 9 | "Encrypted per-client credential storage" as a Phase 2 bullet | **Its own phase (1a), gating everything else** | There is no encryption in this codebase at all (§11.1). On today's storage, moving keys from env into Postgres would be a downgrade, not an upgrade. |

Everything else from v1 — mission, prime directive, tenancy model, the Do-NOT list — carries over intact.

---

## 3. Vendor decision — RESOLVED: ElevenLabs

**Decided 2026-08-08: the control plane targets ElevenLabs Agents.** Gate closed; Phase 1 is unblocked.

The integration layer is `api/services/elevenlabs/`. Consequences carried into the plan:

- **Phase 4 is a real migration**, not an import: 91 agents across 14 Synthflow subaccounts must be recreated on ElevenLabs, number by number. This is the longest phase — budget accordingly.
- **Workspace-per-client requires ElevenLabs Enterprise / Consolidated Billing.** Confirm contract status before Phase 7; until then the MVP runs on a single workspace with the control plane enforcing the client boundary (§7).
- Synthflow stays live and serving throughout Phases 1–3. It is not decommissioned until its last agent is migrated in Phase 4. It is *not* a second engine to build against — no provider abstraction (§8).

The rest of this plan says "the vendor" where the logic is vendor-shaped rather than ElevenLabs-specific; read it as ElevenLabs throughout.

---

## 4. Target architecture

```
┌──────────────── NoralVoice Control Plane (this repo) ─────────────────┐
│                                                                       │
│  Next.js UI  ─────────►  FastAPI backend  ─────────►  Postgres        │
│  • client switcher        • vendor API client         • organizations  │
│  • agent editor           • webhook ingestion           (= clients)    │
│  • calls dashboard        • usage/billing rollups     • workflows      │
│  • usage view             • auth / RBAC                 (= agents)     │
│                                    │                  • workflow_runs  │
│                                    │                    (= convos)     │
│                                    │                  MinIO (audio)    │
└────────────────────────────────────┼──────────────────────────────────┘
                                     │ REST + post-call webhooks
                                     ▼
      ┌──────────── Managed voice platform (rented engine) ────────────┐
      │  agents · KB/RAG · tools · native Twilio · batch calls          │
      │  turn-taking · recordings/transcripts · analysis · simulation   │
      └────────────────────────────────────────────────────────────────┘
```

---

## 5. Data model — extend, don't duplicate

One additive migration in Phase 1; drops deferred to Phase 5.

### Phase 1 — additive only (prod-safe, engine untouched)

| Table | Add |
|---|---|
| `organizations` | `name`, `status`, `vendor_workspace_id` |
| `external_credentials` | `provider`, `last_four`, `rotated_at`; `credential_data` becomes encrypted (§11) |
| `workflows` | `vendor_agent_id`, `vendor_current_version` |
| `telephony_phone_numbers` | `vendor_phone_number_id` |
| `workflow_runs` | `vendor_conversation_id` (**unique** — webhook idempotency key), `duration_seconds`, `sentiment`, `transcript` (JSONB) |

Already present and reused as-is: `workflow_runs.recording_url` / `transcript_url` / `storage_backend` / `usage_info` / `cost_info` / `gathered_context` (= extracted data) / `call_type` / `annotations`; `organization_usage_cycles` (= usage rollups); `organizations.quota_*` / `price_per_second_usd`.

`transcript` is JSONB rather than an object-store pointer so transcripts are searchable.

### Phase 5 — drops (after migration completes)

`workflow_definitions`, `workflow_templates`, `looptalk_test_sessions`, `looptalk_conversations`, `campaigns`, `queued_runs`, `embed_tokens`, `embed_sessions`, `embed_exchange_tokens`, `knowledge_base_chunks`, `telephony_configurations`, and the graph JSON columns on `workflows`.

---

## 6. Phases

Rules that apply to every phase: work one phase at a time; commit on `feat/control-plane-phase-N`; never force-push; never touch other branches or worktrees; ask before any destructive action a phase doesn't explicitly authorize; write tests for every new backend capability; end each phase with a written summary of what changed and what was verified, then wait for go-ahead.

---

### Phase 0 — Recon ✅ complete
Deliverable: [control-plane-phase-0-recon.md](./control-plane-phase-0-recon.md). No files changed.

---

### Phase 0.5 — Working-tree hygiene *(new)*
**Non-destructive to product code.**

- Land, shelve, or discard the 13 modified files and the untracked features (`workflow_generator.py`, `ui/src/app/integrations/`, `VoicePreviewButton.tsx`, `PromptPreview.tsx`, `IntegrationsTab.tsx`, 2 test files). Note: most of this work sits inside code slated for deletion — shelving is usually the right call.
- Delete the ~12 cloud-sync conflict duplicates (`… 2.md`, `… 2.tsx`, `ui/package 2.json`, `ui/package-lock 3.json`). **Confirm the list with me before deleting.**
- Resolve branch state: `claude/workflow-hard-delete` @ `38b9ecb` — merge or abandon.
- Move `CONTROL-PLANE-BUILD-PROMPT.md` (v1) to `docs/design/` marked superseded.

**Acceptance:** `git status` clean on a known branch; no conflict duplicates; CI green.

---

### Phase 1a — Credential management + encryption at rest *(new; blocks 1b)*
**Purely additive. Engine untouched. Prod unaffected.** Full design in §11.

The ElevenLabs key is entered and rotated **in the platform UI**, never in code and never in env. That requires encryption at rest to exist first — see the finding in §11.1, which is why this is its own phase rather than a bullet under 1b.

1. **Crypto module** (`api/services/crypto/`) — libsodium `SecretBox` envelope encryption, versioned `v1:` format, key from `CREDENTIAL_ENCRYPTION_KEY`. No new dependency: PyNaCl is already in `api/requirements.txt:21`.
2. **Transparent encrypt/decrypt** in `WebhookCredentialClient` so no callsite handles ciphertext directly.
3. **Schema**: add `provider`, `last_four`, `rotated_at` to `external_credentials`; add `ELEVENLABS` to the provider set. Chains off alembic head `e4a2b9d3f715` (§11.5).
4. **Data migration**: encrypt existing plaintext rows in `external_credentials` and the LLM/TTS keys in `user_configurations` / `organization_configurations`. Idempotent, reversible, backup first (§11.4).
5. **Routes**: set / rotate / revoke a provider credential. No read endpoint ever returns the secret — only `provider`, `last_four`, `rotated_at`.
6. **UI**: ElevenLabs section in Settings following the existing `WebhookAuthTab` pattern. Paste to set; thereafter shows `…last4` with rotate and revoke.

**Acceptance:** key entered through the UI and used to make a live authenticated ElevenLabs call; `SELECT credential_data FROM external_credentials` shows ciphertext for every row; no secret in any API response or log line; unit tests cover round trip, legacy-plaintext pass-through, missing/malformed key, tampered ciphertext, and key mismatch; existing suite green.

---

### Phase 1b — ElevenLabs client + tenancy *(was Phase 2)*
**Purely additive. Engine untouched. Prod unaffected.**

- `api/services/elevenlabs/` — one typed client covering: agents (create/get/list/update/duplicate, drafts/versions/publish), knowledge base (create from file/url/text, list, delete, index), tools (webhook/client/MCP + system tools: transfer-to-number, voicemail detection, end-call), phone numbers (import Twilio, list, assign, outbound call, batch calling), conversations (list, get, transcript, audio, signed URL, analysis), workspace (secrets, env vars).
- Additive migration per §5.
- Tenant-scoped credential resolution: every ElevenLabs call resolves the calling org's credential through Phase 1a. No global client, no module-level key.

**Acceptance:** list a real client's agents from a real ElevenLabs workspace through our API; unit tests against a mocked client; existing test suite still green; **prod still serving calls on the engine**.

---

### Phase 2 — Conversation ingestion *(was Phase 4)*
**Dual-source: engine calls and vendor calls both land in `workflow_runs`.**

- `api/routes/<vendor>_webhooks.py` — signature-verified, idempotent on `vendor_conversation_id`. Resolves the client from agent/workspace, writes the run row, transcript JSONB, extracted data into `gathered_context`, and updates `organization_usage_cycles`.
- Recording: fetch call audio via the vendor's audio/signed-URL endpoint, store in MinIO under a per-client key, set `recording_url` + `storage_backend`. Reuses the existing `s3_upload` task and signed-URL route.

**Acceptance:** a vendor test call appears in our DB within seconds with transcript, playable recording, duration and sentiment, attributed to the correct client; replaying the same webhook creates no duplicate row; engine-originated calls still write to the same table unaffected.

---

### Phase 3 — Agent editor + first client live *(the go/no-go gate)*

- New UI route (`/agents`) **alongside** the existing `/workflow` editor — client switcher, agent list, agent editor (system prompt, voice, language, tools, knowledge base, conversation settings), save-as-draft → publish via vendor versions/deployments.
- **Cross-repo decision executed** (§7.2 of recon): re-express `noralai.noralvoice` over vendor agents, or freeze the plugin until Phase 5. Coordinate with the NoralOS repo before merging.
- **Move one real client end-to-end**: create agent → attach number → real inbound call → real outbound call → both appear in the dashboard with recording + transcript.

**Acceptance:** the real-call round trip above, verified in production, scoped to one client. **If the vendor cannot express that client's behavior, we find out here — while the engine still exists.** No engine code deleted yet.

---

### Phase 4 — Migrate remaining clients
Agent-by-agent. Each migration: recreate on the vendor, cut the number over, verify a live call, mark the old workflow archived. Track progress in a checklist committed to the repo.

**Acceptance:** all production traffic served by the vendor; zero calls routed to the engine for a full agreed observation window (recommend 7 days).

---

### Phase 5 — DESTRUCTIVE: remove the engine *(was Phase 1)*
**Authorized only after Phase 4 acceptance. Confirm the file list with me before deleting.**

- Delete: `pipecat/` submodule; `api/services/pipecat|audio|smart_turn|looptalk|campaign`; `api/services/workflow/pipecat_engine*.py`, `workflow_graph.py`, `node_specs/`; `api/services/telephony/providers/`; `api/native/rnnoise`; `dograh_pcm_cache`; `evals/`; routes `webrtc_signaling`, `agent_stream`, `turn_credentials`, `telephony`, `campaign`, `looptalk`, embed stack; `ui/src/components/flow/`, `ui/src/app/workflow|campaigns|looptalk|telephony-configurations`.
- Drop `coturn` from compose + `config/coturn`. Slim `api/requirements.txt`.
- Collapse `api/services/configuration/registry.py` from 15+ providers to the vendor (+ optional BYO-LLM).
- Phase-5 table drops per §5.
- Remove tests for deleted features.

**Acceptance:** `docker compose up` runs the slim stack; UI loads; API health check passes; `grep -ri "pipecat\|coturn\|webrtc"` returns no hits in `api/` or `ui/src/`; full suite green; **prod still serving calls throughout** (nothing deleted was in the serving path).

---

### Phase 6 — Dashboards + usage/billing
Calls dashboard (table, inline audio player, transcript view, sentiment, extracted fields, duration) and usage view (minutes, calls, cost per client per period). Built on the existing reports layer.

**Acceptance:** dashboards render real ingested data per client; totals reconcile against the vendor's own history for a sample period.

---

### Phase 7 — Isolation hardening + RBAC
Tenant scoping enforced on every query and every vendor API call. RBAC: Noral admin vs. per-client scope. Wire workspace-per-client if on Enterprise.

**Acceptance:** an automated test proving no endpoint returns cross-client data; role checks enforced and tested.

---

### Phase 8 — Cleanup, docs, deploy
Dead config removal, `README`, `deploy/noral` refreshed for the slim stack, CI updated.

**Acceptance:** clean build, green CI, deploy to `voice.noral.ai`, one end-to-end call verified in production against the slim stack.

---

## 7. Confirmed defaults

| Decision | Setting |
|---|---|
| **Tenancy** | Schema designed for workspace-per-client (`vendor_workspace_id` + per-client credential); MVP runs on a single workspace. The credential lookup is the same code path either way, so this is zero-cost future-proofing. Confirm Enterprise/Consolidated Billing status. |
| **Client access** | Noral-internal only for v1. Client-facing read dashboards later — an RBAC change, not an architecture change. |
| **Recording storage** | Download to MinIO. Bucket, upload task, and signed-URL routes already exist; decouples retention from the vendor. |

---

## 8. Do NOT

- Do NOT reintroduce any real-time media path (Pipecat, WebRTC, coturn, audio streaming, turn detection).
- Do NOT store provider API keys or Twilio tokens in the repo, logs, or client-side code.
- Do NOT hardcode the ElevenLabs key in env, code, or config. It is entered in the platform UI and stored encrypted (§11). The **only** credential in env is `CREDENTIAL_ENCRYPTION_KEY`.
- Do NOT return a secret from any read endpoint once written — `last_four` only.
- Do NOT write a plaintext credential to the database after Phase 1a lands, including in a migration or a fixture.
- Do NOT run the Phase 1a data migration before a verified backup exists.
- Do NOT return or render data across client boundaries anywhere.
- Do NOT preserve upstream Dograh compatibility at the cost of keeping engine code.
- Do NOT expand scope into "just a small" custom voice feature — use the vendor's BYO-LLM hook.
- Do NOT run any Phase 5 deletion before Phase 4 acceptance.
- Do NOT create parallel tables where §5 says to extend an existing one.

---

## 9. Definition of done

A Noral operator logs in, picks a client, creates/edits/publishes that client's agent from our branded UI, the client's phone number takes and makes calls (handled entirely by the vendor), and every call lands in our dashboard with a playable recording, full transcript, sentiment, extracted fields, and usage that rolls up into per-client billing — **with zero real-time voice infrastructure running in this repo.**

---

## 10. Open items

1. ~~Vendor decision~~ — resolved: ElevenLabs (§3).
2. ~~Phase 0.5 working-tree disposition~~ — resolved: shelved at `312c0e0`, tree clean.
3. **NoralOS plugin plan (§Phase 3)** — deferrable to Phase 3, not past it.
4. **Backup confirmation before the Phase 1a data migration** (§11.4) — blocks that step only.
5. **ElevenLabs Enterprise / Consolidated Billing status** — decides whether Phase 7 wires real workspace isolation or control-plane-enforced boundaries.

---

## 11. Phase 1a design — credential management

### 11.1 The finding that shapes this phase

`grep -riE "fernet|encrypt|decrypt|cryptography"` across `api/` returns **zero hits**. There is no encryption anywhere in this codebase. Meanwhile `api/db/models.py` carries this on `external_credentials`:

```python
# Encrypted credential data (JSON)
credential_data = Column(JSON, nullable=False, default=dict)
```

The comment is false. Those credentials are plaintext. So are the provider keys in `user_configurations.configuration` and `organization_configurations.value`, including the ElevenLabs TTS key already stored there.

**Consequence for this phase:** moving the API key from env into the platform, on today's storage, would be *weaker* than the env var it replaces — env vars do not appear in `pg_dump` output, nightly backups, or replica snapshots; a plaintext JSON column appears in all three. Given the 2026-05-17 Postgres compromise, that is a demonstrated exposure path, not a theoretical one. Encryption is therefore a precondition of the requested feature, not a nice-to-have bolted on after.

### 11.2 Storage location

`external_credentials`, extended — not a new table.

It is already organization-scoped with a public UUID, `created_by` audit, soft delete, and a unique-name-per-org constraint, and it already has a route (`api/routes/credentials.py`) and a settings tab (`WebhookAuthTab.tsx`) to model the new UI on. One credential store, not a third pattern beside `user_configurations` and `organization_configurations`.

Because it is org-scoped, the ElevenLabs credential is **already the per-client credential** Phase 1b and Phase 7 need. No global key to unpick later.

| Column | Status | Purpose |
|---|---|---|
| `organization_id`, `credential_uuid`, `name`, `created_by`, `is_active` | exists | tenancy, audit, soft delete |
| `credential_data` (JSON) | exists, **behaviour changes** | holds `{"__enc__": "v1:…"}` once encrypted |
| `provider` | **add** | `elevenlabs`; NULL for webhook credentials |
| `last_four` | **add** | UI display without decrypting |
| `rotated_at` | **add** | rotation audit |

### 11.3 Envelope format

Ciphertext is stored as a self-describing string:

```
v1:<urlsafe-base64( 24-byte nonce || ciphertext || Poly1305 MAC )>
```

- **Algorithm:** libsodium `SecretBox` (XSalsa20-Poly1305) via PyNaCl — already a direct dependency, so no new package. Authenticated, so tampering fails loudly instead of yielding garbage.
- **Nonce:** random per encryption. Equal secrets must not produce equal ciphertext, or the database leaks which organizations share a key.
- **Whole-document encryption:** the entire `credential_data` JSON is encrypted as one envelope rather than selected fields, so a sensitive field added later cannot be left in the clear by omission.
- **The `v1:` prefix** does two jobs: it lets reads distinguish an encrypted value from a legacy plaintext one with no schema flag — which is what keeps existing rows working during migration — and it leaves room for `v2:` on key or algorithm rotation.

**Key management.** One 32-byte key, base64-encoded, in `CREDENTIAL_ENCRYPTION_KEY`. This is the one secret that legitimately belongs in the environment: it carries no credential itself, and it is precisely what allows every *actual* credential to live in the database under operator control. Losing it makes existing ciphertext unrecoverable and credentials must be re-entered — back it up with the other deploy secrets.

Reads of legacy plaintext must work **without** a key configured, otherwise deploying this would break every existing installation at startup.

### 11.4 Data migration — the part that touches live data

Existing plaintext credentials get encrypted in place. This is the only step in Phase 1a that writes to production rows, so it is fenced:

1. **Backup first**, verified restorable. This step does not start until that is confirmed (open item §10.4).
2. **Idempotent** — guarded on `is_encrypted()`, so a re-run is a no-op and a partial failure is resumable.
3. **Reversible** — a downgrade path decrypts back to plaintext, so a rollback does not strand the deployment.
4. **Scope:** `external_credentials.credential_data`, plus the LLM/TTS keys nested in `user_configurations.configuration` and `organization_configurations.value`.
5. **Verification:** row counts before and after, and a spot decrypt of each affected table proving plaintext round-trips.

Risk being managed: those LLM keys are serving production calls right now. A bad migration is an outage. Hence backup, idempotence, and a downgrade path rather than a one-way script.

### 11.5 Alembic

Single head: **`e4a2b9d3f715`** (`20260526_add_api_key_plaintext.py`), confirmed with `alembic heads` against the test database. An earlier static scan of this repo suggested four heads; that was wrong — it missed revisions whose `down_revision` is a tuple. No merge revision is needed; Phase 1a chains one schema migration and one data migration off that head.

### 11.6 Exposure rules

- No endpoint returns a secret after it is written — reads expose `provider`, `name`, `last_four`, `rotated_at` only.
- No secret, ciphertext, or key material in any log line, including exception messages. Decryption errors name the failure mode, never the value.
- Secrets never reach the client bundle, URL parameters, or query strings.
- `CREDENTIAL_ENCRYPTION_KEY` is never committed, never logged, never returned by an endpoint.

### 11.7 What this does not cover

Application-level encryption protects database dumps, backups, and replicas. It does **not** protect against an attacker with live application memory or the ability to call the app's own decrypt path — that requires a KMS or HSM holding the key outside the process, which is out of scope here and worth revisiting if a regulated client is onboarded (see §7 tenancy note).
