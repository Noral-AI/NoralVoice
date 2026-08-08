# Phase 0.6 — Capability Spike

Acceptance artifact for [control-plane-build-plan.md](./control-plane-build-plan.md) §7 Phase 0.6.
Read-only against both platforms. **No product code is written in this phase.**

| # | Task | Status |
|---|---|---|
| 1 | Verify ElevenLabs feature mapping for each §4.3 row | ✅ 2026-08-08 |
| 2 | Check retention / privacy controls | ⬜ |
| 3 | Prototype Cal.com booking in n8n | ⬜ |
| 4 | Prototype SMS opt-in in n8n | ⬜ |
| 5 | Reliability baseline from `workflow_runs` | ⬜ |
| 6 | Per-agent complexity profile (91 agents) → ranked order + gate client | ⬜ |
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
