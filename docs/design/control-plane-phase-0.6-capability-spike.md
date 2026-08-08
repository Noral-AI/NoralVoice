# Phase 0.6 — Capability Spike

Acceptance artifact for [control-plane-build-plan.md](./control-plane-build-plan.md) §7 Phase 0.6.
Read-only against both platforms. **No product code is written in this phase.**

| # | Task | Status |
|---|---|---|
| 1 | Verify ElevenLabs feature mapping for each §4.3 row | ✅ 2026-08-08 |
| 2 | Check retention / privacy controls | ✅ 2026-08-08 |
| 3 | Prototype Cal.com booking in n8n | ⬜ |
| 4 | Prototype SMS opt-in in n8n | ⬜ |
| 5 | Reliability baseline from `workflow_runs` | ⬜ |
| 6 | Per-agent complexity profile (91 agents) → ranked order + gate client | ✅ 2026-08-08 |
| 7 | Set BYO-LLM p95 latency budget | ⬜ |

---

## 1. Feature mapping — verified against live docs

Every row of plan §4.3 checked against ElevenLabs documentation on 2026-08-08. **No gap requires an S6 stop.** Two rows got *cheaper* than the plan assumed; one new hard constraint appeared; one plan claim was wrong.

### 1.1 Row-by-row

| §4.3 row | Count | Verified mapping | Risk (was → now) |
|---|---|---|---|
| Data extraction | ~105 | **Data collection.** Types: String, Boolean, Integer, Number. Each item has a unique **Identifier** — the same concept as the Synthflow extractor identifier, so the §8 equivalence contract carries over 1:1. Extracted values are delivered via post-call webhook. | Low → **Low, with a cap** (§1.2) |
| Cold transfer | ~40 | **`transfer_to_number` system tool.** Three modes: conference (default, warm), **blind (cold — what we need)**, SIP REFER. Blind transfer is **Twilio-native-integration only**, which we have. Conditions are a *natural-language description of the circumstances* evaluated by the LLM — the same shape as the Synthflow trigger, including the Spanish-language one. | Low–medium → **Low** |
| SMS | 5 | **Confirmed: no native SMS tool.** The full system-tool list is end call, language detection, agent transfer, transfer to number, skip turn, play keypad touch tone, voicemail detection, update state. Mapping stands: webhook tool → n8n → Twilio. | Medium — **unchanged** |
| Cal.com booking | 5 | **Confirmed: no native calendar/booking tool.** Mapping stands: webhook tool → n8n → Cal.com, and we rebuild slot windows, days-ahead, per-day slot caps, timezone and first-available-date ourselves. | Highest — **unchanged** |
| Pre-call HTTP fetch | 4 | **A genuine pre-call fetch exists.** See §1.3. | Medium → **Low** |

### 1.2 New hard constraint — data collection is capped per agent

Documented limit: **25 data-collection items per agent**, rising to 40 on Trial and Enterprise plans.

We have 159 extractors across 91 agents — ~1.7 average, so this is comfortable in aggregate. It is not comfortable if the distribution is skewed, and extractor-heavy qualification agents are exactly the kind that skew. **Any single agent carrying more than 25 extractors cannot be recreated as one ElevenLabs agent.**

- This is now an explicit output of task 6: the complexity profile must report **max extractors on any one agent**, not just the total.
- If an agent exceeds the cap, the workaround is real but not free — split it across workflow nodes (§1.4) or across chained agents via agent transfer. That is a migration-cost item for Phase 4, not a blocker for the vendor choice.
- Confirm the ceiling that applies to *our* plan tier before task 6 concludes; the docs pair "Trial and Enterprise" at 40, which is unusual enough to be worth confirming in-product.

**Also:** there is **no enum/choice type**. Synthflow's `choice` extractors become String with the permitted values constrained in the prompt. Behaviourally equivalent, but it is prompt-enforced rather than schema-enforced — so choice extractors are the ones most likely to drift in the §8 replay diff, and should be over-sampled when capturing baselines.

### 1.3 Pre-call fetch — confirmed, better than assumed

