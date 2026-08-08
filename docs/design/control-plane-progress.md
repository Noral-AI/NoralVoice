# Control Plane — Progress

**Current phase:** 0.6
**Branch:** feat/control-plane-phase-0
**Last updated:** 2026-08-08 · 5d09f0d
**Blocked on:** nothing

Working artifact: [control-plane-phase-0.6-capability-spike.md](./control-plane-phase-0.6-capability-spike.md)

## Phase 0.6 — Capability spike
- [x] Verify ElevenLabs feature mapping for each §4.3 row — *capability spike §1* — `5d09f0d`
- [x] Check retention / privacy controls — *capability spike §2* — `<sha-2>`
- [ ] Prototype Cal.com booking in n8n
- [ ] Prototype SMS opt-in in n8n
- [ ] Reliability baseline from workflow_runs
- [ ] Per-agent complexity profile (91 agents) → ranked order + gate client
- [ ] Set BYO-LLM p95 latency budget

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

## Decisions needed from a human

**D1 · Phase 3 editor scope — do we author ElevenLabs workflow graphs?** (plan §12.7, from F1)
Blocks the Phase 3 editor build only; nothing before it. My read: **defer** — ship the flat editor, and let task 6's complexity profile say how many of the 91 agents actually branch before committing to graph-authoring UI. Not urgent this iteration.

**D2 · Confirm the data-collection cap for our plan tier** (plan §12.8, from F2). 25 vs 40. In-product check, one minute, sets the threshold task 6 measures against.

**D3 · Re-open Enterprise on compliance grounds?** (plan §12.9, from F5/F7) — *the one worth reading first.*
§5.1 evaluated Enterprise on billing and correctly said no. Enterprise is also the only route to a BAA, workspace-enforced ZRM and non-US residency. That is a different question than the one that was answered, and the §6 portfolio is what makes it live. Blocks Phase 4 for Aspire Medspa only (already S5-gated) — nothing before it.

**D4 · Two ZRM unknowns, both settle empirically in Phase 1b** (plan §12.10, from F8).
(a) Is per-agent ZRM available below Enterprise? The docs state a tier for the workspace-wide version and not for the per-agent one. (b) Does `post_call_audio` still fire under ZRM? If not, ZRM and §15's "playable recording" are mutually exclusive. Both need a key, so neither blocks now — but neither may be promised to a client before it is tested.
