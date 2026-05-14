#!/bin/bash
# Apply Noral deployment customizations on top of a fresh upstream setup_remote.sh install.
# Intended to be run AFTER setup_remote.sh has created /root/NoralVoice/dograh/
# and BEFORE the first ./remote_up.sh.
#
# Idempotent: safe to re-run; backs up the previous compose first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="/root/NoralVoice/dograh"
NORAL_COMPOSE="$SCRIPT_DIR/docker-compose.yaml"
DEPLOYED_COMPOSE="$DEPLOY_DIR/docker-compose.yaml"

if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "ERROR: $DEPLOY_DIR not found. Run scripts/setup_remote.sh first." >&2
    exit 1
fi

if [[ ! -f "$NORAL_COMPOSE" ]]; then
    echo "ERROR: $NORAL_COMPOSE missing from this checkout." >&2
    exit 1
fi

if [[ -f "$DEPLOYED_COMPOSE" ]]; then
    backup="${DEPLOYED_COMPOSE}.bak-$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$DEPLOYED_COMPOSE" "$backup"
    echo "Backed up existing compose to $backup"
fi

cp "$NORAL_COMPOSE" "$DEPLOYED_COMPOSE"
echo "Installed Noral-customized docker-compose.yaml at $DEPLOYED_COMPOSE"

cd "$DEPLOY_DIR"
docker compose config -q
echo "Compose syntax validates OK."
echo
echo "Next: cd $DEPLOY_DIR && ./remote_up.sh"
