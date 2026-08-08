# Control Plane — Looping Execution Prompt

Hand this to a Claude Code session to execute [control-plane-build-plan.md](./control-plane-build-plan.md) continuously.

**To run it:**

```bash
/loop Execute docs/design/control-plane-loop-prompt.md
```

Omit an interval and the model paces itself. It reads its own progress file each iteration, so it survives context resets and can be stopped and resumed at any point.

---

## Everything below this line is the prompt

---

You are executing the NoralVoice → ElevenLabs control plane migration, defined in `docs/design/control-plane-build-plan.md`. That plan is the specification. This document is the operating procedure. Where they conflict, the plan wins on *what* to build and this document wins on *how to run the loop*.

### Context in one paragraph

This repo is a fork of Dograh — a self-hosted Pipecat voice engine currently serving live calls at `voice.noral.ai`. It is being reduced to a thin control plane over ElevenLabs Agents: agent CRUD, webhook ingestion, dashboards, auth, per-client isolation. Ninety-one agents across 14 client subaccounts currently run on Synthflow and migrate later. The engine is not deleted until a real client is proven live on the replacement. Read the plan before your first action, and re-read the relevant section at the start of each phase.

---

## 1. Standing authority

You may do these without asking, repeatedly, until a stop condition fires:

- Read anything in the repo. Run read-only commands against the repo, the test DB, and public API documentation.
- Write and modify code, tests, migrations, and docs on the current working branch.
- Create branches named `feat/control-plane-phase-N`. Commit as often as is useful.
- Run the test suite, linters, type checks, and the local dev stack.
- Query the Synthflow MCP with **read-only** tools (`list_*`, `get_*`, `search_*`) for inventory work.
- Fetch and read ElevenLabs public API documentation.
- Update your own progress file (§4).
- Move to the next task, and to the next phase, without checking in — **except** where §2 says otherwise.

**This relaxes one rule in the plan.** The plan says "written summary at the end of each phase, then wait for go-ahead." Under this loop you flow between phases without waiting, because the user has asked for continuous execution. The §2 hard stops are not relaxed and never become optional.

---

## 2. HARD STOPS — read this section every iteration

When any of these is reached: **stop the loop, write a clear report of what is done and what is needed, and end the iteration.** Do not work around it, do not do "the safe part" of it, do not proceed on an assumption.

| # | Stop | Why | To resume |
|---|---|---|---|
| **S1** | **Entering any API key or credential value** | You must never handle credential material. The ElevenLabs key is entered by a human through the platform UI. | Human enters the key; you verify only that authentication succeeds. |
| **S2** | **The Phase 1a data migration step** | It rewrites LLM/TTS keys that are serving production calls. Plan Do-NOT: never run it before a verified backup. | Human confirms a verified, restorable backup exists. |
| **S3** | **Any action against a real client's agent, phone number, or workspace** | Phase 4 cuts over live business lines. A misconfigured number silently keeps serving its old destination. | Explicit per-client authorization, with the rollback written first. |
| **S4** | **Phase 5, in whole or in part** | Irreversible deletion of ~50k lines. Requires Phase 4 acceptance, a 7-day soak, and explicit written go-ahead. | All three conditions met and stated by a human. |
| **S5** | **Any regulated client** (§6 of the plan: Aspire Medspa, Academy Prep, housing authority, Affordable Solar / Energy Harbor, campaign calling) | Compliance confirmations are outstanding. | Confirmations landed and recorded in the plan. |
| **S6** | **A capability gap with no viable mapping** (Phase 0.6) | This may invalidate the vendor choice. It is a decision, not a workaround. | Human decides: accept the gap, build around it, or reconsider. |
| **S7** | **Same task fails acceptance twice in a row** | Two failures means the approach is wrong, not that the third attempt will work. | Human input on approach. |
| **S8** | **Any destructive action a phase does not explicitly authorize** | Deleting files, dropping tables, force-pushing, touching other branches or worktrees. | Explicit authorization naming the specific action. |
| **S9** | **Production deploy** | `voice.noral.ai` serves live calls. | Explicit go-ahead. |

If you are unsure whether something is a stop, **it is a stop.**

---

## 3. Per-iteration protocol

Each iteration, in order:

1. **Load state.** Read `docs/design/control-plane-progress.md` (§4). If it does not exist, create it from the template and start at Phase 0.6.
2. **Re-read §2 of this document.** Every iteration. Not from memory.
3. **Select the next task** — the first unchecked item in the current phase. One task per iteration unless tasks are trivially small and related.
4. **Check the gates.** Does this task touch a §2 stop? If yes → stop and report. If it touches a real client, a credential, or production, assume yes.
5. **Re-read the plan section** governing this phase.
6. **Do the work.** Follow repo conventions. Write tests for every new backend capability.
7. **Verify, and show the verification.** Run the command that proves the claim and put its output in your report. A sweep-style task (removal, rename, audit) is not complete while its verifying `grep` still returns hits. Never write "done" without evidence.
8. **Commit.** One logical change per commit. Message explains *why*, not just what.
9. **Update the progress file** — tick the task, record the commit SHA, note anything learned that changes later phases.
10. **Report** in three lines: what you did, what proved it, what is next.
11. **Continue** to the next task, or end the iteration if a phase boundary or stop was reached.

### Failure handling

- Test fails → fix it. Do not delete or skip the test. Deleting a test to go green is a plan-level Do-NOT.
- Blocked on one task → do every other task in the phase that isn't blocked, then report the blocker specifically.
- Something in the plan turns out to be wrong → **say so, fix the plan document, commit that fix, and continue.** The plan is a living document; three of its findings were already corrected by evidence. Do not silently deviate from it, and do not follow it off a cliff.

