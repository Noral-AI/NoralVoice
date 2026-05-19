#!/usr/bin/env bash

NORAL_DEPLOY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORAL_DEPLOY_REPO_ROOT="$(cd "$NORAL_DEPLOY_LIB_DIR/../.." 2>/dev/null && pwd || true)"

: "${RED:=\033[0;31m}"
: "${GREEN:=\033[0;32m}"
: "${YELLOW:=\033[1;33m}"
: "${BLUE:=\033[0;34m}"
: "${NC:=\033[0m}"

noral_info() {
    echo -e "${BLUE}$*${NC}"
}

noral_success() {
    echo -e "${GREEN}$*${NC}"
}

noral_warn() {
    echo -e "${YELLOW}$*${NC}"
}

noral_fail() {
    echo -e "${RED}Error: $*${NC}" >&2
    exit 1
}

noral_project_dir() {
    if [[ -n "${NORAL_DEPLOY_PROJECT_DIR:-}" ]]; then
        printf '%s\n' "$NORAL_DEPLOY_PROJECT_DIR"
    else
        pwd
    fi
}

noral_template_path() {
    local template_name=$1
    local candidate=""
    local project_dir

    project_dir="$(noral_project_dir)"

    for candidate in \
        "$project_dir/deploy/templates/$template_name" \
        "$NORAL_DEPLOY_REPO_ROOT/deploy/templates/$template_name"
    do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    noral_fail "Template '$template_name' not found"
}

noral_init_script_path() {
    local candidate=""
    local project_dir

    project_dir="$(noral_project_dir)"

    for candidate in \
        "$project_dir/scripts/run_init.sh" \
        "$NORAL_DEPLOY_REPO_ROOT/scripts/run_init.sh"
    do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    noral_fail "run_init.sh not found"
}

noral_load_env_file() {
    local env_file=${1:-.env}

    [[ -f "$env_file" ]] || noral_fail "$env_file not found"

    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
}

noral_host_from_url() {
    local url=$1

    url="${url#https://}"
    url="${url#http://}"
    url="${url%%/*}"

    printf '%s\n' "$url"
}

