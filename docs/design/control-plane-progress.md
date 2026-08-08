# Control Plane — Progress

**Current phase:** 0.6
**Branch:** feat/control-plane-phase-0
**Last updated:** 2026-08-08 · (see below)
**Blocked on:** nothing

Working artifact: [control-plane-phase-0.6-capability-spike.md](./control-plane-phase-0.6-capability-spike.md)

## Phase 0.6 — Capability spike
- [x] Verify ElevenLabs feature mapping for each §4.3 row — *capability spike §1* — `<sha-1>`
- [ ] Check retention / privacy controls
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

## Decisions needed from a human

**D1 · Phase 3 editor scope — do we author ElevenLabs workflow graphs?** (plan §12.7, from F1)
Blocks the Phase 3 editor build only; nothing before it. My read: **defer** — ship the flat editor, and let task 6's complexity profile say how many of the 91 agents actually branch before committing to graph-authoring UI. Not urgent this iteration.

**D2 · Confirm the data-collection cap for our plan tier** (plan §12.8, from F2). 25 vs 40. In-product check, one minute, sets the threshold task 6 measures against.
