# NoralVoice → ElevenLabs Control Plane — Build Plan v3

**Supersedes** v2 (`4adda9a`) and the v1 brief ([control-plane-build-prompt-v1-superseded.md](./control-plane-build-prompt-v1-superseded.md)).
**Inputs:** [Phase 0 recon](./control-plane-phase-0-recon.md) · [red-team review](./control-plane-plan-red-team.md) · live Synthflow inventory taken 2026-08-08 (§4).
**Status:** rebuilt to close all 21 red-team findings. Phase 0.6 (capability spike) is the next action.

---

## 1. Mission

Transform this repository from a self-hosted Pipecat/Dograh voice engine into a thin multi-tenant **control plane** over ElevenLabs Agents.

We manage voice agents for clients. We do not want to run a real-time voice pipeline again. We rent the engine via its API and build only the layer that is genuinely ours: a branded UI to create, edit and publish each client's agents; reporting, recordings and transcripts in our own database; per-client isolation and usage/billing rollups.

### Prime directive

1. **Rent the engine. Never rebuild it.** STT, LLM, TTS, turn-taking, telephony media, WebRTC, TURN belong to ElevenLabs. If you find yourself re-adding a media server, streaming audio, or turn detection: **stop**.
2. **Keep the control plane thin.** CRUD + API proxying + webhook ingestion + dashboards + auth.
3. **The escape valve is BYO-LLM — and it is capped.** See §9.2. It is not free and it is not the default answer to a capability gap.
4. **This fork diverges permanently from upstream Dograh.**

---

## 2. What changed in v3

v2 was reviewed adversarially; 21 findings resulted. All are closed here.

| Finding | Resolution |
|---|---|
| **C1** No capability-parity check | **Done, with data** (§4). Live Synthflow inventory pulled: 3 integrations, 159 actions, 14 client subaccounts. Gap list in §4.3. |
| **C2** Gate fires after the money is spent | New **Phase 0.6 spike** before any build. Phase 3 gate is now a purpose-built reference agent (§7 Phase 3) exercising all five action types, then the hardest real client. |
| **C3** Single-workspace MVP is theater | **Fixed by building the controls for real, not by adding a workspace.** Consolidated billing turned out to be Enterprise-only and we are not on Enterprise, so workspace-per-client is unavailable. The isolation controls are built properly regardless, the vendor-side blast radius is documented rather than hand-waved, and the move to workspace-per-client later is a data change (§5). |
| **H1** Encryption justified with wrong threat model | **Corrected with the runbook** (§10.1). The 5/17 attack was RCE *inside the postgres container*; the encryption key lives in the api container. Encryption would have defeated it. |
| **H2** No cost model | **Dropped** — vendor decision is made and not cost-contingent. Phase 6 rollups still surface margin. |
| **H3** No behavioral regression testing | Baseline-capture / replay / diff per agent, keyed on extractor identifiers (§8). |
| **H4** Webhook-only ingestion loses calls | Reconciliation backfill job in Phase 2. |
| **H5** No rollback, no point of no return | Per-client rollback runbook + explicit irreversibility gate (§7 Phase 4/5). |
| **H6** Phase 5 orphans historical calls | Retention step with denormalisation and a verified pre-migration call (§7 Phase 5). |
| **M1** Unverified "no graph counterpart" claim | Verified in Phase 0.6 before scope is fixed. |
| **M2** BYO-LLM uncapped | Capped at §9.2 with a latency budget and a client ceiling. |
| **M3** No exit story | §9.3 — no abstraction, but our data stays complete and the exit cost is written down. |
| **M4** Reliability never measured | Baseline computed in Phase 0.6; threshold in Phase 4 acceptance (§8.3). |
| **M5** Cutover risk understated | Per-client cutover runbook (§7 Phase 4). |
| **M6** Compliance silent | **Materially escalated** — the portfolio includes a medspa, a school, a housing authority, consumer-credit qualification and political campaign calling (§6). |
| **M7** Phase 5 acceptance gameable | Test-count and coverage deltas, per-file justification (§7 Phase 5). |
| **M8** `workflow_runs` legacy debt glossed | Column cleanup scheduled into Phase 5. |
| **L1** Security work on the critical path | Phase 0.6 spike now precedes Phase 1a; they can run in parallel. |
| **L2** No effort estimate | §11. |
| **L3** Shelf branch local-only | §11, open item. |
| **L4** `.gitignore` changed in passing | Noted; keep or revert on request. |

