# NoralVoice Rebrand — Claude Code Prompts

Run these tier by tier. Verify each tier before moving to the next. Do NOT batch them — each tier has different risk profiles.

**Rebrand target:**
- Product name: `NoralVoice` (one word, capitalized)
- Lowercase/code form: `noralvoice`
- Env var prefix: `NORALVOICE_`
- Production domain: `voice.noral.ai`
  - App: `voice.noral.ai`
  - API: `api.voice.noral.ai`
  - Docs: `docs.voice.noral.ai` (or hosted elsewhere — confirm)
- Cookie domain: `.noral.ai` (covers all Noral subdomains)
- Repo posture: Private — strip public community references entirely
- GitHub org: `noralai` (confirmed)
- Container registry: `ghcr.io/noralai/noralvoice-*`
- MPS strategy: CONFIGURATION-only — don't rip MPS code out (breaks
  upstream sync). Instead, ensure no agent uses DOGRAH provider so MPS
  code is dead-code present-but-unreached. Handled in Tier 5.

**ACTUAL plan: Tier 7 — Minimal fix (supersedes Tier 6 entirely).**

Prior Tier 6 plans (full white-label and skin-only) are both
superseded. Both rebranded files that are upstream-tracked (README,
layout.tsx, Footer.tsx, api/app.py), which creates permanent merge
conflicts on every sync from `dograh-hq/dograh@main`. The
`deploy/noral/` architectural pattern explicitly avoids that.

**Run order (only this matters now):**
Tier 7.0 (walkthrough) → 7.1 (cookie domain, NOT optional) →
7.2 (user-visible rebrand, ≤10 files) → 7.3 (embed widget, conditional)
→ 7.4 (Sentry org, optional) → final verification

Expected scope: 5-10 files, ~30 minutes of work.

**Everything below in Tiers 1-6 is HISTORICAL CONTEXT, not a plan to
execute.** Tiers 1-5 already partially ran. Tier 6 (skin-only and
white-label) was both removed. Read for context; do not run any of
those prompts.

The deliberately deferred surfaces (README, AGENTS.md, scripts/,
docs/, sdk/, docker-compose.yaml, DOGRAH_* env vars, dograh_tokens DB
columns, .github/workflows/, examples/) STAY as Dograh to preserve
clean upstream sync. This is a feature, not a bug.

**Do NOT touch:**
- `pipecat/` submodule (external dependency)
- `venv/`, `node_modules/`, `.next/`, `__pycache__/`
- Any `.git/` internals

---

## Tier 1 — Customer-visible (do this before any demo)

### Prompt 1.1: UI strings and brand surface

```
I'm rebranding this codebase from Dograh to NoralVoice. This tier focuses on
user-visible UI strings only — no env vars, no docs, no scripts yet.

Replace the brand name in these UI surfaces:
- ui/ — all .tsx, .ts, .jsx, .js files
- ui/public/ — any HTML, manifest.json, favicon-related metadata
- Page titles, meta tags, og:tags, footer text, login screens, error pages
- Any user-visible "Dograh" string

Replacement rules:
- "Dograh" → "NoralVoice"
- "dograh" (in user-visible copy only, NOT in identifiers/cookies/env vars) → "noralvoice"
- "DOGRAH" in user-visible UI copy → "NORALVOICE"

Do NOT change in this pass:
- Cookie names (LEGACY_OSS_TOKEN_COOKIE references — handled in 1.2)
- Domain detection logic (window.location.hostname checks — handled in 1.2)
- Type literals like 'dograh' as a TTS provider name in VoiceSelector.tsx — that's
  an internal identifier mapping to a backend voice provider; leave it
- Auto-generated client files in ui/src/client/ — these regenerate from the API
- Any DOGRAH_* env var reads (handled in Tier 2)

After making changes, show me a summary of every file modified and a sample of
3 before/after diffs so I can spot-check.
```

### Prompt 1.2: Cookie names and domain logic (auth migration)

