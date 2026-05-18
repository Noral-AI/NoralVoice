# Runbook: Postgres compromise

Recovery procedure if `dograh-postgres-1` is breached, based on the **pg_mem / Operation Hadooken** cryptojacking pattern observed on voice.noral.ai on 2026-05-17.

## When to use this runbook

Use this if you see ANY of:

- `psql -c '\du'` shows a role you don't recognize (especially superuser)
- `psql -c 'SELECT * FROM pg_event_trigger'` returns any rows
- Top CPU on the server is a process named `/tmp/mysql`, `/tmp/init`, `kdevtmpfsi`, `kinsing`, or anything else in `dograh-postgres-1`
- Repeated `password authentication failed for user "postgres"` in `docker logs dograh-postgres-1`
- The monitor cron (`/var/log/noralvoice/postgres-alerts.log`) writes an entry

The monitor catches the first three automatically. Check `tail -20 /var/log/noralvoice/postgres-alerts.log` first.

## Detection signature (what to look for)

```sql
-- Compromised:
List of roles
 priv_esc | Superuser
 postgres | Superuser, ...

SELECT evtname, evtfoid::regprocedure FROM pg_event_trigger;
 log_start | escalate_priv()
 log_end   | escalate_priv()
```

The `priv_esc` role + `escalate_priv()` event triggers are a self-healing trap: dropping the role fires the trigger, which re-creates it. **Don't try to clean in place. Replace the volume.**

## Phase 1 — Contain (do these in order)

1. **Kill the postgres container immediately** (stops any miner / RCE):

   ```bash
   docker kill dograh-postgres-1
   ```

2. **Snapshot evidence** (read-only copy of the volume + full logs):

   ```bash
   INCIDENT_DIR=/root/incident-$(date -u +%Y-%m-%d)
   mkdir -p "$INCIDENT_DIR"
   docker logs dograh-postgres-1 > "$INCIDENT_DIR/postgres-full.log" 2>&1
   docker run --rm \
     -v dograh_postgres_data:/data:ro \
     -v "$INCIDENT_DIR":/backup \
     alpine tar czf /backup/postgres-volume-snapshot.tgz -C / data
   ```

3. **Extract any miner binaries** before container removal (useful for IOC sharing):

   ```bash
   docker cp dograh-postgres-1:/tmp/init "$INCIDENT_DIR/miner-init.bin" 2>/dev/null || true
   docker cp dograh-postgres-1:/tmp/mysql "$INCIDENT_DIR/miner-mysql.bin" 2>/dev/null || true
   sha256sum "$INCIDENT_DIR"/miner-*.bin
   ```

4. **Verify nothing is publicly exposed.** Ports 5432/6379/2000/8000/3010 should NOT appear in:

   ```bash
   ss -tlnp | grep -vE '127.0.0.1|systemd-resolve'
   ```

   If they do, this is how the attacker got in (or a separate door is open). Fix before continuing — see "Port exposure" in this repo's compose.

## Phase 2 — Rebuild postgres clean

5. **Quarantine the compromised volume** (rename via copy):

   ```bash
   QUARANTINE="dograh_postgres_data_quarantine_$(date -u +%Y_%m_%d)"
   docker volume create "$QUARANTINE"
   docker run --rm \
     -v dograh_postgres_data:/source:ro \
     -v "$QUARANTINE":/dest \
     alpine sh -c 'cp -a /source/. /dest/'
   docker rm -f dograh-postgres-1 2>/dev/null
   docker volume rm dograh_postgres_data
   ```

6. **Rotate all secrets**:

   ```bash
   cd /root/NoralVoice
   cp .env .env.bak.incident-$(date -u +%Y-%m-%d)
   NEW_PG_PW=$(openssl rand -hex 32)
   NEW_REDIS_PW=$(openssl rand -hex 32)
   NEW_JWT=$(openssl rand -hex 32)
   sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$NEW_PG_PW|" .env
   sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$NEW_REDIS_PW|" .env
   sed -i "s|^OSS_JWT_SECRET=.*|OSS_JWT_SECRET=$NEW_JWT|" .env
   ```

7. **Bring up fresh postgres** (alembic auto-runs from api startup):

   ```bash
   docker compose -p dograh --env-file .env up -d postgres
   sleep 8
   docker exec dograh-postgres-1 psql -U "$POSTGRES_USER" -c '\du'  # should show only your app user
   docker compose -p dograh --env-file .env up -d api
   sleep 15
   docker exec dograh-postgres-1 psql -U "$POSTGRES_USER" -c '\dt' | wc -l  # should be ~30+ tables
   ```