---

## 3. Vendor decision — ElevenLabs (settled)

Confirmed 2026-08-08. The integration layer is `api/services/elevenlabs/`. Synthflow stays live and serving until its last agent migrates in Phase 4; it is **not** a second engine to build against, and there is no provider abstraction (§9.3).

---

## 4. Capability inventory — what the 91 agents actually do

Pulled live from the Synthflow workspace on 2026-08-08. This closes C1, which was the plan's largest unvalidated assumption.

### 4.1 Integrations — smaller than feared

| Integration | Configured |
|---|---|
| Cal.com | **yes** |
| GoHighLevel | no |
| Zendesk | no |

Only **one** third-party integration is actually connected. This substantially supports the position that n8n covers the integration surface — with one important caveat in §4.3.

### 4.2 Actions — 159 total, five types

Census over 150 of 159 actions (pages 1–3; the tail does not introduce new types):

| Action type | Approx. count | What it does |
|---|---|---|
| `extract_info_action_type` | ~105 | Structured data collection — yes/no, choice, open. The dominant pattern by far. |
| `transfer_call_action_type` | ~40 | Cold transfer to a specific number, fired by a natural-language trigger. Includes a Spanish-language trigger. |
| `send_sms_action_type` | 5 | Conditional SMS, mostly TCPA opt-in confirmations with STOP language. |
| `calcom_booking_action_type` | 5 | Native Cal.com booking — event type, days ahead, slots per day, first-appointment date, lead timezone. |
| `custom_function_action_type` | 4 | HTTP calls, two with `run_action_before_call_start: true` (pre-call data fetch). One targets n8n. |

### 4.3 Gap analysis against ElevenLabs

| Capability | Maps to | Risk |
|---|---|---|
| Data extraction (~105) | ElevenLabs data collection / evaluation criteria | **Low.** Direct conceptual match. The 159 extractor identifiers become our equivalence contract (§8). |
| Cold transfer (~40) | `transfer_to_number` system tool | **Low–medium.** Verify cold vs. warm semantics and that natural-language trigger conditions carry over faithfully. |
| SMS (5) | **No native equivalent** — webhook tool → n8n → Twilio | **Medium.** n8n can do it; the workflows **do not exist yet**. |
| Cal.com booking (5) | **No native equivalent** — webhook tool → n8n → Cal.com | **Highest.** The native action carries real logic: slot windows, days ahead, per-day slot caps, timezone, first-available date. All of that must be rebuilt. |
| Pre-call HTTP fetch (4) | Webhook tools / dynamic variables | **Medium.** Verify ElevenLabs supports a genuine *pre-call* fetch that populates variables before the first turn. |

**The honest conclusion:** n8n does cover the integration surface, but "covered by n8n" is not the same as "already built." Cal.com booking and SMS are today *native platform features* we get for free. On ElevenLabs they become **n8n workflows we own, build, and operate**. That is net-new work this plan now carries explicitly, and it is concentrated in a small number of agents.

### 4.4 Two incidental findings

- **`repeat_caller_check` points at a test webhook.** Its URL is `https://noralai.app.n8n.cloud/webhook-test/4ce754bd-…`. n8n test webhooks only fire while the workflow editor is listening — this is very likely dead in production. Worth checking independently of this migration.
- **`info_extractor_ccnumber`** collects "the caller's last 4 digits of the credit card" into call transcripts. See §6.