```
This step migrates the auth cookie names and domain detection from Dograh to
NoralVoice. Sessions must NOT break for any currently logged-in user, so we
write new cookies AND read old ones during a grace period.

Files to change:
- ui/src/middleware.ts
- ui/src/app/api/auth/logout/route.ts
- ui/src/app/api/auth/oss/route.ts
- ui/src/app/api/auth/session/route.ts
- ui/src/lib/auth/server.ts
- ui/src/lib/utils.ts

Changes:

1. Add new cookie name constants alongside the legacy ones:
   const NORAL_AUTH_TOKEN_COOKIE = 'noral_auth_token';
   const NORAL_AUTH_USER_COOKIE = 'noral_auth_user';
   Keep:
   const LEGACY_OSS_TOKEN_COOKIE = 'dograh_auth_token';
   const LEGACY_OSS_USER_COOKIE = 'dograh_auth_user';

2. On WRITE (login, session refresh): write the new NORAL_* cookies.

3. On READ (middleware, session checks): try NORAL_* first, fall back to
   LEGACY_OSS_* if not present. If a legacy cookie is found, re-issue as a
   NORAL_* cookie on the response so sessions migrate forward on next request.

4. On LOGOUT: clear BOTH the NORAL_* and LEGACY_OSS_* cookies.

5. In ui/src/lib/utils.ts, replace the domain detection:
   - OLD: window.location.hostname.endsWith('.dograh.com')
   - NEW: window.location.hostname.endsWith('.noral.ai')
   - Update the cookieDomainPart accordingly: '; domain=.noral.ai'
   - For local dev (localhost), no domain attribute is set — preserve that.

After making changes:
- Show me the full diff of ui/src/lib/utils.ts and ui/src/middleware.ts
- Confirm the logout flow clears both old and new cookies
- Run any existing auth tests (api/tests/test_auth* or ui auth tests)
```

### Prompt 1.3: Repo-root marketing files

```
Rebrand the repo-root files that anyone looking at this codebase sees first:
- README.md
- CONTRIBUTING.md
- SECURITY.md
- CHANGELOG.md (just the brand strings; don't rewrite history)

Replace:
- "Dograh" → "NoralVoice"
- "dograh" → "noralvoice" in body copy (not in git commit SHAs, not in
  package-lock paths)
- "https://app.dograh.com" → "https://voice.noral.ai"
- "https://api.dograh.com" → "https://api.voice.noral.ai"
- "https://docs.dograh.com" → "https://docs.voice.noral.ai"
- "github.com/dograh-hq/dograh" → (REMOVE THE LINK — this is a private repo
  rebrand; do not point to dograh-hq)
- Slack community invite link (the join.slack.com/.../dograh-community/...) →
  REMOVE
- "Dograh Community" Slack mentions → REMOVE entirely (we're going private)
- Replace any "Report a bug at github.com/dograh-hq/dograh/issues" with
  "Report a bug to your NoralVoice administrator"

In CHANGELOG.md specifically: do NOT rewrite past version entries. Only update
the project name at the top of the file. The history of "dograh-v1.2.3"
release tags is fine to keep — that's git history, not brand.

INCIDENT-2026-05-17-postgres-handoff.md: leave references to Dograh that
describe historical fact (e.g., "the Dograh database was migrated on X").
Update any forward-looking references and the doc header.

After changes, show me:
1. List of files modified
2. The full new README.md
3. Any URLs you kept and why
```

---

## Tier 2 — Operational (do before team/clients onboard)

### Prompt 2.1: Environment variable migration

```
Migrate environment variables from DOGRAH_* to NORALVOICE_* without breaking
any deployment that still has the old env vars set.

There are 25 DOGRAH_* env vars in this codebase. Run this command first to
get the current list, then plan the migration:

  grep -rohE "DOGRAH_[A-Z_]+" . \
    --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=.git \
    --exclude-dir=.next --exclude-dir=__pycache__ --exclude-dir=pipecat \
    | sort -u

Migration strategy (do NOT do a flat find-and-replace):

1. For every DOGRAH_FOO env var, create a NORALVOICE_FOO equivalent.

2. In code that READS env vars (Python config files, shell scripts,
   docker-compose interpolations), read NORALVOICE_FOO first and fall back to
   DOGRAH_FOO if unset. Log a deprecation warning when the fallback is used.
   Example Python pattern:
     api_key = os.getenv("NORALVOICE_API_KEY") or os.getenv("DOGRAH_API_KEY")
     if not os.getenv("NORALVOICE_API_KEY") and os.getenv("DOGRAH_API_KEY"):
         logger.warning("DOGRAH_API_KEY is deprecated; use NORALVOICE_API_KEY")

3. Update all .env.example files to ONLY reference NORALVOICE_* (not the
   legacy names) so new deployments use the new names.

4. Update docker-compose.yaml and docker-compose-local.yaml to pass through
   both old and new env vars during the migration window.

5. Update deploy scripts in scripts/ to set NORALVOICE_* primarily.

DO NOT change names like:
- Third-party env vars (TWILIO_*, OPENAI_*, ELEVENLABS_*, etc.) — those are
  not ours to rename
- Database connection strings (POSTGRES_*, REDIS_*) — those aren't branded

Files most affected:
- api/services/configuration/registry.py (20 hits)
- scripts/*.sh (multiple)
- docker-compose*.yaml
- .env.example files in api/ and ui/

After changes:
1. Show me the env var migration map (old name → new name)
2. List every file modified
3. Confirm no DOGRAH_* references remain that don't have a NORALVOICE_*
   companion
```

