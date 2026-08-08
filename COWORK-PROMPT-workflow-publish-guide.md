# Cowork prompt — update the NoralVoice user guide to prevent silent publish failures

Paste the block below into a fresh Cowork session pointed at the NoralVoice repo (`/Users/quentin/Documents/NORALAI/NoralVoice`). It is self-contained.

---

## Context

NoralVoice is the Dograh-derived voice-agent platform. End users build conversational agents as React-Flow graphs in the workflow editor (nodes = agent steps, edges = transitions between them) and then click **Publish** to make a new draft version go live for inbound/outbound calls.

The published version is what the runtime actually executes. Drafts are not executed. A workflow that "looks finished in the editor" can be silently stuck on an old published version if the draft fails validation.

## The incident this prompt is responding to

A real customer-facing workflow ("Ethos Inbound Agent Test", workflow id 7 in prod) had been built out into 19 nodes / 13 edges in the editor. The author clicked **Publish** repeatedly across two days and assumed it had gone live. Every inbound call kept being served by the original empty 1-node v1 stub — callers heard "Hi" and nothing else. The author had no idea why.

Root cause when we investigated in prod:

1. The server was correctly returning `422` from `POST /api/v1/workflow/{id}/publish` because the draft had **two classes of validation problems**:
   - **8 out of 13 edges had empty `data.label` and empty `data.condition` strings.** Every transition must have both: a short label and a natural-language condition that tells the agent when to follow that path.
   - **2 nodes were orphaned** (an `agentNode` "Booking Confirmation" and an `endCall` "Booked Close") — laid out visually under "Pitch Intro Call" but with no incoming edge wired up. Agent nodes and end-call nodes must have at least one incoming edge.
2. **The UI was not surfacing the 422 response in a way the user noticed.** Pressing Publish appeared to do nothing — no toast, no inline marker on the offending edges/nodes, no banner. So the user kept retrying instead of fixing the problem.

The runtime symptom: every inbound call still hit definition v1 (the empty starter), the agent said "Hi", the graph had zero edges out of "Start Call", the caller hung up. Six runs in a row showed `nodes_visited: ["start call"]` with `call_disposition: user_hangup`. Two of those even had `user_speech` tags — the caller spoke, the agent had nowhere to go.

We fixed the data in prod (filled the 8 blank edge labels/conditions and wired the 2 orphans into the "appointment scheduled" branch); v2 is now published. But this is a class of mistake that any author building a non-trivial workflow will hit, and the docs do not currently warn them about it.

## What you are doing

Update the NoralVoice user guide so a workflow author understands these rules **before** they hit them, and can self-diagnose **if** they hit them.

The Mintlify docs live under `docs/`. The most relevant existing pages are:
- `docs/voice-agent/editing-a-workflow.mdx` — where new content most likely belongs.
- `docs/core-concepts/workflows-and-agents.mdx` — conceptual framing.
- `docs/core-concepts/how-dograh-works.mdx` — already mentions publishing.

Read those first to match tone and structure.

## What to add to the guide

Cover these points clearly. You can split across pages or add a single new page (e.g. `docs/voice-agent/publishing-a-workflow.mdx`) — whichever fits the existing IA best. Cross-link from the editing-a-workflow page.

1. **The draft/published model.** Saving the editor does not change what callers hear. The runtime only ever runs the *published* version. To make changes go live, you must press **Publish**. A workflow can have at most one draft and one published version at a time; publishing promotes the draft and archives the previous published version.

2. **Publish is gated by validation.** The server will refuse to publish an invalid graph. The two most common ways a graph is invalid:
   - **Every edge needs a label and a condition.** When you draw a line from one node to another, fill in both fields in the side panel — a short label (shown on the edge in the editor) and a natural-language condition (what the agent should look for to take this path, e.g. "the caller has agreed to schedule a call"). Empty strings will block publish.
   - **Every agent node and end-call node needs at least one incoming edge.** If you place a node and forget to draw an arrow into it, validation will fail. (Global nodes, webhook nodes, and QA nodes are sidecars and do not need incoming flow edges.)

3. **What the agent does with labels vs. conditions.** The label is for you, in the editor. The condition is what the LLM uses at runtime to decide whether to follow that edge. Vague conditions ("continue") work for straight-through transitions but for branching nodes (e.g. "Qualify: Bottleneck & Goals" branching into "Good Fit" vs. "Unclear Fit") the condition is what determines which branch the call takes. Encourage authors to write conditions that describe **what just happened in the conversation**, not what the next node will do.

4. **What "stuck on the old version" looks like.** A clear troubleshooting box: if you press Publish but callers are still hearing the old behavior — or in the worst case, the agent says one line and then goes silent — check whether your draft is actually published. The workflow versions panel shows version number and status; the live version is the one marked `published`.

5. **The orphan-node trap.** When you copy/paste a chunk of a flow or sketch out terminal states ("Booked Close", "Not Booked Close") visually before wiring them up, validation will flag them as soon as you try to publish. Suggest authors finish wiring before publishing — or, if they want to commit intermediate progress, that's fine, drafts persist indefinitely.

6. **A short worked example.** Walk through a 3-node toy workflow (Start → Qualify → End Call), point at the label/condition fields on each edge, and show what a valid published state looks like in the versions panel.

Keep the tone consistent with the rest of `docs/voice-agent/`: practical, screenshot-friendly placeholders are fine (mark them `TODO: screenshot` rather than inventing image paths). Avoid jargon like "React Flow DTO" or "WorkflowGraph" — those are implementation details. Use the user-facing terms the editor exposes ("node", "edge", "label", "condition", "publish", "draft", "version").

## Out of scope for this prompt

- Do not change validation behavior in the API. The 422 gate is correct.
- Do not change the editor UI. Surfacing the 422 to the user clearly (toast + per-edge red marker + "fix and republish" affordance) is a real bug, but it is a code change, not a docs change. Mention in your handoff that it exists; do not attempt it.
- Do not touch the prod database or any running workflow. Docs only.

## Deliverable

One PR against `main` that adds the docs content described above, with a clear title like `docs(voice-agent): explain workflow publishing, validation rules, and the draft model`. Include in the PR description: a one-paragraph summary of the customer incident that motivated the change (paraphrased — no customer names beyond "Ethos test workflow" which is internal), and which pages were touched.