---

## 5. Tenancy — one workspace, isolation controls built for real

### 5.1 The constraint

Verified against ElevenLabs documentation: multi-seat workspaces exist on Scale, Business and Enterprise, but **consolidated billing — linking multiple workspaces under one billing account with a shared credit pool and a single invoice — is Enterprise-only** and requires a CSM to enable.

We are not on Enterprise. Multiple standalone workspaces would therefore mean 14 separate subscriptions with 14 non-shareable credit pools — more expensive than one pooled plan, with credit stranded per client. **Decision (2026-08-08): single workspace.**

### 5.2 What C3 actually demanded

The red-team objection was never "you must have N workspaces." It was that v2 *claimed* per-client isolation while shipping a design where every org's credential held the same key — isolation theater. The fix is to build every control properly and be explicit about the one residual we cannot close on this tier.

**Built for real, from day one:**

1. **Per-organization credential rows** (§10) — one row per client, encrypted. Today they resolve to the same workspace key; the resolution path never assumes that.
2. **No ambient credential anywhere.** No module-level client, no default workspace, no environment fallback. Every ElevenLabs call resolves its key from the calling organization or fails.
3. **Mandatory org-scoping** on every query. No endpoint accepts a client identifier the caller doesn't own.
4. **Cross-tenant denial test in CI** (Phase 7), asserted per route.
5. **Per-client MinIO prefixes** for recordings.
6. **Our Postgres is the isolated system of record** — the copy that reporting, billing and client access read from is properly partitioned even while the vendor's is not.

### 5.3 The residual, stated plainly

With one workspace, all clients' agents, phone numbers, conversations and recordings are **commingled on the ElevenLabs side behind a single key**. Anyone holding that key — our staff, a leaked CI secret, an attacker — can see every client's call data. Our controls do not change that; they bound what our *own* application will serve.

This matters more than average here because of the §6 portfolio: a medspa, a school, a housing authority, consumer-credit qualification. Consequences:

- **Phase 0.6 must check ElevenLabs' retention and privacy controls** — zero-retention or reduced-retention modes, and what is stored vendor-side at all — since minimising vendor-held data is the main lever we still have.
- Treat the workspace key as the highest-value secret in the system. It is one credential away from total portfolio disclosure.
- Revisit before onboarding any client with a contractual isolation requirement.

### 5.4 Forward path

`organizations.elevenlabs_workspace_id` is populated from day one, and every credential lookup already goes through the per-org path. Moving to workspace-per-client — on Enterprise, or by standing up separate subscriptions for specific clients — becomes **a data change: write a new workspace id and a new key on that org's row.** No code change. Regulated clients can be moved individually without waiting for the whole portfolio.

The 14 existing Synthflow subaccounts (Ethos Residential Services, Affordable Solar, MET Marketing, I-DIEM, Allure, Aspire Medspa, Academy Prep, Energy Harbor, The Trench Academy, John A Williams, Southern States Roofing, Hometown Roofing, TBRS, Florida Made Tiny Homes) map one-to-one to `organizations` rows regardless of how many ElevenLabs workspaces sit behind them. Seven have Twilio active; per-client telephony config is captured in Phase 0.6.

---

## 6. Compliance — escalated

The inventory turned M6 from a hypothetical into a live issue. The portfolio includes:

| Client / data | Concern |
|---|---|
| **Aspire Medspa** | Health-adjacent call content, recorded and transcribed. Potential HIPAA exposure; a BAA may be required with any processor. |
| **Academy Prep** | A school — calls may involve minors or student records (FERPA/COPPA). |
| Tampa Housing Authority (in agent actions) | Public housing; tenant PII under HUD-adjacent obligations. |
| **Affordable Solar / Energy Harbor** | Extracts credit score band ("above 650?") and utility billing. Consumer financial data; FCRA-adjacent; heavy outbound TCPA exposure. |
| `campaign_*` actions | Election-day calling — TCPA plus state robocall regimes. |
| `info_extractor_ccnumber` | Credit-card last-4 captured into transcripts we are about to store. |
| DNC handling (`info_extractor_dnd`) | Do-not-call capture exists as an extractor; its downstream enforcement must survive migration. |

