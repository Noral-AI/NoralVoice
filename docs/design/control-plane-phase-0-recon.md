# Phase 0 — Recon: NoralVoice → ElevenLabs Control Plane

**Status:** recon complete, no code changed.
**Repo state at time of survey:** branch `claude/workflow-hard-delete`, HEAD `38b9ecb`, 13 modified files uncommitted.

---

## 1. Verdict up front

The build prompt is directionally right about *what* to keep and cut, but wrong about *scale* and *order*.

Three things need to change before any code is written:

1. **The engine is not isolated in `pipecat/`.** 106 Python files reference pipecat, spanning telephony (11k lines / 7 providers), the workflow engine (7k lines), looptalk, tasks, utils, db, and the MCP server. Deleting "the engine" means deleting roughly two-thirds of the backend and most of the frontend, not one directory.
2. **The data model you specified is ~80% already built.** `organizations` → `client`, `workflow_runs` → `conversation`, `organization_usage_cycles` → `usage_rollup`. Building parallel tables would be a self-inflicted migration. Extend, don't duplicate.
3. **Phase order is backwards and unsafe.** The plan deletes the engine (Phase 1) before proving ElevenLabs covers the use cases (Phases 2–4). `voice.noral.ai` is live and taking real calls. Recommended change: **strangler, not big-bang** — stand up the ElevenLabs path alongside the engine, move one real client onto it end-to-end, *then* delete. Detail in §6.

Two strategic questions must be answered before Phase 1, both in §7: **Synthflow** (you already run 91 agents on a managed platform of exactly this shape) and **NoralOS coupling** (the shipped `noralai.noralvoice` plugin authors workflow graphs; deleting them breaks `agent.noral.ai` in production).

---

## 2. Corrections to the prompt's assumed layout

| Prompt claim | Reality |
|---|---|
| `pipecat/` is a directory to delete | It's a **git submodule** (`dograh-hq/pipecat`, 33 MB, 1 tracked entry). Removing it is a one-liner; the coupling in `api/` is the actual work. |
| `native/rnnoise` | No top-level `native/`. It's `api/native/rnnoise/librnnoise.so.0.4.1` — a single binary. |
| `dograh_pcm_cache` | Exists but is **empty (0 B)** and untracked. Trivial. |
| `api/services/audio`, `api/services/smart_turn` | Confirmed. Small: 257 and 795 lines. |
| `api/routes/webrtc_signaling.py`, `agent_stream.py`, `turn_credentials.py` | Confirmed: 509, 189, ~small lines. `coturn` service confirmed in `docker-compose.yaml` + `config/coturn`. |
| `api/services/looptalk` | Confirmed, 1,816 lines + 2 DB tables + UI. This is agent-vs-agent call testing → maps to ElevenLabs simulation suites. |
| "Likely KEEP: `api/routes/knowledge_base.py` (re-point to ElevenLabs KB)" | Correct, but note it has its own chunking/embedding stack (`knowledge_base_chunks` table + `api/tasks/knowledge_base_processing.py`). Re-pointing means deleting a local RAG pipeline, not swapping a URL. |

**What the prompt does not mention at all**, and which dominates the effort:

- **The node-graph workflow editor.** `api/services/workflow/` (7,096 lines: `workflow_graph.py`, `node_specs/`, `pipecat_engine*.py`) + `ui/src/components/flow/` (3,401) + `ui/src/app/workflow/` (9,329). ~20k lines of visual agent authoring. **ElevenLabs agents are prompt+tools shaped, not graph shaped.** Phase 3 is not "edit the existing editor" — it is delete ~20k lines and write a new form.
- **Telephony: 11,124 lines across 7 providers** (twilio, telnyx, plivo, vonage, vobiz, cloudonix, ari) + `telephony_configurations` / `telephony_phone_numbers` tables + UI. Bigger than the pipecat services themselves. All replaced by ElevenLabs' native Twilio import.
- **Campaigns:** 3,095 API + 2,621 UI lines + `campaigns` / `queued_runs` tables → ElevenLabs batch calling. Not a 1:1 mapping; dialer pacing/retry logic has no direct counterpart.
- **Embed / widget stack:** `embed.py`, `public_embed.py`, `workflow_embed.py`, `public_agent.py` + `embed_tokens` / `embed_sessions` / `embed_exchange_tokens` tables → ElevenLabs widget.
- **SDK + MCP server:** `sdk/python`, `sdk/typescript` (typed node classes), `api/mcp_server/` (13 files). See §7.2.