### Prompt 2.2: File and directory renames

```
Rename files and directories that have "dograh" in their path. This breaks
import paths and links, so be thorough about updating references.

Renames to perform:
1. docs/core-concepts/how-dograh-works.mdx → how-noralvoice-works.mdx
   Update every link to this file in other docs.
2. nginx/dograh_upstream.conf.template → nginx/noralvoice_upstream.conf.template
   Update any deploy script that references this filename.
3. scripts/run_dograh_init.sh → scripts/run_noralvoice_init.sh
   Update any caller (docker-compose, other scripts, deploy docs).

Also check for any other file or directory in the repo whose NAME contains
"dograh" (case-insensitive) using:
  find . -iname "*dograh*" -not -path "*/node_modules/*" -not -path "*/venv/*" \
    -not -path "*/.git/*" -not -path "*/.next/*" -not -path "*/.claude/*" \
    -not -path "*/pipecat/*"

Rename each. After every rename, grep for the old filename across the repo
and update references.

Show me:
1. Every rename performed
2. Every file modified to update references
3. Any reference you couldn't update and why
```

### Prompt 2.3: Package names and CI/CD

```
Update package.json names and GitHub workflow files.

1. Rename package names:
   - examples/typescript/package.json: "dograh-examples-typescript" →
     "noralvoice-examples-typescript"
   - api/mcp_server/ts_validator/package.json: "dograh-ts-validator" →
     "noralvoice-ts-validator"
   - Delete the existing package-lock.json files in those directories so
     they regenerate on next `npm install`
   - Check the root package.json and any other package.json in the repo
     for "dograh" in the name field

2. Update GitHub workflow files in .github/workflows/:
   - docker-image.yml: replace any dograh-named image, tag, or registry path
     with noralvoice equivalents
   - pre-pr-drift-check.yml, api-tests.yml, release-deployment.yml,
     slack-announcements.yml: scan for any Dograh references; replace
     brand strings, but be careful with secrets names like DOGRAH_API_TOKEN
     (those should match what's in your GitHub repo secrets — coordinate
     with the env var migration in 2.1)

3. .github/ISSUE_TEMPLATE/config.yml:
   - Strip any link to dograh-hq's GitHub or Slack
   - Since this repo is going private, you can either delete the issue
     templates entirely or replace community links with your internal
     support email

4. .gitmodules: the pipecat submodule points to github.com/dograh-hq/pipecat.git
   - DO NOT change this unless you're forking pipecat to your own org. If you
     do fork it later, update the URL and run:
       git submodule sync && git submodule update --init --recursive

5. release-please-config.json: update the package name if it references dograh

6. .gitignore: check for any dograh-named paths and update

Show me:
1. Every package.json modified
2. Every workflow file modified with a summary of what changed
3. Confirmation that .gitmodules was NOT changed (unless I explicitly approved)
```

### Prompt 2.4: Docker/Compose/code-side artifact renames

```
Coordinated rename of all "dograh" identifiers that are baked into the actual
running system (not docs, not env vars — those were prior tiers). This is a
single atomic change because container names, image names, and the Compose
project name all reference each other.

Renames to perform:

1. Docker Compose project name (the thing that prefixes container names):
   - docker-compose.yaml: add or update `name: noralvoice` at the top level
     (Compose v2 syntax). If the project name is currently being set via
     COMPOSE_PROJECT_NAME env var or `-p dograh` flag in scripts, update
     those references too.
   - docker-compose-local.yaml: same treatment.
   - Result: container names will become noralvoice-postgres-1,
     noralvoice-redis-1, noralvoice-minio-1, noralvoice-api, noralvoice-ui,
     noralvoice-init, etc.

2. Docker image names referenced in compose files and deploy scripts:
   - Anywhere images are named "dograh-api", "dograh-ui", "dograh-init",
     etc., rename to "noralvoice-api", "noralvoice-ui", "noralvoice-init".
   - Update the build context and image tags consistently.

3. Hardcoded Telnyx application name prefix in code:
   - File: api/services/telephony/providers/telnyx/__init__.py:53
   - Change: application_name = f"dograh-{uuid.uuid4().hex[:12]}"
   - To:     application_name = f"noralvoice-{uuid.uuid4().hex[:12]}"
   - This is the name customers see in their Telnyx console — important.

4. Web widget filenames and DOM IDs (embed code customers paste on their site):
   - Find: dograh-widget.js → rename to noralvoice-widget.js
   - Find: dograh-inline-container (HTML element ID) → noralvoice-inline-container
   - Find: any related CSS class names (dograh-*) → noralvoice-*
   - Update every documentation reference to the new filenames/IDs.

5. Init script and reload script renames:
   - scripts/run_dograh_init.sh → scripts/run_noralvoice_init.sh
   - Any dograh-reload.sh → noralvoice-reload.sh
   - Update every caller (docker-compose, Dockerfiles, deploy docs).

6. The "dograh/" directory created by setup_remote.sh on remote hosts:
   - Update the script to create "noralvoice/" instead.
   - Update DOGRAH_DEPLOY_* env vars to NORALVOICE_DEPLOY_* (this should
     have happened in Tier 2.1; verify and complete if missed).

7. Check api/services/configuration/registry.py for any remaining
   "dograh" string constants and rename appropriately.

DO NOT change:
- pipecat/ submodule contents (still external dependency)
- Any 'dograh' references that are internal voice provider identifiers in
  TTS/STT configuration (these map to specific backend models, not branding)
- Existing customer data — DO NOT write migration scripts that rename
  existing Telnyx applications or running containers. Future-created
  resources get the new name; existing ones stay until manually rotated.

After changes:
1. Show me the docker-compose.yaml diff in full
2. Confirm the Telnyx prefix change with file:line
3. List every script renamed and every caller updated
4. Run `docker-compose config` to validate the Compose file parses cleanly
5. Flag any reference you weren't sure about so I can decide
```