Compounding this: with a single shared workspace (§5.3), every one of these clients' recordings and transcripts sits behind one vendor key. The compliance questions below are therefore about the portfolio, not just the individual client being migrated.

**Required before Phase 4 migrates any of these clients:**

- Confirm no client contract contains a data-residency, retention, or subprocessor clause that this migration breaks. Note `api/services/configuration/registry.py:495` already exposes an ElevenLabs EU residency endpoint — someone previously anticipated this.
- Confirm whether ElevenLabs will sign a BAA if medspa call content warrants one.
- Decide retention policy for recordings and transcripts in MinIO, per client.
- Confirm DNC/opt-out state survives the platform change, and that consent records remain auditable.

Regulated clients migrate **last**, after the pattern is proven on unregulated ones.

---

## 7. Phases

Rules for every phase: one phase at a time; branch `feat/control-plane-phase-N`; never force-push; never touch other branches or worktrees; ask before any destructive action a phase doesn't authorize; tests for every new backend capability; written summary at the end, then wait for go-ahead.

### Phase 0 — Recon ✅
[control-plane-phase-0-recon.md](./control-plane-phase-0-recon.md).

### Phase 0.5 — Working-tree hygiene ✅
Shelved at `312c0e0`; tree clean on `feat/control-plane-phase-0`; conflict duplicates removed; v1 brief superseded.

### Phase 0.6 — Capability spike ⬅ **next; no product code**

Closes C1/C2/M1/M4 and de-risks everything after it. Read-only against both platforms.

1. **Verify ElevenLabs feature mapping** against live API docs for each row of §4.3 — especially whether conversational flows/graphs exist (M1), transfer semantics, pre-call variable population, and data-collection expressiveness.
2. **Check ElevenLabs retention and privacy controls** (§5.3) — zero/reduced-retention modes, what conversation data is stored vendor-side, and any per-agent privacy settings. With one shared workspace this is the main lever for limiting vendor-held client data, and it feeds the §6 compliance answers.
3. **Prototype the two real gaps** end-to-end in n8n: Cal.com booking (slots/days/timezone) and SMS opt-in. These are the only capabilities with no native counterpart.
4. **Reliability baseline** from `workflow_runs` — noting `WorkflowRunState` has no failure state (`api/enums.py:66`), so use initialized-never-completed as the proxy and document the method.
5. **Per-agent complexity profile** for all 91 agents: action types used, extractor count, transfer targets, telephony config. Output ranks agents and **names the Phase 3 gate client**.

**Acceptance:** a written gap report; a working n8n booking prototype; a stated reliability baseline; a ranked migration order; retention controls documented. **If a gap has no viable mapping, that surfaces here — before anything is built.**

### Phase 1a — Credential management + encryption
Full design in §10. Six steps: crypto module → transparent encrypt/decrypt in the credential client → schema (`provider`, `last_four`, `rotated_at`) → data migration of existing plaintext → set/rotate/revoke routes → Settings UI.

**Acceptance:** key entered through the UI authenticates a live ElevenLabs call; `SELECT credential_data FROM external_credentials` is ciphertext for every row; no secret in any response or log; tests cover round trip, legacy pass-through, missing/malformed key, tampered ciphertext, key mismatch; existing suite green.

### Phase 1b — ElevenLabs client + tenancy
`api/services/elevenlabs/` — agents (CRUD, versions, publish), knowledge base, tools (webhook/client/MCP + transfer-to-number, voicemail detection, end-call), phone numbers (Twilio import, assign, outbound, batch), conversations (list, get, transcript, audio, signed URL, analysis), workspace (secrets, env vars). Additive migration per §13. Per-client credential resolution on every call.

