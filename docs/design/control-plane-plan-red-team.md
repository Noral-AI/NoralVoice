# Red team — Control Plane Build Plan v2

Adversarial review of [control-plane-build-plan.md](./control-plane-build-plan.md) @ `4adda9a`.
Most of these are flaws in my own plan. Ordered by severity.

---

## CRITICAL

### C1 — Nobody has checked whether ElevenLabs can do what the 91 agents do

The plan's entire premise is that ElevenLabs can express the behavior currently running on Synthflow and Dograh. **No phase verifies this.** There is no inventory of what those 91 agents actually use — custom tools, CRM integrations, warm transfer logic, data collection schemas, multi-language, per-agent LLM choice, conditional branching, voicemail handling.

If 20% of agents depend on a capability ElevenLabs lacks, the plan discovers it in **Phase 4**, after the credential system, the API client, ingestion, and a new UI are all built. That is the worst possible place to find out.

**Fix:** a capability-parity spike before Phase 1b. Export the 91 agent configs, classify the features in use, map each to an ElevenLabs feature, and produce a gap list. This is a few days of work that de-risks the entire program. It should arguably run before *any* build phase.

### C2 — The "go/no-go gate" fires after the money is spent

Phase 3 is described as the gate where "we find out if ElevenLabs can't express a client's behavior — while the engine still exists." True, but by then 1a + 1b + 2 are built. The gate protects the *deletion*, not the *investment*.

Worse: the plan says "one real client" without saying **which**. Migrating the simplest client proves nothing. A gate you're likely to pass is not a gate.

**Fix:** name the client, and make it the hardest one — most tools, most integrations, highest call volume. Combine with C1: the spike picks the client by evidence.

### C3 — Single-workspace MVP makes the per-client credential design theater

§7 permits an MVP on one ElevenLabs workspace. §11.2 claims the org-scoped credential means "no global key to unpick later." **These contradict each other.** In the MVP, every organization's credential row holds the *same* workspace key. Tenant-scoped resolution is real code doing nothing.

The security consequence is worse than the tidiness one: all clients' agents, phone numbers, conversations, and **recordings** are commingled in one vendor workspace. Anyone with that key — our staff, a leaked CI secret, an attacker — reads every client's call data. For a business whose product is *managing agents on behalf of clients*, that is a disclosure risk the plan waves through in one sentence.

**Fix:** either confirm Enterprise/Consolidated Billing before Phase 1b and go workspace-per-client from the start, or state the MVP's blast radius explicitly, cap it at named low-sensitivity clients, and make Enterprise a hard prerequisite for onboarding client #2.

---

## HIGH

### H1 — The encryption phase is justified with a threat model it may not address

§11.1 leans on the 2026-05-17 Postgres compromise to justify Phase 1a. But §11.7 admits app-level encryption doesn't help an attacker with host access — **and a host-level attacker gets `CREDENTIAL_ENCRYPTION_KEY` out of the environment along with everything else.**

Encryption is still worth doing: it protects `pg_dump` output, backups, replicas, and a DB-only compromise. But if the May 17 attacker had host access, this control would not have prevented it. The plan should say which of those it was rather than implying the fix matches the incident.

**Fix:** state the actual 5/17 access path. Justify 1a on backups/dumps/replicas, which is true regardless. If host compromise is the real threat, the honest answer is KMS — or accepting the residual risk explicitly.

### H2 — There is no cost model, so the business case is unexamined

No phase compares ElevenLabs per-minute cost against current all-in cost. The plan builds usage/billing rollups in Phase 6 and calls for reconciliation — which is where you'd *discover* the unit economics, long after they could change the decision.

**Fix:** price a representative month against ElevenLabs' rate card during the C1 spike. If the margin inverts, that's a Phase 0 decision, not a Phase 6 surprise.

### H3 — No behavioral regression testing for migrated agents

Phase 4 migrates 91 agents with acceptance "verify a live call." One call proves the agent answers, not that it behaves equivalently — same qualification questions, same extraction fields, same transfer conditions, same refusals.

LoopTalk (agent-vs-agent testing) exists today and is deleted in Phase 5, but the plan never uses it to build an equivalence baseline before migrating.

**Fix:** capture a behavioral baseline per agent before cutover (recorded scenarios + expected extractions), replay against the ElevenLabs version, diff. ElevenLabs simulation suites can carry this post-migration.

### H4 — Webhook-only ingestion loses calls silently

Phase 2 is idempotent on `vendor_conversation_id`, which handles *duplicate* delivery. It has no answer for *missed* delivery. If our endpoint is down, mid-deploy, or the vendor drops a webhook, those calls happen and never appear in our database — and nothing detects it. Reporting and billing quietly under-count.

**Fix:** a periodic reconciliation job that lists conversations from the vendor API for the last N hours and backfills anything missing. Idempotency already makes this safe.

### H5 — Phase 4 has no rollback, and the point of no return is undefined

A client is migrated; calls degrade. What happens? The engine still exists until Phase 5, so rollback is *possible* — but the procedure isn't written, and after Phase 5 it's gone forever. The plan never names the moment the decision becomes irreversible.

**Fix:** a per-client rollback runbook for Phase 4 (revert the Twilio number config, re-enable the workflow), and an explicit "point of no return" declaration gating Phase 5 with a soak period.

### H6 — Phase 5 orphans historical call data

`workflow_runs` has FKs to `workflows`, `workflow_definitions`, `campaigns`, `queued_runs` (`api/db/models.py:453,457,492,494`). Phase 5 drops three of those four tables. Historical conversations — with recordings clients may be entitled to — would carry dangling references, and any reporting query joining them breaks.