The plan flagged "verify ElevenLabs supports a genuine *pre-call* fetch that populates variables before the first turn." It does.

**Conversation initiation webhook (inbound Twilio):** on an inbound call ElevenLabs calls our endpoint with `caller_id`, `agent_id`, `called_number`, `call_sid`. We return `dynamic_variables` (must contain every variable the agent declares) plus optional `conversation_config_override`. It fires **during Twilio's dial period, in parallel with the connection tone**, so the data is in place by the first turn without adding latency the caller perceives. Auth is via request headers sourced from the ElevenLabs secrets manager. Enabled per agent under the agent's Security tab; the URL is configured once at workspace level.

This covers the two `run_action_before_call_start: true` actions on inbound agents. On outbound, we initiate the call ourselves and pass `dynamic_variables` in the initiation payload — we can fetch whatever we need first, in our own code, with no vendor mechanism required. **Both directions are covered.**

Two consequences to carry forward:

- **Phase 2 gains a second inbound endpoint.** Not just the post-call webhook — an initiation webhook too, which is latency-sensitive in a way the post-call one is not. It must be fast, and it must fail open (a timeout should still let the call connect with default variables rather than dropping it).
- **The initiation webhook URL is workspace-scoped**, so on our single workspace (§5) one endpoint serves every client. It receives `agent_id` and `called_number`, so it resolves the client the same way the post-call webhook does. Same org-resolution path, same mandatory scoping — worth building once and sharing.

### 1.4 M1 resolved — and the plan's premise was wrong

M1 was "unverified 'no graph counterpart' claim." **Verified: ElevenLabs has a graph counterpart.**

**Agent Workflows** is a visual conversation-flow editor: subagent nodes (change agent behaviour at a point in the flow), tool nodes (a dedicated execution point that *guarantees* the tool is called, unlike a tool offered to the LLM), agent-transfer nodes, transfer-to-number nodes and end-call nodes, connected by edges with **LLM-evaluated natural-language conditions**. The analytics dashboard overlays per-node entry counts, average dwell time, terminations and edge distribution onto the graph.

Corrections this forces:

1. **The Phase 5 step 3 deletion still stands, but not for the stated reason.** We delete `api/mcp_server/` and the typed graph builders because they author *Dograh's* graph shape, which no longer runs anything — not because graphs have no counterpart. The counterpart exists and is the vendor's.
2. **Phase 3's editor scope needs a decision.** An agent editor limited to prompt/voice/tools cannot express a branching agent. Either the editor covers workflows too (materially more UI than the plan budgets), or branching agents are authored in the ElevenLabs dashboard and we own only the flat surface. This is a scope decision for a human — logged in the progress file, not decided here.
3. **A migration lever the plan did not have.** Tool nodes guarantee execution, which is a better fit for deterministic Synthflow actions than a prompt-offered tool. And workflow nodes are the natural way to split an agent that busts the 25-item extractor cap (§1.2).

### 1.5 Verification commands

```
WebFetch elevenlabs.io/docs/agents-platform/customization/tools/system-tools/transfer-to-number
WebFetch elevenlabs.io/docs/agents-platform/customization/tools
WebFetch elevenlabs.io/docs/agents-platform/customization/agent-analysis/data-collection
WebFetch elevenlabs.io/docs/agents-platform/customization/personalization/dynamic-variables
WebFetch elevenlabs.io/docs/agents-platform/customization/personalization/twilio-personalization
WebSearch  agent-workflows (elevenlabs.io)
```

Docs are a claim, not a proof. Every mapping above is re-proven behaviourally by the Phase 3 reference agent, which exercises all five action types on a real call.

---

## 2. Retention and privacy controls

Plan §5.3 set this task because, with one shared workspace, "minimising vendor-held data is the main lever we still have." The finding: **most of that lever is behind the Enterprise tier we decided not to buy** — but the one control that matters most for day-to-day data minimisation is not.

### 2.1 What is available on our tier

**Configurable retention, per agent, transcripts and audio separately.**