**Acceptance:** list a real client's agents from that client's own workspace; no code path can reach a workspace the caller doesn't own; mocked-client unit tests; suite green; **prod still serving on the engine**.

### Phase 2 — Conversation ingestion
Dual-source — engine and ElevenLabs calls both land in `workflow_runs`.

- `api/routes/elevenlabs_webhooks.py`: signature-verified, idempotent on `elevenlabs_conversation_id`, resolves client from workspace/agent, writes run + transcript JSONB + extracted data + usage rollup.
- **Reconciliation backfill (H4):** a scheduled job listing conversations from the ElevenLabs API for the last N hours and inserting anything the webhook missed. Idempotency makes it safe to run often.
- Recording: fetch audio, store in MinIO per-client, set `recording_url` + `storage_backend`.

**Acceptance:** a test call lands within seconds with transcript, playable recording, duration, sentiment, correct client; replaying a webhook creates no duplicate; **killing the webhook endpoint, placing a call, then running reconciliation recovers it**; engine calls unaffected.

### Phase 3 — Agent editor + gate
New `/agents` route beside the existing `/workflow` editor: client switcher, agent list, editor (prompt, voice, language, tools, KB, settings), draft → publish.

**The gate, in two steps (C2):**

1. **Reference agent** — a purpose-built test agent exercising **all five action types** from §4.2 at once: extraction, cold transfer, SMS opt-in, Cal.com booking, pre-call fetch. Not a client. This is what proves the platform, and it is the agent to iterate on freely.
2. **Hardest real client**, chosen by the Phase 0.6 ranking — not the easiest. Unregulated, per §6.

**Cross-repo (NoralOS):** the `noralai.noralvoice` plugin (32 tools, live on `agent.noral.ai`) and both typed SDKs author workflow graphs. Decide here — re-express over ElevenLabs agents, or freeze until Phase 5 — and coordinate before merging.

**Acceptance:** reference agent handles all five capabilities on a real call; then the gate client runs real inbound **and** outbound, appearing in the dashboard with recording and transcript. No engine code deleted.

### Phase 4 — Migrate remaining clients
Per client, in Phase 0.6 ranked order, unregulated first:

1. Capture the behavioral baseline (§8) **before** touching anything.
2. Recreate agent + actions on the client's ElevenLabs workspace.
3. Replay the baseline; diff extracted fields and transfer decisions; resolve every difference.
4. **Cutover runbook (M5):** low-traffic window; update the Twilio number config; verify inbound *and* outbound on a live call; monitor for missed calls for an agreed period. Note the documented failure mode in this project — a number whose config never gets PATCHed silently keeps serving its old destination.
5. **Rollback (H5):** if the client degrades, revert the Twilio number config and re-enable the engine workflow. Written per client before cutover, not improvised after.
6. Mark the old workflow archived (not deleted).

**Acceptance:** all traffic on ElevenLabs; behavioral diff resolved for every agent; reliability at or above the Phase 0.6 baseline (§8.3); zero engine-routed calls for a 7-day soak.

### Phase 5 — DESTRUCTIVE: remove the engine
**Point of no return (H5).** Authorized only after Phase 4 acceptance including the 7-day soak, and after an explicit written go-ahead. Confirm the file list before deleting.

