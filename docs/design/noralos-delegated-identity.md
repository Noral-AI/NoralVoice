# NoralOS-delegated identity for NoralVoice

**Status:** Proposed — pending approval
**Author:** Claude (with Quentin)
**Date:** 2026-05-26
**Repos affected:** `NoralVoice`, `NORALOS/NoralOS-canonical`
**Related memory:** [project_noralvoice_noralos_relationship.md], [project_voice_google_sso_live_2026_05_26.md], [project_workflow_create_mps_dependency.md], [feedback_noralvoice_editor_save_distrust.md]

---

## 1. Summary

Today, a NoralOS agent (e.g. Brooklyn) cannot create a NoralVoice workflow on behalf of a human user such that the workflow appears in that user's voice.noral.ai UI. The plugin authenticates with a shared API key, and NoralVoice stamps the resulting workflow with `user_id = api_key.created_by` — so every workflow Brooklyn creates ends up owned by whichever account minted the API key.

This proposal extends the **existing** NoralOS↔NoralVoice cross-app identity bridge (already live for browser SSO via `NORALOS_SESSION_VALIDATE_URL`) to the **agent-call path**. A NoralOS-issued identity assertion, carried in HTTP headers signed implicitly by a delegation-capable API key, lets NoralVoice resolve the *actual triggering user* and reuse the JIT provisioning path that browser SSO already uses. Workflows then naturally appear in the right user's UI, because the `user_id` on the row matches the `current_user` the UI authenticates as.

Net result: Quentin asks Brooklyn to "create a customer-support callback agent for ACME" → Brooklyn calls the plugin → workflow lands in NoralVoice owned by Quentin → Quentin sees it next time he opens voice.noral.ai. Two new plugin tools (`publish_workflow`, `validate_workflow`) and a workflow-authoring skill close the loop on actually shipping an executable bot.

---

## 2. Goal

Enable this end-to-end flow:

```
User (Quentin) → NoralOS chat → Brooklyn agent → noralai.noralvoice plugin
                                                         │
                                                         ▼
                                                  NoralVoice API
                                                         │
                                                         ▼
                            Workflow row, user_id = Quentin's NoralVoice user
                                                         │
                                                         ▼
                              Quentin opens voice.noral.ai → sees workflow → can dial it
```

**In scope:** auth bridge for agent-call path, two plugin tools to ship a workflow to executable, an authoring skill so agents can produce valid graph JSON without hand-holding.

**Out of scope:** new node types, workflow editor UX changes, MPS-powered template endpoint (broken, see [project_workflow_create_mps_dependency.md]), org-scoped visibility model.

---

## 3. Current state

### Bridge for browser flows (already live)

- Env var `NORALOS_SESSION_VALIDATE_URL` set to `https://agent.noral.ai/api/auth/get-session` in `voice.noral.ai`'s override.yaml.
- [`api/services/auth/noral_sso.py:43`](../../api/services/auth/noral_sso.py) reads it.
- [`api/services/auth/depends.py:44`](../../api/services/auth/depends.py) — when `AUTH_PROVIDER="noral"`, every request first tries `get_user_from_noralos_session(cookie)`.
- On success, [`noral_sso.py:121`](../../api/services/auth/noral_sso.py) calls `db_client.get_or_create_user_by_provider_id(provider_id=f"noralos:{noralos_user_id}")` — JIT provisioning is already in place.
- User table has `provider_id` UNIQUE column ([`api/db/models.py:54`](../../api/db/models.py)).

### Agent-call path (the gap)

- Plugin worker has `ToolRunContext { agentId, companyId, runId }` — no userId, no cookie ([`packages/plugins/noralai-noralvoice/src/worker.ts:366`](../../../NORALOS/NoralOS-canonical/packages/plugins/noralai-noralvoice/src/worker.ts)).
- Plugin already sends attribution headers: `X-Noralos-Actor-Agent-Id`, `X-Noralos-Actor-Company-Id`, `X-Noralos-Run-Id` ([`noralvoice-client.ts:24`](../../../NORALOS/NoralOS-canonical/packages/plugins/noralai-noralvoice/src/noralvoice-client.ts)).
- NoralVoice ignores those headers for auth. `_handle_api_key_auth` ([`depends.py:193`](../../api/services/auth/depends.py)) returns `api_key.created_by` as `current_user`.
- Workflow INSERT stamps `user_id = current_user.id` ([`api/routes/v1/workflow.py:472`](../../api/routes/v1/workflow.py)).
- UI lists workflows where `user_id = current_user.id`. → Quentin never sees Brooklyn's creations.

### What works that we should not break