### Prompt 2.5: Hosting URLs (GitHub, GHCR, install scripts)

```
Replace all references to Dograh's hosted artifacts (GitHub repo, container
registries, install scripts) with NoralVoice equivalents.

GitHub org confirmed: 'noralai'. Use this as the org name for all GitHub
and GHCR URLs below.

Replacements:

1. GitHub raw content URLs (install/bootstrap scripts):
   - OLD: https://raw.githubusercontent.com/dograh-hq/dograh/main/...
   - NEW: https://raw.githubusercontent.com/noralai/noralvoice/main/...
   - Found primarily in: README.md, docs/deployment/*, scripts/setup_remote.sh,
     scripts/setup_local.sh, scripts/update_remote.sh

2. GitHub repo URLs:
   - OLD: github.com/dograh-hq/dograh
   - NEW: github.com/noralai/noralvoice
   - But for a PRIVATE repo, prefer REMOVING the URL in customer-facing docs
     and keeping it only in internal contributor docs.

3. Container registry references:
   - OLD: ghcr.io/dograh-hq/dograh-api, ghcr.io/dograh-hq/dograh-ui, etc.
   - NEW: ghcr.io/noralai/noralvoice-api, ghcr.io/noralai/noralvoice-ui, etc.
   - Files: docker-compose.yaml, .github/workflows/docker-image.yml,
     .github/workflows/release-deployment.yml, deploy/* scripts

4. Docker Hub references:
   - OLD: docker.io/dograhai/*, dograhai/*
   - NEW: REMOVE entirely. NoralVoice is private; not publishing to Docker Hub.
   - If a doc mentions "pull from Docker Hub", rewrite to "pull from
     ghcr.io/noralai/noralvoice-*" or "build locally from source".

5. GitHub Issues / Discussions / Releases links:
   - For private repo: REMOVE all customer-facing references to
     github.com/dograh-hq/dograh/issues, .../discussions, .../releases
   - Replace with internal support email or your customer support channel.
   - Keep internal contributor references if appropriate (CONTRIBUTING.md).

6. Slack community references:
   - OLD: any join.slack.com URL with dograh-community
   - NEW: REMOVE entirely. Private repo — no public community.

After changes:
1. Run a final grep for "dograh-hq" and "dograhai" and confirm zero hits
   in production code/docs (test fixtures or git history references in
   CHANGELOG are OK)
2. List every file modified
3. Confirm no broken links remain by checking each replacement points to a
   sensible target (or has been intentionally removed)
```

---

## Tier 3 — Documentation rewrite

### Prompt 3.1: Docs content rebrand

```
Rebrand all docs/*.mdx files. This is the largest content change (68 files,
~1,000 brand references), but the technical risk is low — just be thorough
about cross-links.

Tasks:
1. In every .mdx file under docs/:
   - "Dograh" → "NoralVoice"
   - "dograh" → "noralvoice" in body prose (not in code samples that reference
     env var names like DOGRAH_API_KEY — those depend on Tier 2.1 being done first)
   - URLs: app.dograh.com → voice.noral.ai
            api.dograh.com → api.voice.noral.ai
            docs.dograh.com → docs.voice.noral.ai
   - github.com/dograh-hq/dograh → REMOVE (this is private)
   - The Slack community invite link → REMOVE
   - "Dograh community" references → REMOVE or replace with
     "your NoralVoice administrator"

2. Update internal docs links that point to renamed files (see Tier 2.2):
   - /core-concepts/how-dograh-works → /core-concepts/how-noralvoice-works

3. Update docs/mint.json (or whatever the Mintlify config file is called):
   - Site name
   - Logo paths if branded
   - Navigation labels
   - Social links — remove or replace

4. Check docs/images/ and docs/logo/ for branded image files. List any you
   find — don't replace them automatically; flag them for me to swap manually
   with NoralVoice assets.

ORDER OF OPERATIONS: Run Tier 2.1 (env var migration) BEFORE this prompt so
that the env var names referenced in code samples throughout the docs match
what's actually in the codebase.

After changes:
1. Count of files modified
2. List of any image/asset files that need manual replacement
3. List of any links you couldn't resolve (broken references)
```