**Fix:** decide retention explicitly before Phase 5. Denormalize what reporting needs onto `workflow_runs`, null the dead FKs, and verify a pre-migration call still resolves end-to-end afterward.

---

## MEDIUM

### M1 — "ElevenLabs agents are prompt+tools shaped, not graph shaped" is my claim, not a verified fact

This assertion drives the largest scope decision in the plan: delete ~20k lines of graph editor and replace it with a form. It is stated flatly in the recon and never verified against current ElevenLabs API documentation, and my knowledge has a cutoff. If ElevenLabs supports conversational flows or multi-agent handoff graphs, the migration mapping — and the UI scope — changes materially.

**Fix:** verify against live API docs during the C1 spike. Treat the current recon claim as provisional.

### M2 — The BYO-LLM escape valve is not free, and quietly contradicts the prime directive

"If a client needs behavior the vendor can't express, use BYO-LLM" is presented as a costless hatch. It isn't: BYO-LLM means we operate an inference endpoint **inside the latency-critical voice path**, with its own uptime, scaling, and p95 budget. That is infrastructure we run — the thing the prime directive forbids.

**Fix:** bound it. BYO-LLM is acceptable for N clients under a stated latency budget; beyond that it's a signal the vendor choice is wrong. Without a bound it becomes the default answer to every gap found in C1.

### M3 — Vendor concentration is designed in, with no exit

§8 forbids a provider abstraction — correct for simplicity, but the plan also deletes the ability to run voice in-house, permanently. A price rise, ToS change, or outage has no mitigation.

The irony is load-bearing: **this migration exists because you're leaving Synthflow.** Vendor switches demonstrably happen here, and the plan is optimized to make the next one maximally expensive.

**Fix:** don't build an abstraction. Do write down the exit cost and keep the control plane's own data (conversations, transcripts, recordings in MinIO) complete enough that switching means rewriting one directory, not reconstructing history.

### M4 — "Reliability" is the stated motivation but never measured

The mission opens with "it was unreliable and calls failed." No phase establishes a failure-rate baseline or sets a post-migration target. The definition of done — "zero real-time voice infrastructure" — can be fully satisfied while calls are *less* reliable.

It's also harder to measure than it looks: `WorkflowRunState` is only `initialized / running / completed` (`api/enums.py:66`) with no failure state, so a baseline needs a proxy (initialized-never-completed) and some care.

**Fix:** compute the baseline now, while the engine still runs. Put a reliability threshold in the Phase 4 acceptance criteria.

### M5 — Number cutover risk is understated

"Cut the number over, verify a live call" describes a customer-facing telephony change on a client's main business line, 91 times. Misconfiguration means missed inbound calls — and per the phone-number gotcha already documented in this project, a number whose config doesn't get updated silently keeps serving the old destination.

**Fix:** per-client cutover runbook, low-traffic window, verify inbound *and* outbound before declaring done, monitor for missed calls in the following hours.

### M6 — Compliance and data residency are absent

Recordings and transcripts move to a US vendor. `api/services/configuration/registry.py:495` already exposes an EU residency base URL "for GDPR / HIPAA / regional compliance" — someone previously thought about this. The plan says nothing about client contracts, DPAs, residency, or retention obligations.

**Fix:** confirm no client has a residency or retention clause that the move breaks, before Phase 4.

### M7 — Phase 5's acceptance criteria are gameable

"Test suite green (minus deleted-feature tests, which you remove)" — deleting the failing tests is precisely how breakage hides. And "prod still serving calls throughout" is muddled: by Phase 5 prod serves via ElevenLabs, so the criterion doesn't test what it sounds like it tests.

**Fix:** record the test count and coverage before and after, justify each removed test file against a deleted feature, and replace the prod criterion with a live end-to-end call verified after the deletion deploys.

### M8 — The `workflow_runs` reuse has a cost I glossed over

I argued "extend, don't duplicate" and it's still right. But the honest tradeoff: the table keeps dead FK columns, engine-era enums (`mode`, `storage_backend`), and JSON blobs shaped for the old pipeline. We inherit a legacy table rather than a clean `conversation` model, and every future reader has to know which columns are live.

**Fix:** accept it, but schedule a column-level cleanup inside Phase 5 rather than letting it accrete silently.

---

## LOW

### L1 — Phase 1a blocks capability validation for no reason
Encryption and a live-data migration are risky work sequenced *ahead* of the thing that could kill the project (C1). Capability validation needs only a throwaway key in a dev environment. Security work should not sit on the critical path of a feasibility question.

### L2 — No effort or timeline estimate anywhere
~50k lines deleted, 91 agents migrated, a new UI built, and the plan expresses only sequence. Phase 4 alone is plausibly weeks. Sequence without magnitude can't be resourced or prioritized.

### L3 — The shelf branch is local-only
`shelf/pre-control-plane-2026-08-08` @ `312c0e0` exists on one machine. It is the only copy of the pre-migration working tree.

### L4 — `.claude/` was added to `.gitignore` unilaterally
Reasonable (it holds 18 embedded worktrees), but it's a repo-wide convention change made in passing during a docs commit.

---

## Summary

| Severity | Count | Theme |
|---|---|---|
| Critical | 3 | The plan never validates its central assumption, and its gate fires too late to matter |
| High | 6 | Missing cost model, regression testing, ingestion backstop, rollback, data retention; overstated security justification |
| Medium | 8 | Unverified scope claim, uncapped escape valve, no exit story, unmeasured reliability, compliance silence |
| Low | 4 | Sequencing, estimation, hygiene |

**The single most important change:** insert a capability-parity spike (C1) before any build phase, and let its findings choose the Phase 3 gate client (C2) and price the migration (H2). Everything else is repair work on a plan that is currently building infrastructure for a conclusion nobody has tested.