---

## 4. State file

Maintain `docs/design/control-plane-progress.md`. It is the loop's memory — assume your context will be lost and this file is all that survives.

```markdown
# Control Plane — Progress

**Current phase:** 0.6
**Branch:** feat/control-plane-phase-0
**Last updated:** <ISO date> · <commit sha>
**Blocked on:** <nothing | which S-number and what is needed>

## Phase 0.6 — Capability spike
- [ ] Verify ElevenLabs feature mapping for each §4.3 row
- [ ] Check retention / privacy controls
- [ ] Prototype Cal.com booking in n8n
- [ ] Prototype SMS opt-in in n8n
- [ ] Reliability baseline from workflow_runs
- [ ] Per-agent complexity profile (91 agents) → ranked order + gate client
- [ ] Set BYO-LLM p95 latency budget

## Findings that change the plan
<!-- anything discovered that later phases must account for -->

## Decisions needed from a human
<!-- accumulates while the loop runs; cleared when answered -->
```

Extend it with each phase's task list as you reach that phase, taken from the plan's phase section. Keep completed phases in the file — the history matters.

---

## 5. Work queue

Detail lives in the plan; this is the sequence and the gates.

| Phase | Autonomy | Gate |
|---|---|---|
| **0.6** Capability spike | **Full** — read-only against docs and APIs | S6 if a gap has no mapping |
| **1a** Credentials + encryption | **Full except the migration step** | **S2** at the data migration; **S1** at key entry |
| **1b** ElevenLabs client + tenancy | **Full** — build against mocks; live verification needs S1 | — |
| **2** Conversation ingestion | **Full** — including the reconciliation job and its kill-the-endpoint test | — |
| **3** Agent editor + reference agent | **Full up to the reference agent** | **S3** before the real gate client |
| **4** Migrate clients | **None** | **S3** per client; **S5** for regulated ones |
| **5** Remove the engine | **None** | **S4** |
| **6** Dashboards | Full, once data exists | — |
| **7** Isolation + RBAC | Full | — |
| **8** Cleanup + deploy | Full except deploy | **S9** |

**Realistic scope for this loop: Phase 0.6 through Phase 3's reference agent.** That is a large amount of genuine work. Everything past it is human-gated by design, not by caution.

---

## 6. Standing constraints

Carried from the plan; they apply to every task in every phase.

- **No real-time media path.** No Pipecat, WebRTC, coturn, audio streaming, turn detection. If you are writing one, you have misread the task.
- **No hardcoded ElevenLabs key** in env, code, or config. The only credential in env is `CREDENTIAL_ENCRYPTION_KEY`.
- **No secret in any log, exception message, URL, query string, response body, or client bundle.** Reads expose `last_four` only.
- **No ambient ElevenLabs credential.** No module-level client, no default workspace, no env fallback. Every call resolves from the calling organization or fails.
- **No plaintext credential written to the database** after Phase 1a — including in migrations and fixtures.
- **Org-scope every query.** No endpoint returns data across a client boundary.
- **Never force-push. Never touch other branches or worktrees.**
- **BYO-LLM stays capped** at 2 clients and a stated latency budget.

---

## 7. Environment

```bash
# Tests — always source .env.test so tests never touch the dev/prod DB
source venv/bin/activate && set -a && source api/.env.test && set +a && python -m pytest api/tests/...

# Diagnostics against the dev DB
source venv/bin/activate && set -a && source api/.env && set +a && python -m api.services.admin_utils.local_exec

# Infra
./scripts/start_services_dev.sh
```

Known repo facts, already verified — do not re-derive:

- Alembic has a **single head**, `e4a2b9d3f715`. A naive static scan reports four; it misses tuple `down_revision`s. Use `alembic heads`.
- **PyNaCl 1.6.2** is already a direct dependency (`api/requirements.txt:21`). No new crypto package is needed.
- There is **no encryption anywhere** in `api/` today, despite a comment on `external_credentials` claiming otherwise.
- `api/services/crypto/` and `api/tests/test_credential_encryption.py` may already exist, uncommitted, from an earlier start. Review before rewriting.
- `loguru.error` does **not** accept `exc_info=True`. Use `logger.opt(exception=True).error` and `{e!r}`, or a `{...}` in the message raises a `KeyError` that masks the real exception.

---

## 8. Loop termination

End the loop and report when any of these is true:

- **Phase 3's reference agent passes** — the loop's realistic completion point.
- **A §2 hard stop fires.** Report which one and exactly what is needed to resume.
- **The work queue for the current phase is empty and the next phase is human-gated.**
- **Two consecutive iterations produce no verifiable progress.** Stop and say why rather than spinning.

Your final report states: phases completed, commits made, what was verified and how, what is blocked and on whom, and the single next action.

---

## 9. Anti-patterns

Things that would make this loop worse than not running it:

- Claiming a phase complete without running its acceptance criteria.
- Reporting a sweep as done while the verifying command still returns hits.
- Deleting or skipping a failing test.
- Treating a §2 stop as a suggestion, or splitting a gated task to do "the safe half."
- Building the ElevenLabs client before the Phase 0.6 spike confirms the feature mapping — that is the exact ordering error the plan was rebuilt to fix.
- Re-deriving facts already recorded in §7 or the plan.
- Writing a summary that says work happened without saying what proves it.
- Continuing past a genuine blocker by inventing an assumption.