---

## Tier 4 — SDK regeneration

### Prompt 4.1: SDK rebrand via codegen template

```
The sdk/ directory contains auto-generated client libraries (TypeScript and
likely Python). Hand-editing 51 generated files is fragile — instead, update
the codegen templates and regenerate.

Tasks:
1. Locate the codegen entry point: sdk/codegen/client_codegen.py
   - Read it and identify where the brand name, package name, and any URLs
     are templated
   - Update those template strings: Dograh → NoralVoice, dograh → noralvoice,
     app.dograh.com → voice.noral.ai

2. Identify which generated files exist and their source templates:
   - sdk/typescript/* (TypeScript SDK)
   - Any Python SDK in sdk/python/ if present
   - ui/src/client/types.gen.ts is also auto-generated from the OpenAPI spec —
     update the codegen for it too (look for an openapi-typescript or
     hey-api/openapi-ts config)

3. Run the codegen to regenerate:
   - Follow whatever command is documented in sdk/codegen/ or in package.json
     scripts (likely `npm run generate` or `python -m sdk.codegen.client_codegen`)
   - If the command isn't obvious, STOP and ask me before running anything

4. After regeneration, diff the changes:
   - Confirm Dograh references in sdk/ dropped from ~51 files to 0 (or close)
   - Any remaining hits are either (a) hand-written wrapper code that needs
     the same treatment as Tier 1, or (b) test fixtures

5. Update any SDK README or example code:
   - sdk/typescript/README.md (if it exists)
   - examples/typescript/*

Show me:
1. The codegen entry points you found and updated
2. The exact regeneration command(s) you ran (or would run, if you stopped
   to ask)
3. Diff of file counts containing "dograh" before vs after
```

---

## Tier 5 — MPS bypass via CONFIGURATION (revised, May 2026)

**Strategic context:** the original Tier 5 ripped MPS (services.dograh.com)
out of `service_factory.py`. That breaks upstream sync, since the file is
upstream-owned. New approach: leave the MPS code intact, just ensure no
agent is configured to use the DOGRAH provider. The MPS code becomes dead
code — present but never called.

### Prompt 5.1: Configure NoralVoice to bypass MPS

```
This prompt makes NoralVoice route every call directly to underlying
provider APIs (Deepgram, ElevenLabs, OpenAI, etc.) WITHOUT modifying the
upstream MPS code paths. The MPS layer in service_factory.py stays intact
and untouched — it just never gets invoked because no agent is configured
with ServiceProviders.DOGRAH.

Tasks:

1. Audit existing user_configs / agent configs in the running database:
   SELECT id, stt_provider, tts_provider, llm_provider FROM user_config
   WHERE stt_provider = 'dograh' OR tts_provider = 'dograh'
     OR llm_provider = 'dograh';
   - For each row found, replace the 'dograh' provider with a real one:
     STT → 'deepgram', TTS → 'elevenlabs' or 'cartesia', LLM → 'openai'.
   - Update the api_key field for the new provider — the customer must
     supply their own provider API key. If no key is available, FLAG
     for me to provide one.

2. Update default agent templates (if any) so newly created agents do NOT
   default to ServiceProviders.DOGRAH. Find templates in:
   - api/services/configuration/ — any default config that references
     ServiceProviders.DOGRAH should be changed.
   - api/db/seed data (if any) for default user_configs.
   - The UI agent creation flow (ui/src/app/workflow/) — confirm the
     provider dropdown does not pre-select 'dograh'.

3. Set MPS_API_URL to an inert value via environment config so that even
   if some code path tries to hit MPS, the request fails fast rather than
   leaking call data to services.dograh.com:
   - Set in .env: MPS_API_URL=http://disabled.invalid
   - Document in deploy/noral/README.md that MPS is not used and the URL
     is deliberately inert.

4. Add a startup warning in api/app.py: if any user_config or default
   template references ServiceProviders.DOGRAH at boot, log a warning.
   Pattern (pseudo):
     dograh_configs = db.query(UserConfig).filter(
       UserConfig.stt_provider == 'dograh' OR ...
     ).count()
     if dograh_configs > 0:
       logger.warning(
         f"{dograh_configs} agent configs still reference the dograh "
         f"provider. These will attempt to route through MPS. "
         f"Reconfigure them to use direct provider APIs."
       )

5. DO NOT modify:
   - api/services/pipecat/service_factory.py (upstream code; stays intact)
   - api/services/mps_service_key_client.py (upstream code)
   - api/services/auth/depends.py — but VERIFY that the MPS service-key
     validation path is not the only auth path. If it is, FLAG before
     proceeding; we may need to add a non-MPS auth path.
   - pipecat/ submodule

6. Test paths:
   - Start a local call with Deepgram STT + ElevenLabs TTS + OpenAI LLM
   - Confirm no network traffic to *.dograh.com during the call:
     `lsof -i -P | grep -i dograh` or capture with mitmproxy/Charles
   - Verify the transcript, recording, and cost info are correct in the
     run record
   - Test the startup warning by temporarily setting an agent to DOGRAH
     provider and confirming the warning logs

After changes:
1. Show me the list of agent configs that needed reprovisioning
2. Confirm the startup warning fires when DOGRAH is configured
3. Show me a successful test call's logs proving no dograh.com traffic
4. Flag any auth path that depends on MPS
```

