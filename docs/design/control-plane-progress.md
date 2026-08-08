# Control Plane — Progress

> ## ⚠️ SCOPE CHANGE — 2026-08-08, from the user, direct quote
> **"i do not need all the agent copied from synthflow. i just need a working platform"**
>
> **Phase 0.6 ends here. Phase 4's mass migration is descoped.** The goal is a working control plane, not a 91-agent port. Task 6's data already supported this: only 13 of 91 agents have a number, and the rest are dead demos.
>
> **What this cancels:**
> - Phase 4 as "migrate 91 agents" — gone. Agents get authored fresh in our UI.
> - Phase 0.6 tasks 3, 4, 5 (n8n prototypes, reliability baseline) — these existed to de-risk a migration that is no longer happening. Left unchecked and unblocked, not silently ticked.
> - §8 behavioural equivalence, baseline capture/replay/diff — no agent is being recreated, so there is nothing to diff against.
> - The D5 gate-client question — moot.
>
> **What this leaves — the build path to §15:**
> **1a** credentials + encryption → **1b** ElevenLabs client + tenancy → **2** conversation ingestion → **3** agent editor → **6** dashboards → **7** isolation/RBAC → **8** deploy.
>
> **Assumption I am proceeding on:** "working platform" means plan §15's definition of done, minus the migration — an operator logs in, creates and publishes an agent from our UI, a number takes and makes calls on ElevenLabs, and every call lands in our dashboard with recording, transcript and extracted fields. Say so if you meant something narrower.
>
> Phases 5 (engine deletion) and 9 remain human-gated exactly as before — descoping the migration does **not** unlock deleting the engine, which still serves live calls.

**Current phase:** 1a (was 0.6)
**Branch:** feat/control-plane-phase-0
**Last updated:** 2026-08-08 — per-task commit SHAs are recorded against each task below; this header no longer chases its own SHA.
**Blocked on:** nothing phase-wide. Tasks 3 and 4 blocked on B1 (n8n access + authority); task 5 waiting on Q1. Tasks 6 and 7 are clear and are next.

Working artifact: [control-plane-phase-0.6-capability-spike.md](./control-plane-phase-0.6-capability-spike.md)

## Phase 0.6 — Capability spike
- [x] Verify ElevenLabs feature mapping for each §4.3 row — *capability spike §1* — `5d09f0d`
- [x] Check retention / privacy controls — *capability spike §2* — `e0d815a`
- [~] Prototype Cal.com booking in n8n — **DESCOPED** (was blocked on B1; migration cancelled)
- [~] Prototype SMS opt-in in n8n — **DESCOPED** (was blocked on B1; migration cancelled)
- [~] Reliability baseline from workflow_runs — **DESCOPED** (existed to gate migrated agents against a baseline)
- [x] Per-agent complexity profile (91 agents) → ranked order + gate client — *capability spike §3* — `a46b21f`
- [~] Set BYO-LLM p95 latency budget — **DEFERRED** to whenever BYO-LLM is actually reached (§9.2 cap still stands)

## Phase 1a — Credentials + encryption (current)
Design: plan §10. Six steps.
- [x] Review the uncommitted crypto work from an earlier start — complete and correct, matched §10.3 exactly; 35 tests passing. Committed rather than rewritten.
- [x] Crypto module — PyNaCl SecretBox, `v1:` envelope (§10.3) — `687e464`
- [x] Transparent encrypt/decrypt in the credential client, legacy plaintext passthrough — `cccf922`
- [x] Schema migration — `provider`, `last_four`, `rotated_at` — `53a6bab` (head now `a1c4e7b920f3`, still single)
- [x] Set/rotate/revoke routes — `188e26e` — `PUT|GET|DELETE /api/v1/credentials/providers/{provider}`
- [x] Settings UI — key entered by a human, never by me (**S1**) — `1447b9e` — Settings → Voice provider
- [x] Seal/unseal seam for `user_configurations` + `organization_configurations` — `1447b9e` — **the migration's prerequisite**
- [ ] Data migration of existing plaintext — **S2 HARD STOP, needs a verified backup** ⬅ only thing left in 1a