## Phase 3 — Salvage data from quarantine

8. **Spin up a temp postgres on the quarantine volume** (no exposed ports, isolated):

   ```bash
   docker run -d --name temp-pg-quarantine \
     -v "$QUARANTINE":/var/lib/postgresql/data \
     pgvector/pgvector:pg17
   sleep 3
   ```

9. **Dump app data only** (NEVER include functions / triggers / event triggers):

   ```bash
   docker exec temp-pg-quarantine pg_dump -U postgres \
     --data-only --schema=public --disable-triggers \
     --no-owner --no-privileges \
     --exclude-table=alembic_version \
     postgres > "$INCIDENT_DIR/data-only.sql"
   ```

10. **Scan the dump for attacker IOCs** — should return zero:

    ```bash
    grep -iEc 'priv_esc|escalate_priv|FROM PROGRAM|kunt' "$INCIDENT_DIR/data-only.sql"
    ```

11. **Import into the fresh DB**:

    ```bash
    docker exec -i dograh-postgres-1 psql -U "$POSTGRES_USER" -d postgres < "$INCIDENT_DIR/data-only.sql"
    docker exec dograh-postgres-1 psql -U "$POSTGRES_USER" -c \
      'SELECT (SELECT count(*) FROM users) u, (SELECT count(*) FROM workflows) w'
    docker rm -f temp-pg-quarantine
    ```

12. **Bring up UI, smoke test**:

    ```bash
    docker compose -p dograh --env-file .env up -d ui
    sleep 8
    curl -fsS https://voice.noral.ai/api/v1/health
    ```

## Phase 4 — Rotate user-facing creds (only you can do these)

Anything stored in the DB before the breach is potentially exfiltrated. Walk every external system that had creds in `user_configurations`, `telephony_configurations`, `external_credentials`, `integrations`, `api_keys`:

- **Twilio / Telnyx / Plivo** auth tokens — financial loss risk, rotate **first**
- **AI provider API keys** (only if not using Dograh-managed providers): OpenAI, Anthropic, Deepgram, ElevenLabs, Cartesia, etc.
- **Google OAuth client secret** (GCP Console → APIs & Services → Credentials)
- **Dograh API keys** in the UI's Settings → API Keys (regenerate, distribute new key to consumers)

## What's already in place (don't redo)

The 2026-05-17 incident installed these defenses; they remain active:

- `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `OSS_JWT_SECRET`, MinIO creds — env-var driven, no defaults in compose
- `POSTGRES_USER` — randomized, no longer the literal string `postgres`
- Postgres / Redis / MinIO ports removed from external mapping
- `api:8000` / `ui:3010` bound to `127.0.0.1` (nginx-only access)
- UFW deny on 5432 / 6379 / 2000 (defense in depth)
- nginx `limit_req` on `/api/v1/auth/*` (10 req/min/IP) and `/api/v1/*` (30 req/s/IP)
- Postgres role/trigger/auth-failure monitor cron (`/root/monitors/postgres-sanity.sh`, every 5 min)
- Daily encrypted pg_dump backup cron (`/root/monitors/postgres-backup.sh`, 03:17 UTC, 30-day retention)
- Restore companion at `/root/monitors/postgres-restore.sh`

## Off-host backups (TODO)

`/root/backups/` is on-host only. Add off-host upload to `postgres-backup.sh`. Suggestions in the script comments. Until then, manually copy a recent backup off-server periodically.

## When NOT to use this runbook

- If postgres is healthy and the issue is application-level (api crashing, migrations failing): debug normally, don't recreate volumes.
- If you suspect host-level compromise (suspicious processes outside docker, unknown SSH keys, modified `/etc/passwd`): this runbook isn't enough — treat the host as untrusted and rebuild from a fresh image.

## Incident artifacts from 2026-05-17

Preserved at `/root/incident-2026-05-17/` on the server:

- `postgres-volume-snapshot.tgz` — full DB at compromise
- `postgres-full.log` — 2,643 lines of attack logs
- `miner-init.bin` / `miner-mysql.bin` — extracted miner binaries
- `data-only-quarantine.sql` — the data we reimported
- `new-secrets.txt` — rotated secret values (root-only)
- `pre-d1-rename-data.sql` — secondary dump from postgres-user-rename step

Quarantined Docker volumes:
- `dograh_postgres_data_quarantine_2026_05_17` — compromised DB at first contain
- `dograh_postgres_data_pre_d1_2026_05_18` — post-Phase-2, pre-user-rename