### Prompt 5.2: Verify no live traffic to dograh.com

```
Audit-only verification that no production runtime path is reaching
services.dograh.com or other *.dograh.com hosts.

Run:

1. Static grep across api/, ui/, scripts/, deploy/ for:
   - services.dograh.com (any reference outside docs/ and pipecat/ is
     a concern)
   - 'dograh' as a provider value in any config/seed/migration

2. For each remaining hit, classify:
   - INTENTIONAL: upstream code in service_factory.py / mps_service_key_client.py /
     auth/depends.py (acceptable — code is present but no longer
     reachable because no agent is configured with DOGRAH provider)
   - INTENTIONAL: pipecat submodule (external dependency)
   - INTENTIONAL: historical docs / CHANGELOG / runbook
   - PROBLEM: a live code path or active config that could still reach Dograh

3. Run the test suite (api/tests/) and confirm no test makes an outbound
   request to dograh.com hosts during the run (capture with a mock or
   check test logs).

4. In the running database, verify:
   SELECT COUNT(*) FROM user_config
   WHERE stt_provider = 'dograh' OR tts_provider = 'dograh'
     OR llm_provider = 'dograh';
   This should return 0.

5. Report:
   - Total dograh.com references remaining and their classification
   - DB count of remaining DOGRAH-provider configs (should be 0)
   - Whether the codebase is safe to deploy without MPS traffic
   - Any remaining risk you'd flag to the user

DO NOT make any changes — this is audit-only.
```

---
## Tier 7 — Minimal fix (FINAL approach, supersedes prior Tier 6 plans)

**Why this replaces every prior Tier 6 plan:**

Both the full white-label Tier 6 and the skin-only Tier 6 rebranded files
that are upstream-tracked (README, layout.tsx, Footer.tsx, api/app.py,
etc.). Every such file creates a permanent merge conflict on every sync
from `dograh-hq/dograh@main`. The `deploy/noral/` architectural pattern
explicitly avoids touching upstream-tracked files for exactly this reason.

Each prior rebrand pass was declared done but turned out partial. A third
or fourth pass leaves ~1,200 hits that keep regenerating with each
upstream sync. This is the rebrand treadmill.

The strategic insight: only rebrand what a user actually SEES when using
voice.noral.ai. Everything else is engineer-visible only and pays no
customer benefit while costing merge conflicts forever.

**Likely actual scope: 5-10 files, ~30 minutes of work.**

---

### Step 7.0 — Self-walkthrough (REQUIRED before running 7.2)

Spend 5 minutes using voice.noral.ai the way a daily user does. Note
every place you see "Dograh." Likely candidates:

- Page title in the browser tab
- App name in the sidebar / header
- Footer copyright or branding line
- Welcome copy on Overview page
- "Service Keys" wording on API Keys page (if user-visible)
- Token usage label on Usage page
- Any modal or empty-state copy
- The embed dialog (if you use it)

Anything NOT on your walkthrough list stays as Dograh. That includes:
- README.md, AGENTS.md, CONTRIBUTING.md, SECURITY.md (engineer-visible)
- All of docs/ (upstream Mintlify)
- All of scripts/ (upstream tooling)
- All of sdk/ (already off-spec renamed; leave as-is or revert per
  separate decision)
- docker-compose.yaml, deploy/templates/, nginx/
- All .github/workflows/
- All examples/
- All `DOGRAH_*` env vars
- All `dograh_tokens` DB columns
- pipecat/ submodule
- VoiceSelector.tsx provider literal 'dograh' (upstream identifier)

---