**The migration is now safe to write, and still gated.** All three §10.4 scopes have a working seal/unseal seam, so encrypting their rows will not break reads. What remains is the migration itself plus S2 clearance (a verified, restorable backup) — those LLM/TTS keys serve production calls.

`organization_configurations` is sealed **selectively** — only `TELEPHONY_CONFIGURATION`, `TWILIO_CONFIGURATION`, `LANGFUSE_CREDENTIALS`. The table is a general key/value store; sealing disposition mappings would make them opaque to queries that inspect them. The migration must respect the same key list (`SECRET_BEARING_KEYS` in `api/db/organization_configuration_client.py`).

**Test state:** 109 passing across the credential suite (`test_provider_credentials`, `test_credential_encryption`, `test_custom_tools`, `test_integration_webhooks`, `test_masked_key_rejection`). No Postgres needed — these are in-process with the DB client mocked.

**Two pre-existing problems in this environment, neither mine:**
1. `test_noralai_voice.py` and `test_noralai_voice_typed.py` fail at *collection* — `ModuleNotFoundError: noralai_voice`. The SDK at `sdk/python` is not installed in the venv. Any full-suite run aborts on these two before running anything.
2. Full-suite collection takes **~30 minutes**. Run targeted files, not `pytest api/tests/`.

**Where the seam is:** writes seal in `WebhookCredentialClient.create_credential` / `update_credential`; reads unseal in `credential_auth.build_auth_header`. Stored shape is `{"__enc__": "v1:…"}`. Legacy plaintext rows read correctly with no key configured, so this is deployable before the data migration and safe against a part-migrated table.

**Note for the S2 step:** §10.4 scopes the data migration to `external_credentials.credential_data` **plus** the LLM/TTS keys in `user_configurations.configuration` and `organization_configurations.value`. Those latter two are *not* covered by the seal/unseal seam above — they have their own read paths, which need the same treatment before their rows are encrypted, or global LLM breaks. Not yet built.

## Findings that change the plan

**F1 · ElevenLabs has a graph editor — M1's premise was wrong.** (task 1)
Agent Workflows: subagent / tool / agent-transfer / transfer-to-number / end-call nodes, LLM-condition edges, per-node analytics. Plan updated: new §4.5, M1 row, Phase 5 step 3 rationale corrected, Phase 3 scope flagged. Phase 5 deletion still stands — those files author *Dograh's* graph shape, which stops running.

**F2 · Data collection is capped at 25 items per agent** (40 Trial/Enterprise). (task 1)
159 extractors / 91 agents averages 1.7, but an agent over 25 cannot be one ElevenLabs agent — it must split across workflow nodes or chained agents. **Task 6 must report max-extractors-on-any-one-agent**, not just the total. Plan §4.3 and Phase 0.6 step 5 updated.

**F3 · No enum/choice type in data collection.** (task 1)
Synthflow `choice` extractors become prompt-constrained Strings — behaviourally equivalent but prompt-enforced, not schema-enforced. These are the likeliest to drift in the §8 replay diff; over-sample them when capturing baselines.

**F4 · Pre-call fetch is real, and Phase 2 grows by one endpoint.** (task 1)
The conversation initiation webhook fires during Twilio's dial period and returns `dynamic_variables` + overrides. Risk drops Medium → Low. But it sits *in the call path*: it must be fast and **fail open**. Its URL is workspace-scoped, so one endpoint serves all clients and resolves org from `agent_id` — same path as the post-call webhook. Plan Phase 2 updated.

**F5 · Most privacy levers are Enterprise-only.** (task 2)
BAA, workspace-wide ZRM and data residency all sit behind the same tier as consolidated billing. Standard storage is US. Residency is not a flag — it is a separate isolated environment with its own portal, API endpoint and workspace, agents recreated via API. Plan §5.3, §6 and §12.9 updated.

**F6 · Our tier does get per-agent retention control — and the default is 2 years.** (task 2)
Configurable per agent, transcripts and audio separately, `-1` unlimited, **`0` immediate deletion**. Two years of medspa transcripts on a shared workspace is not a posture anyone chose; it is the default. Retention value belongs in the per-client config built in Phase 1b. Vendor retention only needs to outlive ingestion + the Phase 2 reconciliation window.