- Browser SSO flow (Quentin logs into voice.noral.ai with Google → his NoralVoice user is JIT-provisioned/looked-up by `provider_id="noralos:<userId>"`).
- Local-auth fallback (email/password, used in dev/test).
- Existing API key holders (anyone today using an API key directly should keep ownership === `api_key.created_by`).

---

## 4. Architecture decision

### Options considered

| | Mechanism | Trust model | UX | Verdict |
|---|---|---|---|---|
| **A. Per-user API keys** | Each NoralOS user mints a NoralVoice API key, plugin loads it from user config | Per-user secret | Bad — every user must provision | Rejected |
| **B-cookie. Forward NoralOS session cookie** | Plugin re-uses the user's session cookie, NoralVoice validates via existing bridge | Same as browser SSO | Plugin worker has no cookie to forward (no user session) | Doesn't fit |
| **B-header (this proposal)** | Plugin sends user-identity actor headers; NoralVoice trusts them only from delegation-capable API keys; resolves user via existing JIT | Shared secret (API key) + scoped capability | Transparent to user | **Chosen** |
| **B-jwt** | NoralOS mints short-lived JWT per tool call; NoralVoice verifies signature | Asymmetric crypto, no shared-secret trust | Same UX as B-header, more plumbing | Future, if we need to break the shared-secret trust |
| **D. Org-scoped visibility** | UI filters workflows by `organization_id`, not `user_id` | Same as today | Everyone in the org sees everyone's bots | Sidecar concern; can layer on later |

### Why B-header

- **Reuses everything that already exists.** Browser SSO's JIT path, the `provider_id="noralos:<userId>"` mapping, the `users` table schema — all unchanged. We only change *who* triggers the JIT lookup.
- **Same identity for browser + agent.** If Quentin signs into voice.noral.ai (browser) and Brooklyn also creates a workflow for Quentin (agent), both paths land on the same NoralVoice user row. No identity fork.
- **Smallest blast radius.** Existing API key callers keep their current behavior. The new behavior is opt-in per key (`delegation_capable` flag).
- **API key is already the trust boundary.** NoralOS already holds the shared secret. Asserting identity via headers signed implicitly by that key has the same trust assumptions as the existing call.

### What we explicitly are NOT doing

- Not changing the workflow-visibility model (still per-user).
- Not removing the legacy `api_key.created_by` ownership path (existing keys keep working).
- Not adding JWT signing (overkill for v1; B-jwt is a future option if we ever expose API keys outside the trust boundary).
- Not wrapping NoralVoice's broken MPS template endpoint (see [project_workflow_create_mps_dependency.md]). The NoralOS agent IS the LLM — it generates the graph itself.

---

## 5. Wire format

Plugin → NoralVoice request:

```http
POST /api/v1/workflow/create/definition HTTP/1.1
Host: voice.noral.ai
X-API-Key: nv_delegated_<...>                ; existing, must be delegation_capable=true
X-Noralos-Actor-User-Id: ba-user-abc123       ; NEW — required for delegation
X-Noralos-Actor-User-Email: quentin@noral.ai  ; NEW — used on JIT creation to sync email
X-Noralos-Actor-Agent-Id: brooklyn            ; existing, attribution only
X-Noralos-Actor-Company-Id: noral             ; existing, attribution only
X-Noralos-Run-Id: run_xyz                     ; existing, attribution only
Content-Type: application/json

{...workflow JSON...}
```

NoralVoice auth decision tree (proposed):

```
inbound request → has X-API-Key?
├─ no → fall through to cookie/SSO/local auth (unchanged)
└─ yes → look up API key
    ├─ invalid → 401 (unchanged)
    └─ valid →
        ├─ key has delegation_capable=true AND request has Actor-User-Id?
        │   └─ yes → current_user = JIT lookup/create("noralos:<actor_user_id>")
        │           (sync email from Actor-User-Email if present and user is new)
        └─ otherwise → current_user = api_key.created_by  (existing behavior)
```

Key safety properties:

1. An API key with `delegation_capable=false` ignores actor headers (no privilege escalation).
2. An API key with `delegation_capable=true` but no Actor-User-Id falls back to `api_key.created_by` (no orphaned rows).
3. The same JIT path produces the same `users.id` whether a user arrives via browser SSO or delegated assertion (identity continuity).

---

## 6. Build plan (4 PRs)

### PR 1 — NoralOS: triggering user → actor headers