---

## 3. Keep / Cut / Re-point

### CUT — real-time media path (uncontroversial)

| Path | Size | Note |
|---|---|---|
| `pipecat/` submodule | 33 MB | `git submodule deinit` + `git rm` |
| `api/services/pipecat/` | 4,786 | service factory, TTS one-shot, transports |
| `api/services/audio/`, `api/services/smart_turn/` | 1,052 | |
| `api/native/rnnoise/` | binary | |
| `api/routes/webrtc_signaling.py`, `agent_stream.py`, `turn_credentials.py` | ~750 | + unregister from `api/routes/main.py:54,55,66` |
| `coturn` service | compose + `config/coturn` | |
| `evals/stt`, `evals/visualizer`, `dograh_pcm_cache` | | |

### CUT — engine-shaped product surface (the part the prompt underestimates)

| Path | Size | Replaced by |
|---|---|---|
| `api/services/workflow/pipecat_engine*.py`, `workflow_graph.py`, `node_specs/` | ~7,000 | ElevenLabs agent config |
| `ui/src/components/flow/`, `ui/src/app/workflow/` | ~12,700 | New agent editor form |
| `api/services/telephony/providers/` (7) + `api/routes/telephony.py` | ~12,000 | ElevenLabs native Twilio |
| `api/services/looptalk/` + `api/routes/looptalk.py` + UI | ~2,400 | ElevenLabs simulation suites |
| `api/services/campaign/` + `api/routes/campaign.py` + UI | ~6,700 | ElevenLabs batch calling |
| Embed stack (4 routes + 3 tables + UI) | ~1,400 | ElevenLabs widget |
| `api/tasks/knowledge_base_processing.py` + `knowledge_base_chunks` | | ElevenLabs KB/RAG |

### KEEP — the shell that is genuinely ours

| Path | Why |
|---|---|
| `api/services/auth/` (`stack_auth`, `google_oauth`, `noral_sso`, `depends`, `oauth_state`) | 1,116 lines, recently hardened, Google SSO live in prod, NoralOS delegated identity shipped. Zero engine coupling. |
| `api/db/models.py` — `organizations`, `users`, `api_keys`, `*_configurations` | Becomes the tenancy layer. See §4. |
| `api/db/reports_client.py`, `api/routes/reports.py`, `api/services/reports/` | 700 lines, the dashboard backend. |
| `api/services/storage.py`, `api/tasks/s3_upload.py`, `api/routes/s3_signed_url.py`, MinIO service | Recording storage is already solved — this is why "download to MinIO" is the cheap option. |
| `api/services/n8n_*.py`, `api/routes/n8n_integration.py`, `integration_webhooks` | Post-call automation. Live on n8n Cloud. |
| `api/routes/organization*.py`, `api/services/quota_service.py`, `api/services/pricing/` | Usage + billing rollups. |
| `ui/` shell: layout, auth pages, settings, reports, recordings, `ui/src/components/ui` | Branded chrome survives; the workflow editor inside it does not. |
| `deploy/noral/`, nginx, postgres/redis/minio compose services | |

### RE-POINT

| Path | Change |
|---|---|
| `api/routes/knowledge_base.py` (436) | CRUD stays; storage/indexing calls go to ElevenLabs KB. Drop local chunking. |
| `api/routes/tool.py` (487) + `tools` table | Our tool definitions become ElevenLabs webhook/client/MCP tool registrations. |
| `api/routes/workflow_recording.py` (352) | Recording source becomes the ElevenLabs conversation audio endpoint. |
| `api/services/configuration/registry.py` | Provider catalog collapses from 15+ AI providers to: ElevenLabs (+ optional BYO-LLM). Large simplification. |