### Step 7.1 — Cookie domain (NOT optional, auth-critical)

```
Tier 7 Step 1: fix the cookie domain in ui/src/lib/utils.ts so auth
cookies scope correctly to .noral.ai on voice.noral.ai.

This is the only functionally-required change in Tier 7. If left unfixed,
auth cookies will fail to set on .noral.ai and login flows will silently
break. This is NOT cosmetic.

Files to change:
- ui/src/lib/utils.ts (lines 118, 119, 174, 180)

Changes:
- endsWith('.dograh.com') → endsWith('.noral.ai')
- '; domain=.dograh.com' → '; domain=.noral.ai'
- Any other URL or domain hardcode that affects cookie scope

DO NOT touch:
- ui/src/middleware.ts (cookie name constants — already correct from
  Tier 1.2)
- ui/src/lib/auth/server.ts (cookie name constants — already correct)
- ui/src/app/api/auth/* (auth route handlers — already correct)

Test on a CLEAN browser profile (incognito or fresh profile):
1. Clear all cookies for .noral.ai and .dograh.com
2. Go to voice.noral.ai
3. Complete the login flow end-to-end
4. Verify auth cookies are set with domain=.noral.ai (use DevTools →
   Application → Cookies)
5. Reload the page and verify the session persists
6. Test logout: cookies should clear cleanly

STOP and ask before committing if the login flow regresses in any way.
The user has been bitten by cookie fragility before and this is the one
place a regression breaks production auth.
```

---

### Step 7.2 — Customer-visible rebrand (use walkthrough list)

```
Tier 7 Step 2: rebrand ONLY the user-visible surfaces I identified
during my walkthrough. Maximum 10 files. If you find yourself wanting
to rebrand a file not on my walkthrough list, STOP and ask first.

DO NOT extend scope. The cost of each file rebranded is a permanent
merge conflict with upstream. We are deliberately keeping that surface
small.

My walkthrough list (replace with what I actually found — these are
likely candidates):
- ui/src/app/layout.tsx (page title metadata)
- ui/src/components/layout/AppSidebar.tsx (sidebar app name)
- ui/src/components/layout/AppLayout.tsx (header)
- ui/src/components/Footer.tsx (footer brand)
- ui/src/app/overview/page.tsx (welcome copy / token usage label)
- ui/src/app/api-keys/page.tsx (if "Service Keys" label is user-visible)
- ui/src/app/usage/page.tsx (token usage label)
- Any other page surface on my walkthrough list

For each: replace user-visible "Dograh" → "NoralVoice" ONLY in rendered
strings (JSX text, label props, placeholder text, aria-label, alt text,
modal titles).

DO NOT touch:
- API response field names (e.g., the `dograh_token_usage` key in JSON
  responses — upstream contract, just translate the LABEL in the UI)
- Any string inside <code> or <pre> blocks that's an env var name,
  package name, or CLI flag (these are upstream identifiers)
- ui/src/client/* (auto-generated)
- ui/src/components/layout/GitHubStarBadge.tsx — recommend DELETING
  this component entirely if still present (private repo, stars
  meaningless), but flag for confirmation before deleting

After changes:
1. Total files modified: must be ≤10
2. Show me the diff of each file in full
3. Confirm grep for "Dograh\|dograh" in the changed files shows only
   intentional remaining hits (provider literals, upstream identifiers,
   etc.)
4. Confirm UI builds cleanly: `cd ui && npm run build`
```

---

### Step 7.3 — Embed widget (CONDITIONAL — skip unless on walkthrough)

If the embed dialog or widget did NOT appear on your walkthrough — skip
this step entirely. The widget filename can stay `dograh-widget.js`;
engineer-only visibility.

If you DO show clients the embed code or actively use the widget in
demos, run this:

```
Tier 7 Step 3: rename embed widget per the conditional decision above.

Only run this if the embed widget surface is on the walkthrough list.

Files to change:
- ui/public/embed/dograh-widget.js → noralvoice-widget.js
- Content of the widget file (~66 internal references)
- ui/src/app/workflow/[workflowId]/components/EmbedDialog.tsx (16
  references — the file that generates the embed snippet customers paste)

DO NOT touch:
- docs/voice-agent/add-to-website.mdx (Mintlify upstream — leave as-is
  even if mismatched; not in scope)

After changes:
1. Confirm the old file no longer exists at ui/public/embed/dograh-widget.js
2. Show me the diff of EmbedDialog.tsx
3. Verify the widget still loads end-to-end (start UI, load embed test)
```

---

### Step 7.4 — Sentry org switch (OPTIONAL — only if you have a Sentry org)

Only run this if ALL of the following are true:
- You have a Sentry account under "noralai" (or your own org)
- You're actively monitoring voice.noral.ai errors
- You accept losing historical error grouping under the "dograh" org