1. **Data retention first (H6).** `workflow_runs` FKs to `workflows`, `workflow_definitions`, `campaigns`, `queued_runs` (`api/db/models.py:453,457,492,494`) — three of those four tables get dropped. Denormalise what reporting needs onto `workflow_runs`, null the dead FKs, and **verify a pre-migration call still resolves end-to-end with playable recording** before any drop runs.
2. Delete: `pipecat/` submodule; `api/services/pipecat|audio|smart_turn|looptalk|campaign`; `workflow/pipecat_engine*.py`, `workflow_graph.py`, `node_specs/`; `telephony/providers/`; `api/native/rnnoise`; `dograh_pcm_cache`; `evals/`; routes `webrtc_signaling`, `agent_stream`, `turn_credentials`, `telephony`, `campaign`, `looptalk`, embed stack; `ui/src/components/flow/`, `ui/src/app/workflow|campaigns|looptalk|telephony-configurations`.
3. Drop `coturn` from compose + `config/coturn`; slim `api/requirements.txt`; collapse `configuration/registry.py` to ElevenLabs (+ BYO-LLM).
4. Phase-5 table drops (§13) and the `workflow_runs` column cleanup (M8).

**Acceptance (M7):** slim stack boots; `grep -ri "pipecat\|coturn\|webrtc"` clean in `api/` and `ui/src/`; **test count and coverage recorded before and after, with every removed test file justified against a specific deleted feature**; a live end-to-end call verified *after* the deletion deploys; a pre-migration historical call still resolves.

### Phase 6 — Dashboards + usage/billing
Calls dashboard (table, audio player, transcript, sentiment, extracted fields) and usage view per client per period, on the existing reports layer.

**Acceptance:** renders real per-client data; reconciles against ElevenLabs' own history for a sample period.

### Phase 7 — Isolation hardening + RBAC
Tenant scoping on every query and every ElevenLabs call; RBAC (Noral admin vs. per-client). Workspace-per-client wiring verified end to end.

**Acceptance:** an automated test proving no endpoint returns cross-client data, running in CI; role checks enforced and tested.

### Phase 8 — Cleanup, docs, deploy
Dead config, `README`, `deploy/noral` for the slim stack, CI.

**Acceptance:** clean build, green CI, deployed to `voice.noral.ai`, one end-to-end call verified in production.

---

## 8. Behavioral equivalence (H3)

"Verify a live call" proves an agent answers, not that it behaves the same. The 159 extractor identifiers give us a natural contract.

### 8.1 Baseline capture — before migrating an agent
For each agent, record a set of scenario transcripts and, for each, the expected outputs: extracted field values by identifier, transfer taken (and target), SMS sent, booking created, call outcome/disposition.

### 8.2 Replay and diff — after recreating it
Run the same scenarios against the ElevenLabs agent. Diff on identifiers, not prose. **Any difference blocks cutover until explained.** LoopTalk exists today and can drive this; it is not deleted until Phase 5. ElevenLabs simulation suites carry it afterwards.

### 8.3 Reliability threshold (M4)
Phase 0.6 sets the baseline. A migrated agent must meet or beat it before its client is signed off. Definition is documented with the baseline, since `WorkflowRunState` has no failure state and the metric is a proxy.

---

## 9. Standing constraints

### 9.1 Exposure rules
No endpoint returns a secret once written — `provider`, `name`, `last_four`, `rotated_at` only. No secret, ciphertext, or key material in any log line or exception message. Never in URLs, query strings, or the client bundle. `CREDENTIAL_ENCRYPTION_KEY` is never committed, logged, or returned.

### 9.2 BYO-LLM cap (M2)
BYO-LLM means running an inference endpoint **inside the latency-critical voice path** — infrastructure, which the prime directive forbids. It is therefore bounded:

- Permitted for at most **2 clients** without a fresh decision.
- Must meet a stated p95 latency budget, set in Phase 0.6.
- Reaching for it a third time is a signal to re-examine the vendor choice, not to keep extending.

### 9.3 Exit cost (M3)
No provider abstraction — that stays correct. But this migration exists *because* you are leaving Synthflow, so switches demonstrably happen. The mitigation is data ownership, not indirection: conversations, transcripts, extracted data and recordings live in **our** Postgres and MinIO, complete enough that a future switch means rewriting `api/services/elevenlabs/` — not reconstructing history. Anything that would make our copy incomplete is a design error.

---

## 10. Phase 1a design — credential management