**F7 · The BAA question §6 asked is answered: yes, Enterprise-only, ZRM mandatory.** (task 2)
Aspire Medspa now has exactly three branches and no fourth — buy Enterprise+BAA+ZRM, document that the content is not PHI, or leave it on Synthflow (which re-opens Phase 5's deletion premise). Does not block Phases 0.6–3; sharpens an S5 gate that already blocked Phase 4 for this client.

**F8 · Under ZRM, post-call webhooks still fire.** (task 2)
So the §9.3 data-ownership position survives ZRM: vendor stores nothing, we store everything. This is a genuinely good outcome *if* per-agent ZRM is available to us — see D4 for the two unknowns.

## Blockers

**B1 · n8n prototypes (tasks 3 and 4) cannot proceed from this session.** Two independent reasons:

1. **No access.** `N8N_ENABLED`, `N8N_API_KEY` and `N8N_BASE_URL` are all absent or empty in `api/.env`; only `api/.env.example` carries n8n keys, and its `N8N_BASE_URL` is the **stale** `https://automation.noral.ai`. The live instance moved to n8n Cloud (`noralai.app.n8n.cloud`) in May. Anyone picking these tasks up from the example file will point at the wrong host.
2. **Outside the loop's authority even with a key.** Building the workflows means creating persistent configuration in an external SaaS. §1 grants read-only external access; standing up live n8n workflows is not covered, and it is exactly the class of action that needs an explicit go-ahead.

**To unblock:** either a human builds the two prototypes, or authorizes this loop to create workflows in the n8n Cloud workspace and provides access through the normal config path (never pasted into chat — S1).

**Not fatal to the phase.** Both gaps were already confirmed real in task 1 (no native SMS tool, no native calendar tool), so the *mapping* question is settled; what is unproven is the *build*. Tasks 5–7 are unaffected and proceed.

## Open questions I can answer myself, but should flag

**Q1 · Which database does the reliability baseline come from?** (task 5)
`workflow_runs` on the **dev** DB will not have meaningful volume; the runs that matter are on `voice.noral.ai`. Two sub-questions before I start: (a) is the intended source prod, and if so does read-only prod DB access fall inside §1's "read-only commands against the repo, the test DB"? I read it as *not* granted and will ask rather than assume. (b) The 91 migrating agents run on **Synthflow**, not on this engine — so an engine-derived baseline measures a different population than the one being migrated. Worth a sentence in the plan on what §8.3 is actually comparing.

**Confirmed while checking:** `WorkflowRunState` has exactly `INITIALIZED` / `RUNNING` / `COMPLETED` (`api/enums.py:66-70`) — no failure state, exactly as plan §7 Phase 0.6 step 4 says. The initialized-never-completed proxy is the right approach and needs no re-derivation.

## Decisions needed from a human

**D1 · Phase 3 editor scope — do we author ElevenLabs workflow graphs?** (plan §12.7, from F1)
Blocks the Phase 3 editor build only; nothing before it. My read: **defer** — ship the flat editor, and let task 6's complexity profile say how many of the 91 agents actually branch before committing to graph-authoring UI. Not urgent this iteration.

**D2 · Confirm the data-collection cap for our plan tier** (plan §12.8, from F2). 25 vs 40. In-product check, one minute, sets the threshold task 6 measures against.

**D3 · Re-open Enterprise on compliance grounds?** (plan §12.9, from F5/F7) — *the one worth reading first.*
§5.1 evaluated Enterprise on billing and correctly said no. Enterprise is also the only route to a BAA, workspace-enforced ZRM and non-US residency. That is a different question than the one that was answered, and the §6 portfolio is what makes it live. Blocks Phase 4 for Aspire Medspa only (already S5-gated) — nothing before it.

**D4 · Two ZRM unknowns, both settle empirically in Phase 1b** (plan §12.10, from F8).
(a) Is per-agent ZRM available below Enterprise? The docs state a tier for the workspace-wide version and not for the per-agent one. (b) Does `post_call_audio` still fire under ZRM? If not, ZRM and §15's "playable recording" are mutually exclusive. Both need a key, so neither blocks now — but neither may be promised to a client before it is tested.