| Setting | Value |
|---|---|
| Default retention | **2 years** |
| Configurable | Per agent, in days |
| Transcripts vs audio | Configured **separately** |
| Unlimited | `-1` |
| **Immediate deletion** | **`0`** |
| Retroactive | Optional — reducing the period can delete existing data immediately |

Two years by default is a long time to hold a medspa's call transcripts on a shared workspace. **This should be turned down deliberately per client rather than left at the default**, and the value belongs in the per-client config we build in Phase 1b, not in someone's memory.

### 2.2 What is behind Enterprise

Four things we might have wanted all sit behind the same paywall:

| Control | Tier | Consequence for us |
|---|---|---|
| **BAA execution** | Enterprise only | See §2.4 — this is the Aspire Medspa question, now answered |
| **Workspace-wide Zero Retention Mode** | Enterprise | Per-agent ZRM may still be reachable — §2.3 |
| **Data residency** (EU / India / Singapore) | Enterprise | Standard storage is **US**. Note `api/services/configuration/registry.py:495` already exposes an EU residency endpoint — someone anticipated a need we cannot currently meet. Residency also means a *separate isolated environment*: distinct portal, API endpoint and workspace, with agents recreated via API. Not a flag — a second deployment. |
| **Consolidated billing** | Enterprise | Already known (§5.1) — the original reason we are not on Enterprise |

**This changes the shape of the Enterprise question.** §5 evaluated Enterprise purely on billing and concluded 14 subscriptions cost more than one pooled plan. That analysis was correct and is unchanged — but it was answering a narrower question than the one now on the table. Enterprise is not just consolidated billing; it is *also* the only route to a BAA, to workspace-enforced ZRM, and to non-US residency. Given the §6 portfolio, that is a materially different trade. **Flagged for a human (D3); not re-decided here.**

### 2.3 Per-agent Zero Retention Mode — the important unknown

There are two ZRM docs: a workspace-level one explicitly marked Enterprise, and a **per-agent** one that **does not state a tier**. If per-agent ZRM is available below Enterprise it is the single most valuable privacy control on the table, so its tier is worth confirming in-product early.

Under ZRM: no recordings stored, no transcripts or PII-bearing metadata logged or stored post-call. Critically — **post-call webhooks still fire, and are documented as the way to retrieve call information under ZRM.** That is precisely our Phase 2 ingestion path, so the §9.3 data-ownership position survives ZRM intact: ElevenLabs stores nothing, we store everything, in our own Postgres and MinIO.

If per-agent ZRM is available to us, it substantially collapses the §5.3 residual for any agent that has it on — commingling is far less alarming when there is nothing vendor-side to commingle.

**The open question that must be answered before relying on it:** ZRM says no recordings are stored, and the audio arrives via a *separate* `post_call_audio` webhook. **The docs do not say whether `post_call_audio` still fires under ZRM.** If it does, we get the ideal configuration. If it does not, ZRM means no recordings at all for that agent — which collides with §15's "playable recording" for every call. This is cheap to settle empirically once a key exists (Phase 1b), and it must be settled before ZRM is promised to any client. Logged as D4.

### 2.4 The compliance answers §6 asked for

§6 asked "Confirm whether ElevenLabs will sign a BAA if medspa call content warrants one." **Answered: yes — but only on Enterprise, and only with ZRM engaged.**

Stated requirements for HIPAA-eligible use: Enterprise tier **and** an executed BAA **and** Zero Retention Mode active **and** only approved LLMs, with compliance responsibility resting on us as the customer.

So for **Aspire Medspa**, the decision tree is now concrete and has no third branch:

1. Buy Enterprise, execute a BAA, run that agent under ZRM — and accept §2.3's recording question, since ZRM is mandatory here, not optional.
2. Establish that the medspa's call content does not constitute PHI, document that determination, and migrate it as an ordinary client.
3. Leave Aspire Medspa on Synthflow — which means the engine's replacement is not universal, and §7 Phase 5's deletion premise needs re-examining.

This does **not** block Phase 0.6, and it does not block Phases 1a–3, none of which touch a client. It sharpens an existing §6 gate that already blocks Phase 4 for this client under **S5**. Regulated clients were already scheduled last; that ordering now has a specific reason and a specific cost attached.