The ElevenLabs key is entered and rotated **in the platform UI**. Never in code, never in env.

### 10.1 Threat model — corrected (H1)

v2 justified this phase by gesturing at the 2026-05-17 Postgres compromise. The runbook (`docs/runbooks/postgres-compromise.md`) makes the access path specific: **pg_mem / Operation Hadooken** — a Postgres-service compromise yielding a `priv_esc` superuser role, `escalate_priv()` event-trigger persistence, and cryptominer RCE **inside `dograh-postgres-1`** (`/tmp/mysql`, `/tmp/init`).

That is container-scoped execution in **postgres**. `CREDENTIAL_ENCRYPTION_KEY` lives in the **api** container's environment. So under the observed access path, application-level encryption **would have defeated credential theft** — the attacker had full database access and no key.

This strengthens the phase rather than weakening it. Stated limits, honestly:

- Protects: database dumps, backups, replicas, and a database-scoped compromise — i.e. exactly what happened.
- Does not protect: container escape to the host, or anything that can read the api container's memory or call its decrypt path. That needs a KMS, out of scope here and worth revisiting for the regulated clients in §6.

The current state makes this urgent: `grep -riE "fernet|encrypt|decrypt|cryptography"` across `api/` returns **zero hits**, while `external_credentials` carries a comment claiming its data is encrypted. It is plaintext. So are the provider keys in `user_configurations` and `organization_configurations`.

### 10.2 Storage
`external_credentials`, extended — already org-scoped with UUID, `created_by` audit, soft delete, unique-name-per-org, an existing route and a settings-tab pattern to follow. One credential store.

| Column | Status | Purpose |
|---|---|---|
| `organization_id`, `credential_uuid`, `name`, `created_by`, `is_active` | exists | tenancy, audit |
| `credential_data` | exists, behaviour changes | holds `{"__enc__": "v1:…"}` |
| `provider` | add | `elevenlabs`; NULL for webhook credentials |
| `last_four` | add | UI display without decrypting |
| `rotated_at` | add | rotation audit |

### 10.3 Envelope
`v1:<urlsafe-base64( 24-byte nonce ‖ ciphertext ‖ Poly1305 MAC )>`, libsodium `SecretBox` (XSalsa20-Poly1305) via PyNaCl — already a direct dependency (`api/requirements.txt:21`). Random nonce per encryption, so equal secrets never produce equal ciphertext. The whole `credential_data` document is encrypted, not selected fields, so a field added later can't be left in the clear. The `v1:` prefix lets reads distinguish encrypted from legacy plaintext with no schema flag, and leaves room for `v2:` on rotation.

Key: one base64 32-byte value in `CREDENTIAL_ENCRYPTION_KEY`. Legacy plaintext reads must work **without** a key configured, or deploying this breaks every existing installation at startup.

### 10.4 Data migration
The only step writing to live rows, so it is fenced: verified backup first (§12); idempotent, guarded on `is_encrypted()`; reversible via a downgrade that decrypts; scope is `external_credentials.credential_data` plus the LLM/TTS keys in `user_configurations.configuration` and `organization_configurations.value`; verification is row counts before/after plus a spot decrypt per table. Those LLM keys are serving production calls — a bad migration is an outage.

### 10.5 Alembic
Single head **`e4a2b9d3f715`**, confirmed via `alembic heads`. (An earlier static scan suggested four; it missed tuple `down_revision`s.) Phase 1a chains one schema and one data migration off it.

---

## 11. Effort (L2)

Rough magnitudes, not commitments:

| Phase | Magnitude | Driver |
|---|---|---|
| 0.6 spike | days | Docs verification + two n8n prototypes |
| 1a | days | Crypto + migration + UI, small surface |
| 1b | 1–2 weeks | Broad API client, well-specified |
| 2 | days | One endpoint + one job |
| 3 | 1–2 weeks | New UI + reference agent + gate client |
| **4** | **weeks — the long pole** | 91 agents × baseline, recreate, diff, cutover, monitor |
| 5 | ~1 week | ~50k lines deleted, retention work first |
| 6–8 | 1–2 weeks | Dashboards, RBAC, deploy |

