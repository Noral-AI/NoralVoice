# Noral deployment customizations

This directory tracks the customizations applied to the Dograh stack as
deployed at `voice.noral.ai` (server: `129.121.101.154`).

The upstream `docker-compose.yaml` in the repo root is left untouched so
this fork can sync cleanly from `dograh-hq/dograh`. The deployed compose
lives here as a tracked snapshot.

## What changed vs. upstream

Three deliberate edits to upstream's `docker-compose.yaml` for the remote
prebuilt deployment:

1. **Removed the `cloudflared` service** (and the `api` service's
   `depends_on: cloudflared` block).
   Upstream's default compose launches a free Cloudflare "quick tunnel"
   that exposes the API at a public `*.trycloudflare.com` URL — anonymous,
   ephemeral, and bypassing nginx + our firewall + Let's Encrypt cert.
   Not appropriate for production. We reach the API only through
   `nginx_https` on 443.

2. **Set `HOSTNAME: "0.0.0.0"` in the `ui` service's `environment`.**
   The Next.js standalone server in the upstream UI image binds to the
   container's hostname (the container ID), which only resolves to the
   container's eth0 IP — never to `127.0.0.1` or `::1`. Forcing
   `HOSTNAME=0.0.0.0` makes Next.js listen on all interfaces, which is
   required for the in-container healthcheck (and is the conventional
   behavior for containerized servers).

3. **Healthcheck for `ui` uses `http://127.0.0.1:3010`** instead of
   `http://localhost:3010`. With (2) above, both work, but `127.0.0.1`
   is unambiguous (no IPv6 fallback to `::1` where Next.js doesn't listen).

## How the deployment is structured on the server

```
/root/NoralVoice/                  <-- this fork, cloned on the server
├── docker-compose.yaml            <-- upstream's, used only as reference
├── scripts/setup_remote.sh        <-- upstream installer
└── dograh/                        <-- created by setup_remote.sh; what actually runs
    ├── docker-compose.yaml        <-- has the 3 edits above applied
    ├── docker-compose.yaml.bak-pre-cloudflared-removal
    ├── .env                       <-- secrets; NEVER commit
    ├── certs/                     <-- self-signed initially; replaced with Let's Encrypt
    ├── remote_up.sh
    └── ...
```

Start / stop / status:

```sh
cd /root/NoralVoice/dograh
./remote_up.sh        # start
docker compose ps     # status
docker compose down   # stop (preserves volumes)
```

## If you ever rebuild from scratch

`setup_remote.sh` in `prebuilt` mode downloads `docker-compose.yaml`
directly from `dograh-hq/dograh@main`, so it will pull in the
cloudflared service again. After a fresh `setup_remote.sh` run but
before the first `./remote_up.sh`, apply our customizations:

```sh
cp /root/NoralVoice/deploy/noral/docker-compose.yaml /root/NoralVoice/dograh/docker-compose.yaml
```

Or run the helper:

```sh
/root/NoralVoice/deploy/noral/redeploy.sh
```

## Server-level configuration (not in compose)

The following are configured on the host directly (not in this repo) and
should be reapplied if rebuilding the server:

- **UFW firewall** — TCP 22/80/443/3478/5349, UDP 3478/5349/49152–49200
- **4 GB swap** at `/swapfile`, `vm.swappiness=10`
- **Docker CE** via the official `get.docker.com` script
- **Let's Encrypt cert for `voice.noral.ai`** issued via `certbot certonly --standalone`,
  copied into `/root/NoralVoice/dograh/certs/local.{crt,key}`,
  renewal hook at `/etc/letsencrypt/renewal-hooks/deploy/dograh-reload.sh`

## Secrets

`.env` on the server contains the auto-generated TURN shared secret and
other deployment-specific values. It is **not** committed to this repo
and should never be. If you need a copy for backup, store it in a
secrets manager — not in git.