noral_is_ipv4() {
    [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

noral_infer_server_ip() {
    local project_dir=${1:-$(noral_project_dir)}
    local turn_conf="$project_dir/turnserver.conf"
    local ip=""

    if [[ -n "${SERVER_IP:-}" ]]; then
        printf '%s\n' "$SERVER_IP"
        return 0
    fi

    if [[ -f "$turn_conf" ]]; then
        ip="$(sed -n 's/^external-ip=//p' "$turn_conf" | head -1)"
        if [[ -n "$ip" ]]; then
            printf '%s\n' "$ip"
            return 0
        fi
    fi

    if [[ -n "${TURN_HOST:-}" ]] && noral_is_ipv4 "$TURN_HOST"; then
        printf '%s\n' "$TURN_HOST"
        return 0
    fi

    if [[ -n "${PUBLIC_HOST:-}" ]] && noral_is_ipv4 "$PUBLIC_HOST"; then
        printf '%s\n' "$PUBLIC_HOST"
        return 0
    fi

    return 1
}

noral_infer_public_base_url() {
    if [[ -n "${PUBLIC_BASE_URL:-}" ]]; then
        printf '%s\n' "${PUBLIC_BASE_URL%/}"
        return 0
    fi

    if [[ -n "${BACKEND_API_ENDPOINT:-}" ]]; then
        printf '%s\n' "${BACKEND_API_ENDPOINT%/}"
        return 0
    fi

    if [[ -n "${PUBLIC_HOST:-}" ]]; then
        printf 'https://%s\n' "$PUBLIC_HOST"
        return 0
    fi

    if [[ -n "${SERVER_IP:-}" ]]; then
        printf 'https://%s\n' "$SERVER_IP"
        return 0
    fi

    return 1
}

noral_infer_public_host() {
    local public_base_url=""

    if [[ -n "${PUBLIC_HOST:-}" ]]; then
        printf '%s\n' "$PUBLIC_HOST"
        return 0
    fi

    public_base_url="$(noral_infer_public_base_url 2>/dev/null || true)"
    if [[ -n "$public_base_url" ]]; then
        noral_host_from_url "$public_base_url"
        return 0
    fi

    if [[ -n "${TURN_HOST:-}" ]]; then
        printf '%s\n' "$TURN_HOST"
        return 0
    fi

    return 1
}

noral_set_env_key() {
    local env_file=$1
    local key=$2
    local value=$3
    local tmp_file="${env_file}.tmp.$$"

    awk -v key="$key" -v value="$value" '
        BEGIN { updated = 0 }
        $0 ~ "^" key "=" {
            print key "=" value
            updated = 1
            next
        }
        { print }
        END {
            if (!updated) {
                print key "=" value
            }
        }
    ' "$env_file" > "$tmp_file"

    mv "$tmp_file" "$env_file"
}

noral_delete_env_key() {
    local env_file=$1
    local key=$2
    local tmp_file="${env_file}.tmp.$$"

    awk -v key="$key" '$0 !~ "^" key "=" { print }' "$env_file" > "$tmp_file"
    mv "$tmp_file" "$env_file"
}

noral_sync_remote_env_file() {
    local env_file=${1:-.env}
    local project_dir
    local public_base_url=""
    local public_host=""
    local server_ip=""

    project_dir="$(cd "$(dirname "$env_file")" && pwd)"
    noral_load_env_file "$env_file"

    public_base_url="$(noral_infer_public_base_url)" || noral_fail "Could not determine PUBLIC_BASE_URL"
    public_base_url="${public_base_url%/}"
    public_host="$(noral_infer_public_host)" || noral_fail "Could not determine PUBLIC_HOST"
    server_ip="$(noral_infer_server_ip "$project_dir")" || noral_fail "Could not determine SERVER_IP"

    [[ "$public_base_url" =~ ^https?:// ]] || noral_fail "PUBLIC_BASE_URL must include http:// or https://"
    noral_is_ipv4 "$server_ip" || noral_fail "SERVER_IP must be an IPv4 address (got: $server_ip)"

    noral_set_env_key "$env_file" ENVIRONMENT "${ENVIRONMENT:-production}"
    noral_set_env_key "$env_file" SERVER_IP "$server_ip"
    noral_set_env_key "$env_file" PUBLIC_HOST "$public_host"
    noral_set_env_key "$env_file" PUBLIC_BASE_URL "$public_base_url"
    noral_set_env_key "$env_file" BACKEND_API_ENDPOINT "$public_base_url"
    noral_set_env_key "$env_file" MINIO_PUBLIC_ENDPOINT "$public_base_url"
    noral_set_env_key "$env_file" TURN_HOST "$public_host"
}

noral_validate_remote_runtime_env() {
    [[ "${FASTAPI_WORKERS:-}" =~ ^[1-9][0-9]*$ ]] || noral_fail "FASTAPI_WORKERS must be a positive integer"
    [[ -n "${TURN_SECRET:-}" ]] || noral_fail "TURN_SECRET is missing"
    [[ -n "${PUBLIC_HOST:-}" ]] || noral_fail "PUBLIC_HOST is missing"
    [[ -n "${PUBLIC_BASE_URL:-}" ]] || noral_fail "PUBLIC_BASE_URL is missing"
    [[ -n "${BACKEND_API_ENDPOINT:-}" ]] || noral_fail "BACKEND_API_ENDPOINT is missing"
    [[ -n "${MINIO_PUBLIC_ENDPOINT:-}" ]] || noral_fail "MINIO_PUBLIC_ENDPOINT is missing"
    [[ -n "${TURN_HOST:-}" ]] || noral_fail "TURN_HOST is missing"
    noral_is_ipv4 "${SERVER_IP:-}" || noral_fail "SERVER_IP must be a valid IPv4 address"
    [[ "${PUBLIC_BASE_URL}" =~ ^https?:// ]] || noral_fail "PUBLIC_BASE_URL must include http:// or https://"
    [[ "${BACKEND_API_ENDPOINT}" == "${PUBLIC_BASE_URL}" ]] || noral_fail "BACKEND_API_ENDPOINT must match PUBLIC_BASE_URL"
    [[ "${MINIO_PUBLIC_ENDPOINT}" == "${PUBLIC_BASE_URL}" ]] || noral_fail "MINIO_PUBLIC_ENDPOINT must match PUBLIC_BASE_URL"
    [[ "${TURN_HOST}" == "${PUBLIC_HOST}" ]] || noral_fail "TURN_HOST must match PUBLIC_HOST"
}

noral_uses_init_compose_layout() {
    local project_dir=${1:-$(noral_project_dir)}
    local compose_file="$project_dir/docker-compose.yaml"

    [[ -f "$compose_file" ]] || return 1
    grep -q "noral-init:" "$compose_file" \
        && grep -q "nginx-generated:/etc/nginx/conf.d:ro" "$compose_file" \
        && grep -q "coturn-generated:/etc/coturn:ro" "$compose_file"
}

noral_require_init_compose_layout() {
    local project_dir=${1:-$(noral_project_dir)}

    if ! noral_uses_init_compose_layout "$project_dir"; then
        noral_fail "This install uses the legacy remote compose layout. Run ./update_remote.sh first so Docker uses noral-init generated config."
    fi
}

noral_render_remote_nginx_conf() {
    local project_dir=${1:-$(noral_project_dir)}
    local destination=${2:-"$project_dir/nginx.conf"}
    local template=""
    local tmp_upstream=""

    template="$(noral_template_path "nginx.remote.conf.template")"
    tmp_upstream="$(mktemp)"

    {
        echo "# Backend API workers - one uvicorn process per port, balanced by least_conn."
        echo "# Auto-generated by Noral remote config renderer. Do not edit manually."
        echo "upstream noral_api {"
        echo "    least_conn;"
        for ((i=0; i<FASTAPI_WORKERS; i++)); do
            printf '    server api:%d max_fails=3 fail_timeout=10s;\n' "$((8000 + i))"
        done
        echo "    keepalive 32;"
        echo "}"
    } > "$tmp_upstream"

    awk -v public_host="$PUBLIC_HOST" -v upstream_file="$tmp_upstream" '
        BEGIN {
            while ((getline line < upstream_file) > 0) {
                upstream = upstream line ORS
            }
            close(upstream_file)
        }
        {
            gsub(/__NORAL_PUBLIC_HOST__/, public_host)
            if ($0 == "__NORAL_UPSTREAM_BLOCK__") {
                printf "%s", upstream
            } else {
                print
            }
        }
    ' "$template" > "$destination"

    rm -f "$tmp_upstream"
}

noral_render_remote_turn_conf() {
    local project_dir=${1:-$(noral_project_dir)}
    local destination=${2:-"$project_dir/turnserver.conf"}
    local template=""
    local external_ip="${TURN_EXTERNAL_IP:-${SERVER_IP:-}}"

    template="$(noral_template_path "turnserver.remote.conf.template")"
    [[ -n "$external_ip" ]] || noral_fail "TURN external IP/host is missing"

    awk \
        -v external_ip="$external_ip" \
        -v turn_secret="$TURN_SECRET" \
        '
        {
            gsub(/__NORAL_TURN_EXTERNAL_IP__/, external_ip)
            gsub(/__NORAL_TURN_SECRET__/, turn_secret)
            print
        }
    ' "$template" > "$destination"
}

noral_preflight_remote_init_render() {
    local project_dir=${1:-$(noral_project_dir)}
    local env_file="$project_dir/.env"
    local cert_dir="$project_dir/certs"
    local init_script=""
    local tmp_root=""
    local nginx_conf=""
    local turn_conf=""
    local nginx_workers=0
    local rendered_secret=""
    local rendered_ip=""
    local rendered_server_name=""

    noral_load_env_file "$env_file"
    noral_validate_remote_runtime_env
    [[ -f "$cert_dir/local.crt" ]] || noral_fail "certs/local.crt not found"
    [[ -f "$cert_dir/local.key" ]] || noral_fail "certs/local.key not found"

    init_script="$(noral_init_script_path)"
    tmp_root="$(mktemp -d)"
    nginx_conf="$tmp_root/nginx/default.conf"
    turn_conf="$tmp_root/coturn/turnserver.conf"

    (
        export ENVIRONMENT SERVER_IP PUBLIC_HOST PUBLIC_BASE_URL BACKEND_API_ENDPOINT MINIO_PUBLIC_ENDPOINT TURN_HOST TURN_SECRET FASTAPI_WORKERS
        export NORAL_INIT_WORKSPACE_DIR="$project_dir"
        export NORAL_INIT_OUTPUT_ROOT="$tmp_root"
        export NORAL_INIT_CERTS_DIR="$cert_dir"
        bash "$init_script" >/dev/null
    )

    [[ -f "$nginx_conf" ]] || noral_fail "noral-init did not render nginx config"
    [[ -f "$turn_conf" ]] || noral_fail "noral-init did not render coturn config"

    nginx_workers=$(awk '/^[[:space:]]*server api:[0-9]+/ { count += 1 } END { print count + 0 }' "$nginx_conf")
    [[ "$nginx_workers" -eq "$FASTAPI_WORKERS" ]] || noral_fail "FASTAPI_WORKERS=$FASTAPI_WORKERS but nginx.conf has $nginx_workers upstream servers"

    rendered_server_name="$(awk '/^[[:space:]]*server_name / { print $2; exit }' "$nginx_conf" | sed 's/;$//')"
    [[ "$rendered_server_name" == "$PUBLIC_HOST" ]] || noral_fail "nginx.conf server_name ($rendered_server_name) does not match PUBLIC_HOST ($PUBLIC_HOST)"

    rendered_secret="$(sed -n 's/^static-auth-secret=//p' "$turn_conf" | head -1)"
    [[ "$rendered_secret" == "$TURN_SECRET" ]] || noral_fail "TURN_SECRET in .env does not match turnserver.conf"

    rendered_ip="$(sed -n 's/^external-ip=//p' "$turn_conf" | head -1)"
    [[ "$rendered_ip" == "$SERVER_IP" ]] || noral_fail "SERVER_IP in .env does not match turnserver.conf"

    rm -rf "$tmp_root"
}

noral_prepare_remote_install() {
    local project_dir=${1:-$(noral_project_dir)}
    local env_file="$project_dir/.env"

    noral_sync_remote_env_file "$env_file"
    noral_require_init_compose_layout "$project_dir"
    noral_preflight_remote_init_render "$project_dir"
}

noral_download_bundle_file_for_ref() {
    local destination=$1
    local remote_path=$2
    local ref=${3:-main}
    local raw_base="https://raw.githubusercontent.com/noral-hq/dograh/$ref"
    local fallback_base="https://raw.githubusercontent.com/noral-hq/dograh/main"

    if ! curl -fsSL -o "$destination" "$raw_base/$remote_path"; then
        noral_warn "Warning: '$remote_path' not found at '$ref' - falling back to main"
        curl -fsSL -o "$destination" "$fallback_base/$remote_path"
    fi
}

noral_download_init_support_bundle() {
    local project_dir=$1
    local ref=${2:-main}

    mkdir -p "$project_dir/scripts/lib" "$project_dir/deploy/templates"

    mkdir -p "$project_dir/scripts"
    noral_download_bundle_file_for_ref "$project_dir/scripts/lib/setup_common.sh" "scripts/lib/setup_common.sh" "$ref"
    noral_download_bundle_file_for_ref "$project_dir/scripts/run_init.sh" "scripts/run_init.sh" "$ref"
    chmod +x "$project_dir/scripts/run_init.sh"
    noral_download_bundle_file_for_ref "$project_dir/deploy/templates/nginx.remote.conf.template" "deploy/templates/nginx.remote.conf.template" "$ref"
    noral_download_bundle_file_for_ref "$project_dir/deploy/templates/turnserver.remote.conf.template" "deploy/templates/turnserver.remote.conf.template" "$ref"
}

noral_download_remote_support_bundle() {
    local project_dir=$1
    local ref=${2:-main}

    noral_download_bundle_file_for_ref "$project_dir/remote_up.sh" "remote_up.sh" "$ref"
    chmod +x "$project_dir/remote_up.sh"
    noral_download_init_support_bundle "$project_dir" "$ref"
}