**Repo:** `NoralOS-canonical` → [#130](https://github.com/Noral-AI/NoralOS/pull/130)

Implemented:
- `ToolRunContext` (`packages/plugins/sdk/src/types.ts`): added optional `triggeredByUserId` and `triggeredByUserEmail`.
- `server/src/routes/plugins.ts`: new `resolveTriggeringUser(runId)` helper walks `heartbeat_runs → agent_wakeup_requests → user` and returns `{ userId, userEmail } | null`. The `/tools/execute` route enriches `runContext` before dispatch. Resolution is server-side (callers cannot spoof identity); wrapped in try/catch so a DB hiccup never blocks tool execution.
- `packages/plugins/noralai-noralvoice/src/worker.ts`: `buildActorHeaders` forwards `X-Noralos-Actor-User-Id` and `X-Noralos-Actor-User-Email` when `runCtx.triggeredByUserId` is set.
- Tests: 5/5 actor-headers, 21/21 plugin-routes-authz, 1582/1583 full server suite.

**Refinement from the original plan:** the `delegation_capable` flag does NOT need to live on NoralOS's `agentApiKeys` — the trust decision is entirely server-side on NoralVoice. PR1 only plumbs the identity assertion; PR2 owns the trust gate.

### PR 2 — NoralVoice: accept delegated identity

**Repo:** `NoralVoice`

Implemented:
- Migration `20260526_add_api_key_delegation_capable.py`: adds `api_keys.delegation_capable BOOLEAN NOT NULL DEFAULT false` + partial index on flagged rows.
- [`api/db/models.py`](../../api/db/models.py): `APIKeyModel.delegation_capable` column.
- [`api/services/auth/depends.py`](../../api/services/auth/depends.py): `get_user` accepts two new header dependencies (`X-Noralos-Actor-User-Id`, `X-Noralos-Actor-User-Email`) and passes them to `_handle_api_key_auth`. The function implements the decision tree above — branching on `api_key.delegation_capable` AND presence of `actor_user_id`, then JIT-provisioning via the existing `get_or_create_user_by_provider_id(f"noralos:{actor_user_id}")` (same call browser SSO uses, so same `users` row regardless of arrival path).
- Email sync only on first JIT creation; existing users are never overwritten.
- `get_user_optional` signature kept in sync.

Tests (`api/tests/test_delegated_identity.py`): 5/5 pass.
- Delegation-capable key + actor headers + new user → JIT-provisioned, email synced.
- Delegation-capable key + actor headers + existing user → reused, email NOT overwritten.
- Delegation-capable key + no actor headers → falls back to `api_key.created_by`.
- Non-delegation key + actor headers → headers ignored (anti-spoofing).
- Invalid API key still 401s regardless of actor headers.

### PR 3 — NoralOS plugin: publish + validate tools

**Repo:** `NoralOS-canonical`

Changes:
- `packages/plugins/noralai-noralvoice/src/tools/publish-workflow.ts` — wraps `POST /api/v1/workflow/{id}/publish`. Returns `{ status, published_version }` or surfaces the validation error message verbatim.
- `packages/plugins/noralai-noralvoice/src/tools/validate-workflow.ts` — wraps `POST /api/v1/workflow/{id}/validate`. Returns `{ valid, errors[] }` for the agent to self-correct before publish.
- Register both in the plugin manifest.

Tests:
- Tool calls hit the right endpoints with right headers.
- Validation errors surface to the agent in a usable shape (per [feedback_noralvoice_editor_save_distrust.md], the agent must SEE 422s, not have them silently swallowed).

### PR 4 — NoralOS: author-workflow skill

**Repo:** `NoralOS-canonical`

Changes:
- `packages/plugins/noralai-noralvoice/skills/author-workflow/SKILL.md` — skill description, when to trigger, behavioural guidance.
- `schema-reference.md` — node types, required fields, edge conditions, model_overrides shape. Source-of-truth pulled from NoralVoice's existing workflow validator.
- `examples/intake-bot.json`, `examples/callback-agent.json`, `examples/support-transfer.json` — three worked examples covering common shapes.
- Skill behavior: after authoring, agent MUST call `validate_workflow`, fix any errors, then call `publish_workflow`.

No tests; this is documentation/prompting content.

---

## 7. Rollout

1. **Merge PR 1** to NoralOS main. Deploy to agent.noral.ai (staging path if available, else straight to prod since the new fields are additive and unused until PR 2).
2. **Merge PR 2** to NoralVoice main. Deploy to voice.noral.ai. Run migration. Verify regression test: existing browser SSO flow still works.
3. **Mark the voice service key delegation-capable** (script from PR 1). At this point, the auth bridge is live but no tools use it yet.
4. **Manual curl verification** before any agent-driven test:
   - `curl -H "X-API-Key: ..." -H "X-Noralos-Actor-User-Id: <quentin's noralos id>" -H "X-Noralos-Actor-User-Email: quentin@..." voice.noral.ai/api/v1/workflow/create/definition -d @minimal-workflow.json`
   - Expect: 201 Created, workflow visible in Quentin's voice.noral.ai UI.
   - Negative: same call with the API key marked `delegation_capable=false` → workflow owned by api_key.created_by, NOT visible in Quentin's UI.
5. **Merge PR 3**. Deploy. Agents can now publish/validate.
6. **Merge PR 4**. Deploy. Agents have schema knowledge.
7. **End-to-end verification:** prompt Brooklyn in NoralOS, "Create a callback workflow for ACME that asks for name and reason then schedules a callback." → verify the workflow appears in Quentin's voice.noral.ai → place a test call.

---

## 8. Verification (definition of done)

- [ ] Browser SSO regression: Quentin can still sign in to voice.noral.ai via Google.
- [ ] `curl` test: delegation-capable key + actor headers → workflow created under correct user.
- [ ] `curl` test: delegation-capable key + no actor headers → workflow created under api_key.created_by (fallback works).
- [ ] `curl` test: non-delegation key + actor headers → headers ignored (no spoofing).
- [ ] Brooklyn-driven creation: workflow appears in Quentin's UI under his account.
- [ ] Validation surfaces real errors to the agent (not silently swallowed).
- [ ] Publish promotes a draft to executable.
- [ ] End-to-end: a Brooklyn-authored workflow is dialable from voice.noral.ai.

Failing any of these = not done.

---

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Spoofed actor headers from a compromised non-delegation key | Headers ignored unless `delegation_capable=true`. The flag is set only on the voice service key, which lives in NoralOS server-side config. |
| `delegation_capable` flag accidentally set on a user's personal API key | Make flipping the flag a one-step admin action that records who flipped it and when. No UI exposure to end users. |
| Agent produces invalid graph JSON repeatedly, hitting publish 422s | `validate_workflow` tool + authoring skill examples. Agent self-corrects before publish. |
| Email collision during JIT — same email exists under a different `provider_id` | The existing JIT path already handles this for browser SSO. Reuse — don't reimplement. If today's behavior is "create duplicate user," that's a pre-existing bug worth filing but not blocking this work. |
| Workflow created by Brooklyn but never used (orphaned drafts) | Same risk as any draft creation; no new behavior. Optional follow-up: TTL on unpublished drafts. |
| Backwards compat — existing API key users see unexpected ownership change | None, by construction. Existing keys default to `delegation_capable=false`. |
| Editor save/publish quirks ([feedback_noralvoice_editor_save_distrust.md]) | Validate-before-publish + verify-from-DB pattern in the skill prevents the silent-drop scenarios from biting the agent flow. |

---

## 10. Alternatives + future work

- **B-jwt:** if we ever want to break the shared-secret trust (e.g. third-party agent hosts), swap the actor-headers-via-API-key trust for JWT-signed assertions. NoralOS mints a short-lived JWT scoped to the user; NoralVoice verifies via JWKS. Same identity model, no behavioral change to plugin tools or workflow code.
- **Org-scoped visibility (option D):** orthogonal concern. If Noral wants workflows visible across an org, that's a UI/query change, not an auth change. Can layer on independently.
- **Granular workflow editing tools:** the plugin currently does graph-level CRUD. If agents need to make incremental edits ("add a transfer node", "change edge condition"), we'd add `add_node`, `update_edge`, etc. Not in this proposal — it's a follow-up once we see whether the agent-as-author flow actually needs it.
- **MPS template endpoint:** if MPS gets fixed, `create_workflow_from_prompt` could wrap it as an alternative authoring path. Until then, agent-as-author is the recommended path anyway because it doesn't depend on a separate service.

---

## 11. Cross-references

- Memory: [project_noralvoice_noralos_relationship.md] — long-term relationship model that this proposal advances.
- Memory: [project_voice_google_sso_live_2026_05_26.md] — the browser SSO bridge this builds on.
- Memory: [project_workflow_create_mps_dependency.md] — why we're not wrapping the MPS template endpoint.
- Memory: [feedback_noralvoice_editor_save_distrust.md] — why `validate_workflow` and DB-verification matter.
- Memory: [project_voice_deploy_layout.md] — deploy locations on voice.noral.ai.
- Memory: [project_noralos_prod_runtime_2026_05_20.md] — NoralOS prod runtime state, plugin loader.
- Memory: [project_noralos_agent_authoring.md] — the original "agents authoring workflows" goal this proposal makes concrete.