---

## 4. Data model — you already have most of it

Do **not** create the tables in the prompt verbatim. Map them:

| Prompt table | Existing table | Gap to close |
|---|---|---|
| `client` | `organizations` | add `elevenlabs_workspace_id`, `name`, `status`. Quota, `price_per_second_usd`, usage cycles, configurations, api_keys all already there. |
| `client_api_credential` | `external_credentials` + `organization_configurations` | verify encryption-at-rest; add ElevenLabs key type. |
| `managed_agent` | `workflows` | keep `workflow_uuid`, `organization_id`, `name`, `status`; add `elevenlabs_agent_id`, `current_version`. Drop `workflow_definition` JSON + `workflow_definitions` version table (ElevenLabs owns config + branches). |
| `phone_number` | `telephony_phone_numbers` | add `elevenlabs_phone_number_id`; drop 7-provider config. |
| `conversation` | **`workflow_runs`** | Already has `recording_url`, `transcript_url`, `storage_backend` (s3/minio), `usage_info`, `cost_info`, `initial_context`, `gathered_context`, `logs`, `annotations`, `call_type` (inbound/outbound), `campaign_id`, indexed `gathered_context->>'call_id'`. Add `elevenlabs_conversation_id` (unique, for webhook idempotency), `sentiment`, `duration_seconds`. |
| `conversation_transcript` | `workflow_runs.transcript_url` | Decide: keep pointer-to-object-store, or add a JSONB column for queryable turns. Recommend JSONB — you'll want to search transcripts. |
| `extracted_data` | `workflow_runs.gathered_context` (JSON) | Already exists; ElevenLabs data-collection results land here. |
| `usage_rollup` | `organization_usage_cycles` | Already exists, feeds `organization_usage.py` + quota service. |

Net: **one migration adding ~6 columns and dropping ~10 tables**, not a greenfield schema.

---

## 5. Working-tree hygiene (blocker for a destructive phase)

Before Phase 1 touches anything:

- 13 modified files uncommitted (`n8n_integration`, `workflow`, `configuration/registry`, `pipecat/tts_one_shot`, `global_node`, SDK typed nodes, UI settings/GenericNode).
- Untracked new work not on any branch: `api/services/workflow/workflow_generator.py` + 2 test files, `ui/src/app/integrations/`, `ui/src/components/VoicePreviewButton.tsx`, `ui/src/components/flow/renderer/PromptPreview.tsx`, `ui/src/components/settings/tabs/IntegrationsTab.tsx`.
- **~12 cloud-sync conflict duplicates** (`… 2.md`, `… 2.tsx`, `ui/package 2.json`, `ui/package-lock 3.json`). These are noise and one of them is a duplicate `package-lock` — delete before building.
- Currently on `claude/workflow-hard-delete` with unmerged commit `38b9ecb`.

Decide per item: land, shelve, or discard. Ironically, much of the untracked work (workflow generator, prompt preview, typed nodes) is in the code slated for deletion.

---

## 6. Proposed change to the phase plan — strangler, not big-bang

The prompt's Phase 1 deletes the engine before anything replaces it. Given `voice.noral.ai` is live on this engine, that means an outage window of unknown length with no proof ElevenLabs covers the workload. Recommended reordering:

| New phase | Work | Why it moved |
|---|---|---|
| **0** | This document + decisions in §7 | unchanged |
| **1** *(was 2)* | `api/services/elevenlabs/` client + tenancy columns + credential storage. Additive migration. Engine untouched, prod unaffected. | Build before destroy |
| **2** *(was 4, partially)* | Webhook ingestion into `workflow_runs`/`conversation` + MinIO recording pull. Dual-source: engine calls and ElevenLabs calls both land in one table. | Proves the reporting path works before deleting the one that feeds it |
| **3** | Agent editor UI, new route (`/agents`), alongside the old `/workflow` editor. **Move one real client onto ElevenLabs end-to-end: create agent → attach number → real inbound + outbound call → row in dashboard with playable recording + transcript.** | This is the go/no-go gate. If ElevenLabs can't express a client's behavior, you find out here — while the engine still exists. |
| **4** | Migrate remaining clients agent-by-agent. | |
| **5 — DESTRUCTIVE** *(was 1)* | Delete the engine, telephony providers, workflow graph, campaigns, embed, looptalk, coturn. Drop dead tables. Slim compose + deps. | Now safe: nothing is running on it |
| **6** | Dashboards + usage/billing on the consolidated data. | |
| **7** | Tenant-isolation hardening + RBAC; automated cross-client leakage test. | |
| **8** | Cleanup, docs, CI, prod deploy of the slim stack. | |

Cost of the reorder: you carry dead engine code ~3 phases longer. Benefit: no outage, and the irreversible delete happens only after the replacement is proven with a real call from a real client.

---

## 7. Decisions needed before Phase 1

### 7.1 Synthflow — the elephant

You currently run **91 agents across 14 subaccounts on Synthflow**, a managed voice platform with the same shape as the ElevenLabs target: agents, actions/tools, knowledge bases, phone numbers, call analytics, simulation suites, and **subaccounts that already provide the per-client isolation** this plan wants from ElevenLabs Enterprise workspaces.

Building an ElevenLabs control plane means one of:
- **(a)** migrate 91 agents off Synthflow to ElevenLabs;
- **(b)** run two managed platforms and build the control plane over both (the integration layer becomes an abstraction over providers, materially more work);
- **(c)** build the same control plane over **Synthflow** instead — same architecture, same "rent the engine" principle, no agent migration.

The prompt assumes ElevenLabs without addressing this. **Everything downstream depends on the answer**, so it should be settled now. If there's a reason ElevenLabs beats Synthflow (voice quality, latency, pricing, API maturity, contract), say so and I'll proceed as written — the architecture doesn't change, only the vendor behind `api/services/<vendor>/`.

### 7.2 NoralOS coupling — a shipped, live integration

The `noralai.noralvoice` plugin (32 tools, live on `agent.noral.ai`) and the typed SDKs (`sdk/python`, `sdk/typescript`) let NoralOS agents **author workflow graphs**. `api/mcp_server/tools/` is `create_workflow`, `save_workflow`, `get_workflow_code`, `node_types` — all graph-shaped.

Deleting workflows breaks that plugin in production. Options:
- Re-express the plugin over ElevenLabs agents (prompt + tools + KB) — smaller, arguably better surface;
- Freeze the plugin until Phase 5, then cut both repos together;
- Keep a translation shim (not recommended — it re-introduces graph semantics).

Needs a coordinated cross-repo plan. Flagging it because the prompt doesn't mention NoralOS at all.

### 7.3 The three questions the prompt asked

| Question | My recommendation |
|---|---|
| **Tenancy** | Design the schema for workspace-per-client now (`organizations.elevenlabs_workspace_id` + per-client credential), run MVP on a single workspace. Zero-cost future-proofing since the credential lookup is the same code path either way. Confirm whether you're on Enterprise / Consolidated Billing. |
| **Client access** | Noral-internal only for v1. Adding client login later is an RBAC change, not an architecture change. |
| **Recording storage** | Download to MinIO. You already have the bucket, the upload task, and signed-URL routes — it's the cheap option here, and it decouples retention from the vendor. |

---

## 8. What I need from you to start Phase 1

1. **Synthflow vs ElevenLabs** (§7.1) — blocking.
2. **Accept or reject the phase reorder** (§6) — blocking for sequencing.
3. **NoralOS plugin plan** (§7.2) — can be deferred to Phase 3, but not past it.
4. Confirm tenancy / client-access / storage defaults (§7.3).
5. An ElevenLabs API key with workspace access, in env (never in repo).
6. Disposition on the uncommitted working tree (§5).

No files have been changed.