### 2.5 Recommended default posture

Pending the decisions above, the posture to build toward — cheap, available on our tier today, and strictly better than the default:

- **Never leave retention at 2 years.** Set it per client, deliberately, as part of onboarding.
- **Transcripts and audio get separate values.** Audio is the higher-risk artifact and usually needs the shorter life.
- **Our copy is the durable one.** Vendor retention only needs to outlive successful ingestion plus reconciliation lag (Phase 2's backfill window), not the reporting horizon. Once the reconciliation job is proven, vendor retention can be short — days, not years.
- **`info_extractor_ccnumber` (§6) does not get recreated** without an explicit decision. Capturing card digits into a transcript on a shared workspace is the worst combination of facts in this document.

### 2.6 Verification commands

```
WebSearch  zero retention mode / retention / HIPAA (elevenlabs.io)
WebFetch elevenlabs.io/docs/eleven-agents/customization/privacy/retention
WebFetch elevenlabs.io/docs/eleven-agents/customization/privacy/zrm
WebFetch elevenlabs.io/docs/eleven-agents/legal/hipaa
WebFetch elevenlabs.io/docs/agents-platform/workflows/post-call-webhooks
WebFetch elevenlabs.io/docs/overview/administration/data-residency
```

---

## 3. Per-agent complexity profile

Pulled read-only from the Synthflow MCP on 2026-08-08. **This task changes the shape of Phase 4 more than anything else in the spike.** The headline number "91 agents" is real, and it is not the migration workload.

### 3.1 Only 13 of 91 agents have a phone number

There are exactly **14 phone numbers in the entire account**. Every one sits in the parent workspace.

| | Count |
|---|---|
| Agents total | **91** |
| Agents with a phone number | **13** |
| Agents with no number at all | **78** |
| Phone numbers in the account | **14** |

An agent with no number cannot take an inbound call. The 78 are demos, pitches and abandoned builds, and the names say so plainly: *Tampa Bay Rays*, *BMW of Sarasota*, *FEMA*, *Central Bank*, *Regal Kia*, *USF Health – Pharmacy*, *Kamala Harris*, *My Inbound Assistant*, *Doctor's office*.

Plan §11 calls Phase 4 "the long pole — weeks, 91 agents × baseline, recreate, diff, cutover, monitor." **That estimate is built on a population roughly seven times larger than the one that actually carries traffic.** The real cutover workload is thirteen agents, of which several are explicitly test builds. Phase 4 should be re-scoped around the live cohort, with a separate, much cheaper decision about what to do with the 78 — most plausibly "do not migrate; archive."

**Before acting on this, confirm the numbers are the whole story.** An agent could plausibly be driven by outbound API without owning a number. That is worth one query against call history per agent before anything is archived — cheap, and it converts this from a strong inference into a fact.

### 3.2 The live cohort, profiled

Actions counted per agent via `get_agent_actions`. "Extractors" counts `info_extractor_*` items — the ones that consume the 25-item data-collection budget (§1.2).

| Agent | Type | Number | Actions | Notes |
|---|---|---|---|---|
| **THA Parking – Sophia** | inbound | +18138197187 | **17** | Most complex live agent. Transfers to +18133419109. Has `preferred_language`. |
| **THA – Danielle** | inbound | +18138197200 | **14** | Transfers to the parking line — agent-to-agent over PSTN. SMS opt-in with TCPA language. |
| **Ice Machine – Michelle** | inbound | +18132127608 | **11** | Refund flow. **Carries `info_extractor_ccnumber`** — see §3.5. |
| Appointment Setter – FL Tiny Homes | inbound | +18135131598 | 5 | Booking + email + reason-for-call. |
| THA – OB Request Routing | outbound | +18132957551 | 1 | Single action: **`calendly_availability`** — see §3.6. |
| Heal Pros | inbound | +18139023777 | **0** | Live number, no actions. |
| Cedric's Personal Assistant | inbound | +18137615700 | **0** | Live number, no actions. |
| THA – Tenant Callback | outbound | +18138197200 | — | Shares the main THA number. |
| V2 – Testing – THA – Danielle | inbound | +18137337900 | — | Test build on a real number. |
| TESTING – THA Parking – Sophia | inbound | +18134991920 | — | Test build on a real number. |
| Hailey | outbound | +18134991920 | — | Shares the test number. |
| Demo – Jeremey | inbound | +18132957206 | — | On the number labelled "TBRS". |
| Physician Partners DEMO | inbound | *(empty string)* | — | Number field is `""`, not null. |

Sampled from the dormant 78 to bound the maximum: **Aspire Medspa — 0 actions.**

### 3.3 Three findings that make the migration cheaper

1. **Max extractors on any one agent is 17**, against the 25-item cap. F2's constraint is real but **not breached anywhere in the live cohort** — no agent needs splitting across workflow nodes. This was the open question §1.2 raised, and the answer is favourable. (Bounded over the live cohort plus samples, not all 91 — but the 78 dormant agents are not migration targets, and the two sampled carry zero actions.)
2. **Extractors are a shared library, not per-agent definitions.** `info_extractor_name_egKLIhPocv`, `info_extractor_tha_property_Iqi8dWAzIm` and `info_extractor_tenant_name_gHeUi3D7SO` appear with *identical slugs* across different agents. So the 159 actions are a deduplicated pool attached many-to-many, and the §8 equivalence contract is **per slug**, defined once and reused — not 159 × per-agent work.
3. **Several live agents have zero actions.** Heal Pros and Cedric's Personal Assistant are answering agents with nothing to extract, transfer or book. They are close to trivial to migrate and are the natural first cutover, ahead of anything complex.

Confirmed in passing: `transfer_mode: "cold_transfer"` appears literally in the action definitions, and `transfer_target_type: "single_target"`. That is the blind-transfer mapping from §1.1, verified from the source side rather than inferred.

### 3.4 The structural finding — subaccounts are empty

**All 91 agents live in the parent workspace `1713968079252x…`. Not one lives in a client subaccount.** The 14 subaccounts exist, seven have Twilio active, and they hold no agents. `list_phone_numbers` scoped across the agency tree (`workspace_ids: ['*']`) returns **zero**; the same call scoped to the parent returns all 14 numbers.

Attempting to read into a subaccount fails outright: *"workspace_id … is not accessible for this user."* The MCP credential can enumerate subaccounts but cannot read inside them.

**This contradicts plan §5.4**, which states the 14 subaccounts "map one-to-one to `organizations` rows." As a description of the client list that is a reasonable starting point. As a description of where agent data lives, it is wrong — and Phase 4 would have been built expecting to walk subaccounts. In reality:

- Client attribution runs through **agent naming convention**, and the convention is inconsistent — `THA - Danielle`, `Ethos Residential - Sales Consultation Agent`, `Attorney John A Williams- Holly`, bare `Aspire Medspa`, and unprefixed names like `Leverage` and `Mccants`.
- **Mapping agents to `organizations` is therefore a manual, judgement-based exercise**, not a field copy. It needs a human-reviewed mapping table built once and checked, and it belongs in Phase 4 preparation rather than being discovered mid-cutover.
- Several live agents map to **no subaccount at all** — Heal Pros, Ice Machine, Cedric's Personal Assistant. Either they are clients without a subaccount, or they are internal. Someone needs to say which.

### 3.5 `info_extractor_ccnumber` is live, and it is not the medspa

Plan §6 flagged this extractor without saying where it ran. It is on **Ice Machine – Michelle**, an agent with a live inbound number, alongside `info_extractor_cc_transaction_time` and `info_extractor_refund`. It is a **refund flow** — caller reports a bad transaction, the agent captures card digits and transaction time.

So the concern is PCI-adjacent rather than HIPAA-adjacent, it is **live today**, and it predates this migration. Two things follow, and the first does not wait for the migration:

- Card digits are being captured into call transcripts right now, on the current platform. That is worth someone's attention independent of anything in this plan.
- Per capability spike §2.5 and plan §6, **this extractor does not get recreated on ElevenLabs without an explicit decision.** Migrating it as-is would put card data into a shared-workspace transcript store with a two-year default retention.

### 3.6 Calendly is in use, not just Cal.com

Plan §4.1 records Cal.com as the only configured integration. True at the *integration* level — but `THA - OB Request Routing` carries a `calendly_availability` action: a `custom_function_action_type` doing `GET` against the Calendly API. It is one of the four custom functions §4.2 counted, so the census is consistent; the *conclusion* drawn from it is not.

**Consequence for the blocked n8n work (tasks 3–4):** the booking prototype cannot assume Cal.com. If THA migrates, the n8n booking workflow has to cover **Calendly as well** — a second API with its own availability model. That is additional scope on the capability the plan already rates "Highest" risk.

### 3.7 Ranked migration order

Cheapest and safest first, since the plan's own §7 Phase 4 says unregulated first and the ranking must respect S5.

| Rank | Agent | Why here |
|---|---|---|
| 1 | **Heal Pros** | Live number, zero actions. Nothing to diff beyond "does it answer and sound right." |
| 2 | **Cedric's Personal Assistant** | Same shape. |
| 3 | **Appointment Setter – FL Tiny Homes** | 5 actions, maps to a real subaccount, exercises booking without regulatory weight. |
| 4 | **Ice Machine – Michelle** | 11 actions, genuinely non-trivial — **but drop `ccnumber` first** (§3.5). |
| 5 | **THA – OB Request Routing** | Single action, but pulls in Calendly (§3.6). **Regulated — S5.** |
| 6 | **THA – Danielle** | 14 actions, SMS opt-in, PSTN agent-to-agent transfer. **Regulated — S5.** |
| 7 | **THA Parking – Sophia** | 17 actions, the most complex live agent. **Regulated — S5.** |
| — | The other 78 | **Do not migrate.** Confirm no outbound-only traffic (§3.1), then archive. |

### 3.8 The gate client — the plan's design does not survive contact with the data

Plan §7 Phase 3 step 2 requires the **"hardest real client, chosen by the ranking — not the easiest. Unregulated, per §6."**

Those two requirements now point in opposite directions. **The hardest live client is Tampa Housing Authority by a wide margin** — it owns 6 of the 14 numbers and the three most complex live agents. THA is a housing authority, which is **explicitly S5-regulated**. Every remaining live unregulated agent is trivial: 0, 0, 5 and 11 actions.

There is no live client that is both hard and unregulated. So the gate must be resolved deliberately rather than by following the rule as written:

- **Recommended: `Ice Machine – Michelle` as the gate client**, with `ccnumber` dropped. It is the only live unregulated agent with real complexity — 11 extractors, a refund flow with genuine branching, and a real inbound number. It satisfies "unregulated" strictly and "hardest" as far as the data permits.
- **The alternative is to accept THA as the gate** and pull the housing-authority compliance confirmations forward from Phase 4 to now — inverting §6's "regulated clients migrate last." Defensible, because THA *is* the portfolio, but it is a decision a human makes, not one this loop takes. **This is S5 territory and the loop will not proceed into it.**
- Either way the **reference agent (gate step 1) is unaffected** — it is purpose-built, exercises all five action types, and belongs to no client. It remains the right first proof and this loop can build toward it.

Logged as **D5**.

### 3.9 Verification commands

```
list_subaccounts                      → 14 subaccounts, 7 Twilio-active, 0 agents
list_agents (page_size 100)           → total 91, every workspace_id = parent
list_agents (workspace_id=<Aspire>)   → error: not accessible for this user
list_phone_numbers (workspace_ids=*)  → total 0
list_phone_numbers (current)          → total 14
list_actions (page_size 1)            → total 159; cold_transfer confirmed in situ
list_actions (search "Calendly")      → 1 custom_function_action_type
get_agent_actions × 8                 → per-agent counts in §3.2
```

Read-only throughout — `list_*` and `get_*` only, per loop prompt §1.