If you don't have a Sentry account, skip and comment out the Sentry
plugin block in ui/next.config.ts to stop errors leaking to Dograh's
Sentry org.

```
Tier 7 Step 4 (optional): switch Sentry org in ui/next.config.ts.

Files to change:
- ui/next.config.ts (line 39 — org: "dograh")

Choices:
A. If you have your own Sentry org: change to org: "noralai" (or
   whatever slug) and update auth token in env config.
B. If you don't: comment out the entire Sentry plugin block so no
   errors leak to Dograh's Sentry.

Continuity caveat: a new org means a new baseline. Historical error
counts, alert thresholds, dashboards, and release tags from "dograh"
do not migrate. Stand up alerts intentionally on the new org rather
than expecting parity with the old one.

After changes:
1. Show me the diff of ui/next.config.ts
2. Confirm a test error in voice.noral.ai surfaces in the new org (or
   confirm no errors leak anywhere if commented out)
```

---

### Final verification (after 7.1 + 7.2, and optionally 7.3/7.4)

```
Final verification for Tier 7:

1. Login flow works on a clean browser at voice.noral.ai
2. Cookies are scoped to .noral.ai (verified via DevTools)
3. Every user-visible Dograh reference from my walkthrough is gone
4. UI builds cleanly (npm run build in ui/)
5. Total files modified is ≤12 across all Tier 7 steps

Run: git diff --name-only main...HEAD
The output should be a SHORT list, all within ui/src/ (plus optionally
ui/public/embed/ and ui/next.config.ts).

If any file outside ui/ is modified, that's scope creep — flag it and
ask whether to revert.
```

---

## What's deliberately deferred (and why)

Everything not on the Tier 7 walkthrough list is **deliberately left as
Dograh** to preserve clean upstream sync from `dograh-hq/dograh@main`.

This includes: README, AGENTS.md, docs/, scripts/, sdk/, docker-compose,
DOGRAH_* env vars, dograh_tokens DB columns, .github/workflows, examples,
nginx configs, deploy templates, and any other engineer-visible surface.

**This is not a half-done rebrand.** It is the FULL rebrand for what
users actually see, with an intentional decision to leave engineer-facing
surfaces upstream-compatible.

If you later decide to hard-fork (commit to never syncing from upstream
again), revisit this decision and run a full white-label sweep. Until
then: do not touch the deferred surfaces.

---

## Status of prior Tier 6 plans (superseded)

- **Tier 6 "full white-label" (A-F covering compose, SDK, env vars,
  DB columns)** — SUPERSEDED. Do not run any old 6.A-6.F prompts.
- **Tier 6 "skin-only" (the May 2026 rewrite)** — SUPERSEDED. Do not
  run the skin-only 6.A-6.F prompts either; they were too broad.
- **Anything that already ran from those plans** — accept the current
  state, do not extend. The SDK was renamed to `noralai_voice/` (off-spec
  but harmless if you accept the divergence). Treat that as a separate
  reversion decision (see SDK revert section in memory if you decide to
  restore upstream sync on that surface).

---

## Final verification prompt

### Prompt V.1: Audit

```
Audit the rebrand by counting remaining "Dograh" / "dograh" / "DOGRAH"
references and categorizing each.

Run:
  grep -rE "Dograh|dograh|DOGRAH" . \
    --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=.git \
    --exclude-dir=.next --exclude-dir=__pycache__ --exclude-dir=.claude \
    --exclude-dir=pipecat --exclude="*.lock" --exclude="package-lock.json" \
    --exclude="pnpm-lock.yaml"

Categorize every remaining hit as one of:
- INTENTIONAL: legacy cookie/env var fallback reads (Tier 1.2 / 2.1 design)
- INTENTIONAL: historical fact in CHANGELOG.md / INCIDENT-*.md
- INTENTIONAL: pipecat submodule reference (external dependency)
- INTENTIONAL: TTS provider internal identifier "dograh" (backend provider name)
- TO FIX: anything else

Report:
1. Total remaining hits
2. Count in each category
3. Full list of "TO FIX" hits with file:line
4. Whether you recommend a Tier 5 cleanup or whether the remaining hits
   are all acceptable

DO NOT make any changes in this pass — this is audit-only.
```

---

## Notes on running these

- Run each prompt in a fresh Claude Code session, or at minimum start with
  `/clear` to reset context. These prompts are designed to be self-contained.
- After each tier, manually test the relevant surface: log in, hit the docs,
  trigger a test call, run the test suite.
- If Claude Code asks for approval on a destructive change (deleting files,
  bulk renames), READ what it's about to do — don't reflexively approve.
- Commit after each tier. If a tier breaks something, `git revert` is your
  friend.
