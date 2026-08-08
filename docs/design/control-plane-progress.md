# Control Plane — Progress

**Current phase:** 1a–7 built. Remaining work is human-gated.
**Branch:** feat/control-plane-phase-0
**Last updated:** 2026-08-08

> ## Scope, as directed
> **"i do not need all the agent copied from synthflow. i just need a working platform"** (2026-08-08)
>
> Phase 4's mass migration is cancelled. Agents are authored fresh in the new UI. Task 6's data supported this independently: only 13 of 91 Synthflow agents have a phone number; the rest are dead demos.

---

## What exists now

A Noral operator can log in, enter an ElevenLabs key, create and edit agents from our own UI, and see every call land with transcript, extracted fields and a playable recording — with each client boundary enforced in our own data and credential paths.

| Phase | State | Commits |
|---|---|---|
| **0.6** Capability spike | Tasks 1, 2, 6 done; 3–5, 7 descoped with the migration | `5d09f0d` `e0d815a` `a46b21f` |
| **1a** Credentials + encryption | Built except the S2-gated data migration | `687e464` `cccf922` `53a6bab` `188e26e` `1447b9e` |
| **1b** ElevenLabs client + tenancy | Done | `813475e` |
| **2** Conversation ingestion | Done — webhooks, reconciliation, recordings | `2297f0f` `fdf7370` |
| **3** Agent editor | Done (flat editor; graph authoring deferred, see D1) | `873bed0` |
| **6** Dashboards | Done — calls list, detail, usage rollups | `873bed0` |
| **7** Isolation + RBAC | Isolation tests done; role checks not built | `873bed0` |
| **8** Cleanup + deploy | Nav, env docs done; **deploy is S9-gated** | this commit |

**Test state:** 203 passing across the control-plane suites. UI typecheck clean.

### Endpoints

```
PUT|GET|DELETE  /api/v1/credentials/providers/{provider}
GET|POST        /api/v1/agents/
GET|PATCH|DELETE /api/v1/agents/{agent_id}
GET             /api/v1/calls/            (list)
GET             /api/v1/calls/usage       (rollups)
GET             /api/v1/calls/{run_id}    (transcript, fields, recording)
POST            /api/v1/elevenlabs/post-call
POST            /api/v1/elevenlabs/conversation-initiation
```

### UI

`Settings → Voice provider` (enter the key) · `/agents` (author) · `/calls` (observe)

---

## Blocked on a human

**S2 · The Phase 1a data migration.** The only unbuilt part of 1a. It rewrites the LLM/TTS keys serving live calls at voice.noral.ai, so it needs a verified, restorable backup first. Everything it depends on is ready: all three §10.4 scopes (`external_credentials`, `user_configurations`, `organization_configurations`) have a working seal/unseal seam, so encrypting their rows will not break reads.

When writing it, respect `SECRET_BEARING_KEYS` in `api/db/organization_configuration_client.py` — `organization_configurations` is sealed **selectively**, and encrypting every row would make disposition mappings opaque to the queries that read them.

**S9 · Production deploy.** `voice.noral.ai` serves live calls.

**S1 · The ElevenLabs key.** Entered by a human at Settings → Voice provider. A key was pasted into a chat transcript on 2026-08-08 and should be treated as compromised and rotated.

---

## Decisions still open

**D1 · Does our editor author ElevenLabs workflow graphs?** (plan §12.7) Currently ships flat — prompt, first message, name. ElevenLabs has a visual graph editor (§4.5), so a branching agent cannot be expressed in our UI today. Deferred deliberately: with the migration cancelled, agents are authored fresh, and most new agents start flat.

**D2 · Confirm the data-collection cap for our tier.** 25 items, or 40 on Trial/Enterprise.

**D3 · Re-open Enterprise on compliance grounds?** (plan §12.9) §5.1 evaluated it on billing and correctly said no. It is also the only route to a BAA, workspace-enforced ZRM and non-US residency.

**D4 · Two ZRM unknowns, settled empirically once a key is installed.** Is per-agent ZRM available below Enterprise? Does `post_call_audio` still fire under it? If not, ZRM and playable recordings are mutually exclusive.

---

## Findings that changed the plan

**F1 · ElevenLabs has a graph editor.** M1's premise was wrong. Phase 5's deletion still stands, but because those files author *Dograh's* graph shape, not because no counterpart exists.

**F2 · Data collection caps at 25 items per agent.** Max observed on any live Synthflow agent is 17, so nothing needs splitting.

**F3 · No enum/choice type.** Synthflow `choice` extractors become prompt-constrained strings — prompt-enforced, not schema-enforced.

**F4 · Pre-call fetch is real.** The conversation initiation webhook fires during Twilio's dial period. It sits *in the call path*, so our endpoint fails open.

**F5 · Most privacy levers are Enterprise-only.** BAA, workspace ZRM, data residency. Standard storage is US.

**F6 · Vendor retention defaults to two years.** Agents are now created with 30-day transcript / 7-day audio retention instead.

**F7 · BAA is Enterprise-only, ZRM mandatory.** Aspire Medspa has three branches and no fourth.

**F8 · Post-call webhooks still fire under ZRM.** Our data-ownership position survives it.

**F9 · Only 13 of 91 Synthflow agents have a phone number.** The other 78 are demos (*Tampa Bay Rays*, *FEMA*, *BMW of Sarasota*). Phase 4 was sized against a population ~7× the real one.

**F10 · All 91 agents live in the parent workspace.** The 14 client subaccounts are empty and unreadable with this credential, so §5.4's subaccount mapping describes who the clients are, not where their data lives.

**F11 · `info_extractor_ccnumber` is live on Ice Machine – Michelle**, a refund flow — not the medspa. Card digits are going into transcripts today, independent of this migration.

**F12 · Calendly is in use alongside Cal.com**, via a custom function on a THA agent.

---

## Environment traps

1. Full-suite collection takes **~30 minutes** and then aborts: `test_noralai_voice.py` and `test_noralai_voice_typed.py` cannot import `noralai_voice` (the SDK is not installed in the venv). **Run targeted files.**
2. The generated API client needs a running backend at `127.0.0.1:8000`. New routes carry `sdk_expose` but the client has not been regenerated; the new UI pages call through the configured fetch client meanwhile.
3. `ui/.next/` accumulates macOS-style duplicate files (`routes.d 2.ts`) that produce phantom typecheck errors. `rm -rf ui/.next` clears them; the directory is gitignored.