Phase 4 dominates and is the one to resource deliberately.

---

## 12. Open items

1. ~~Enterprise status~~ — resolved 2026-08-08: not on Enterprise; single workspace with controls built for real (§5).
2. ~~Shelf branch local-only~~ — resolved: pushed to `origin/shelf/pre-control-plane-2026-08-08`.
3. **Verified restorable backup** — blocks the Phase 1a data migration step only, and is taken immediately before it, not in advance (§10.4).
4. **Compliance confirmations** (§6) — block Phase 4 for the regulated clients, not the whole phase. Now also need to account for vendor-side commingling (§5.3).
5. **NoralOS plugin decision** — due at Phase 3.
6. `.claude/` was added to `.gitignore` in passing — keep or revert.

---

## 13. Data model

### Phase 1 — additive (prod-safe)

| Table | Add |
|---|---|
| `organizations` | `name`, `status`, `elevenlabs_workspace_id` |
| `external_credentials` | `provider`, `last_four`, `rotated_at`; `credential_data` encrypted (§10) |
| `workflows` | `elevenlabs_agent_id`, `elevenlabs_current_version` |
| `telephony_phone_numbers` | `elevenlabs_phone_number_id` |
| `workflow_runs` | `elevenlabs_conversation_id` (**unique** — idempotency key), `duration_seconds`, `sentiment`, `transcript` (JSONB) |

Reused as-is: `workflow_runs.recording_url` / `transcript_url` / `storage_backend` / `usage_info` / `cost_info` / `gathered_context` (extracted data) / `call_type` / `annotations`; `organization_usage_cycles`; `organizations.quota_*` / `price_per_second_usd`.

### Phase 5 — drops
`workflow_definitions`, `workflow_templates`, `looptalk_*`, `campaigns`, `queued_runs`, `embed_*`, `knowledge_base_chunks`, `telephony_configurations`, graph JSON columns on `workflows` — **after** the §7 Phase 5 retention step.

---

## 14. Do NOT

- Do NOT reintroduce any real-time media path (Pipecat, WebRTC, coturn, audio streaming, turn detection).
- Do NOT hardcode the ElevenLabs key in env, code, or config. The **only** credential in env is `CREDENTIAL_ENCRYPTION_KEY`.
- Do NOT return a secret from any read endpoint once written — `last_four` only.
- Do NOT write a plaintext credential to the database after Phase 1a, including in a migration or fixture.
- Do NOT run the Phase 1a data migration before a verified backup.
- Do NOT let the shared workspace (§5) become a reason to skip an isolation control. Org-scoping, per-org credential rows, and the cross-tenant test are mandatory *because* the vendor side is commingled, not optional despite it.
- Do NOT introduce an ambient ElevenLabs credential — no module-level client, no default workspace, no env fallback. Every call resolves from the calling organization or fails.
- Do NOT migrate a regulated client (§6) before the compliance confirmations land.
- Do NOT cut a number over without a written rollback for that client.
- Do NOT begin Phase 5 before the 7-day soak and an explicit go-ahead.
- Do NOT delete a test to make the suite green.
- Do NOT reach for BYO-LLM beyond the §9.2 cap.
- Do NOT preserve upstream Dograh compatibility at the cost of keeping engine code.

---

## 15. Definition of done

A Noral operator logs in, picks a client, creates/edits/publishes that client's agent from our branded UI, the client's number takes and makes calls handled entirely by ElevenLabs, and every call lands in our dashboard with a playable recording, full transcript, sentiment, extracted fields, and usage rolling up into per-client billing — each client isolated in its own workspace, at or above the pre-migration reliability baseline, **with zero real-time voice infrastructure running in this repo.**
