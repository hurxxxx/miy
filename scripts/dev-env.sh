#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

dev_python_bin() {
  local python_bin="${ROOT_DIR}/apps/api/.venv/bin/python"
  if [[ -x "$python_bin" ]]; then
    printf '%s\n' "$python_bin"
  else
    command -v python3
  fi
}

dev_load_dotenv() {
  local env_file="${1:?env file is required}"
  [[ -f "$env_file" ]] || return 0

  local python_bin
  python_bin="$(dev_python_bin)"

  eval "$(
    DEV_ENV_FILE="$env_file" "$python_bin" - <<'PY'
import os
import pathlib
import shlex

path = pathlib.Path(os.environ["DEV_ENV_FILE"])
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key == "MTY_ENV_PROFILE" and key in os.environ:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(f"export {key}={shlex.quote(value)}")
PY
  )"
}

dev_export_mty_desktop_installer_defaults() {
  local python_bin
  python_bin="$(dev_python_bin)"

  eval "$(
    ROOT_DIR="$ROOT_DIR" "$python_bin" - <<'PY'
import json
import os
import pathlib
import shlex

root = pathlib.Path(os.environ["ROOT_DIR"])
manifest = json.loads(
    (root / "packages" / "contracts" / "mty-desktop-update-feed.manifest.json").read_text(
        encoding="utf-8"
    )
)
feed_path_prefix = manifest["feedPathPrefix"]
win_env_name = None
win_default_url = None

for platform in manifest["platformOrder"]:
    config = manifest["platforms"][platform]
    env_name = config["installerUrlEnv"]
    default_url = f'{feed_path_prefix}/{platform}/{config["installerStableCopy"]}'
    if not os.environ.get(env_name):
        print(f"export {env_name}={shlex.quote(default_url)}")
    if platform == "win":
        win_env_name = env_name
        win_default_url = default_url

fallback_url = os.environ.get(str(win_env_name)) if win_env_name else win_default_url
if not fallback_url:
    fallback_url = win_default_url
if fallback_url and not os.environ.get("VITE_MTY_DESKTOP_INSTALLER_URL"):
    print(f"export VITE_MTY_DESKTOP_INSTALLER_URL={shlex.quote(fallback_url)}")
PY
  )"
}

dev_lower() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

if [[ "${MTY_SKIP_DOTENV:-0}" != "1" ]]; then
  dev_load_dotenv "$ROOT_DIR/.env"
fi

export MTY_DEV_API_COUNT="${MTY_DEV_API_COUNT:-1}"
export MTY_DEV_API_HOST="${MTY_DEV_API_HOST:-127.0.0.1}"
export MTY_WEB_DEV_HOST="${MTY_WEB_DEV_HOST:-127.0.0.1}"
export MTY_INFRA_CONTAINER_PREFIX="${MTY_INFRA_CONTAINER_PREFIX:-mty-dev}"
export MTY_INFRA_BIND_HOST="${MTY_INFRA_BIND_HOST:-127.0.0.1}"
export MTY_INFRA_NGINX_PORT="${MTY_INFRA_NGINX_PORT:-14200}"
export MTY_INFRA_REDIS_PORT="${MTY_INFRA_REDIS_PORT:-56380}"
export MTY_INFRA_POSTGRES_DB="${MTY_INFRA_POSTGRES_DB:-mty_dev}"
export MTY_INFRA_POSTGRES_PASSWORD="${MTY_INFRA_POSTGRES_PASSWORD:-mty_dev}"
export MTY_INFRA_POSTGRES_PORT="${MTY_INFRA_POSTGRES_PORT:-55433}"
export MTY_INFRA_POSTGRES_USER="${MTY_INFRA_POSTGRES_USER:-mty_dev}"
export MTY_INFRA_USE_LOCAL_POSTGRES="${MTY_INFRA_USE_LOCAL_POSTGRES:-auto}"
export MTY_DEV_REDIS_URL="${MTY_DEV_REDIS_URL:-redis://127.0.0.1:${MTY_INFRA_REDIS_PORT}/0}"
export MTY_DEV_REDIS_RESULT_BACKEND="${MTY_DEV_REDIS_RESULT_BACKEND:-redis://127.0.0.1:${MTY_INFRA_REDIS_PORT}/1}"
export MTY_DEV_COLLAB_REDIS_URL="${MTY_DEV_COLLAB_REDIS_URL:-$MTY_DEV_REDIS_URL}"
export MTY_DEV_REALTIME_REDIS_URL="${MTY_DEV_REALTIME_REDIS_URL:-$MTY_DEV_REDIS_URL}"
export MTY_DEV_WORKER_BROKER_URL="${MTY_DEV_WORKER_BROKER_URL:-$MTY_DEV_REDIS_URL}"
export MTY_DEV_WORKER_RESULT_BACKEND="${MTY_DEV_WORKER_RESULT_BACKEND:-$MTY_DEV_REDIS_RESULT_BACKEND}"
export MTY_INFRA_MINIO_PORT="${MTY_INFRA_MINIO_PORT:-59010}"
export MTY_INFRA_MINIO_CONSOLE_PORT="${MTY_INFRA_MINIO_CONSOLE_PORT:-59011}"
export MTY_INFRA_OPENSEARCH_PORT="${MTY_INFRA_OPENSEARCH_PORT:-59210}"
export MTY_INFRA_OPENSEARCH_PERF_PORT="${MTY_INFRA_OPENSEARCH_PERF_PORT:-59610}"
export MTY_INFRA_QDRANT_PORT="${MTY_INFRA_QDRANT_PORT:-16333}"
export MTY_INFRA_QDRANT_GRPC_PORT="${MTY_INFRA_QDRANT_GRPC_PORT:-16334}"
export MTY_BENTO_BIND_HOST="${MTY_BENTO_BIND_HOST:-127.0.0.1}"
export MTY_BENTO_IMAGE_TAG="${MTY_BENTO_IMAGE_TAG:-1.0.17}"
export MTY_BENTO_PORT="${MTY_BENTO_PORT:-18084}"
export MTY_BENTO_SERVER_URL="${MTY_BENTO_SERVER_URL:-http://127.0.0.1:${MTY_BENTO_PORT}/}"
if [[ -z "${MTY_HERMES_ENABLED+x}" ]]; then
  if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    export MTY_HERMES_ENABLED=true
  else
    export MTY_HERMES_ENABLED=false
  fi
fi
export MTY_HERMES_RUNTIME_PORT="${MTY_HERMES_RUNTIME_PORT:-18642}"
export MTY_HERMES_MANAGEMENT_PORT="${MTY_HERMES_MANAGEMENT_PORT:-19119}"
export MTY_HERMES_RUNTIME_BASE_URL="${MTY_HERMES_RUNTIME_BASE_URL:-http://127.0.0.1:${MTY_HERMES_RUNTIME_PORT}}"
export MTY_HERMES_MANAGEMENT_BASE_URL="${MTY_HERMES_MANAGEMENT_BASE_URL:-http://127.0.0.1:${MTY_HERMES_MANAGEMENT_PORT}}"
export MTY_HERMES_API_KEY="${MTY_HERMES_API_KEY:-mty-dev-hermes-runtime-key-0001}"
export MTY_HERMES_MANAGEMENT_TOKEN="${MTY_HERMES_MANAGEMENT_TOKEN:-mty-dev-hermes-management-token-0001}"
export MTY_HERMES_MCP_SHARED_SECRET="${MTY_HERMES_MCP_SHARED_SECRET:-mty-dev-hermes-mcp-shared-secret-0000000000000001}"
export MTY_HERMES_MCP_SERVER_URL="${MTY_HERMES_MCP_SERVER_URL:-http://127.0.0.1:${MTY_API_DEV_PORT:-8001}/api/v1/internal/hermes/mcp}"
export MTY_HERMES_PROFILE_CLONE_SOURCE="${MTY_HERMES_PROFILE_CLONE_SOURCE:-default}"
export MTY_HERMES_REQUEST_TIMEOUT_SECONDS="${MTY_HERMES_REQUEST_TIMEOUT_SECONDS:-30}"
export MTY_HERMES_RUN_TIMEOUT_SECONDS="${MTY_HERMES_RUN_TIMEOUT_SECONDS:-3600}"
export MTY_HERMES_DISPATCH_LEASE_SECONDS="${MTY_HERMES_DISPATCH_LEASE_SECONDS:-300}"
export MTY_LIVEKIT_PORT="${MTY_LIVEKIT_PORT:-7880}"
export MTY_LIVEKIT_RTC_TCP_PORT="${MTY_LIVEKIT_RTC_TCP_PORT:-7881}"
export MTY_LIVEKIT_RTC_PORT_RANGE_START="${MTY_LIVEKIT_RTC_PORT_RANGE_START:-52000}"
export MTY_LIVEKIT_RTC_PORT_RANGE_END="${MTY_LIVEKIT_RTC_PORT_RANGE_END:-52100}"
export MTY_INFRA_USE_LOCAL_MINIO="${MTY_INFRA_USE_LOCAL_MINIO:-auto}"
export MTY_DEV_BASE_URL="${MTY_DEV_BASE_URL:-http://127.0.0.1:${MTY_INFRA_NGINX_PORT}}"
export MTY_DEV_RUNTIME_DIR="${MTY_DEV_RUNTIME_DIR:-$ROOT_DIR/.dev}"
export MTY_DEV_PID_DIR="${MTY_DEV_PID_DIR:-$MTY_DEV_RUNTIME_DIR/pids}"
export MTY_DEV_LOG_DIR="${MTY_DEV_LOG_DIR:-$MTY_DEV_RUNTIME_DIR/logs}"
export MTY_DEV_NGINX_CONF_TEMPLATE_PATH="${MTY_DEV_NGINX_CONF_TEMPLATE_PATH:-$ROOT_DIR/ops/dev/nginx.conf.template}"
export MTY_DEV_NGINX_CONF_PATH="${MTY_DEV_NGINX_CONF_PATH:-$MTY_DEV_RUNTIME_DIR/nginx.conf}"
export MTY_ENV_PROFILE="${MTY_ENV_PROFILE:-dev}"

export MTY_POSTGRES_DSN="${MTY_POSTGRES_DSN:-postgresql+psycopg://${MTY_INFRA_POSTGRES_USER}:${MTY_INFRA_POSTGRES_PASSWORD}@127.0.0.1:${MTY_INFRA_POSTGRES_PORT}/${MTY_INFRA_POSTGRES_DB}}"
export MTY_API_COLLAB_REDIS_URL="$MTY_DEV_COLLAB_REDIS_URL"
export MTY_API_REALTIME_REDIS_URL="$MTY_DEV_REALTIME_REDIS_URL"
export MTY_WORKER_BROKER_URL="$MTY_DEV_WORKER_BROKER_URL"
export MTY_WORKER_RESULT_BACKEND="$MTY_DEV_WORKER_RESULT_BACKEND"
export MTY_MINIO_ENDPOINT="${MTY_MINIO_ENDPOINT:-http://127.0.0.1:${MTY_INFRA_MINIO_PORT}}"
export MTY_MINIO_ACCESS_KEY="${MTY_MINIO_ACCESS_KEY:-mty_dev_minio}"
export MTY_MINIO_SECRET_KEY="${MTY_MINIO_SECRET_KEY:-mty_dev_minio}"
export MTY_MINIO_BUCKET="${MTY_MINIO_BUCKET:-mty-dev}"
export MTY_OPENSEARCH_URL="${MTY_OPENSEARCH_URL:-http://127.0.0.1:${MTY_INFRA_OPENSEARCH_PORT}}"
export MTY_OPENSEARCH_INDEX_PREFIX="${MTY_OPENSEARCH_INDEX_PREFIX:-mty-dev}"
export MTY_RAG_QDRANT_URL="${MTY_RAG_QDRANT_URL:-http://127.0.0.1:${MTY_INFRA_QDRANT_PORT}}"
export MTY_RAG_QDRANT_API_KEY="${MTY_RAG_QDRANT_API_KEY:-mty_dev_qdrant}"
export MTY_RAG_QDRANT_COLLECTION_PREFIX="${MTY_RAG_QDRANT_COLLECTION_PREFIX:-mty-dev-rag}"
export MTY_LIVEKIT_URL="${MTY_LIVEKIT_URL:-ws://127.0.0.1:${MTY_LIVEKIT_PORT}}"
export MTY_LIVEKIT_PUBLIC_URL="${MTY_LIVEKIT_PUBLIC_URL:-}"
export MTY_LIVEKIT_API_KEY="${MTY_LIVEKIT_API_KEY:-devkey}"
export MTY_LIVEKIT_API_SECRET="${MTY_LIVEKIT_API_SECRET:-devsecret-devsecret-devsecret-0001}"
export MTY_LLM_HEALTHCHECK_ON_STARTUP="${MTY_LLM_HEALTHCHECK_ON_STARTUP:-0}"
export MTY_LLM_REQUIRED="${MTY_LLM_REQUIRED:-0}"
export MTY_API_ALLOW_DEV_ADMIN_LOGIN="${MTY_API_ALLOW_DEV_ADMIN_LOGIN:-1}"
export MTY_API_OBJECT_STORAGE_REQUIRED="${MTY_API_OBJECT_STORAGE_REQUIRED:-1}"
export MTY_API_SEED_DEV_LOGIN_ACCOUNT="${MTY_API_SEED_DEV_LOGIN_ACCOUNT:-1}"
dev_export_mty_desktop_installer_defaults

dev_docker() {
  case "$MTY_ENV_PROFILE" in
    local|dev|"")
      if docker info >/dev/null 2>&1; then
        docker "$@"
      elif command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
        sudo -n docker "$@"
      else
        docker "$@"
      fi
      ;;
    prod|production)
      echo "[dev] MTY_ENV_PROFILE=$MTY_ENV_PROFILE is not supported for dev docker commands" >&2
      return 1
      ;;
    *)
      echo "[dev] invalid MTY_ENV_PROFILE: $MTY_ENV_PROFILE (expected local, dev, prod)" >&2
      return 1
      ;;
  esac
}

dev_docker_available() {
  dev_docker info >/dev/null 2>&1
}

dev_compose_file() {
  case "$MTY_ENV_PROFILE" in
    local|dev|"")
      printf '%s/ops/compose/mty-dev.infra.yml\n' "$ROOT_DIR"
      ;;
    prod|production)
      echo "[dev] MTY_ENV_PROFILE=$MTY_ENV_PROFILE is not supported for dev compose commands" >&2
      return 1
      ;;
    *)
      echo "[dev] invalid MTY_ENV_PROFILE: $MTY_ENV_PROFILE (expected local, dev, prod)" >&2
      return 1
      ;;
  esac
}

dev_compose_env_file() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    printf '%s/.env\n' "$ROOT_DIR"
  else
    printf '%s/.env.example\n' "$ROOT_DIR"
  fi
}

dev_api_port() {
  local index="${1:?instance index is required}"
  printf '%s\n' "$((8000 + index))"
}

dev_api_name() {
  local index="${1:?instance index is required}"
  printf 'dev-api-%s\n' "$index"
}

dev_ensure_runtime_dirs() {
  mkdir -p "$MTY_DEV_RUNTIME_DIR" "$MTY_DEV_PID_DIR" "$MTY_DEV_LOG_DIR"
}

dev_detect_api_upstream_host() {
  dev_docker run --rm --add-host=dev-host:host-gateway nginx:1.27-alpine \
    sh -lc "grep -m1 -E '^[0-9]+(\\.[0-9]+){3}[[:space:]]+dev-host([[:space:]]|\$)' /etc/hosts | awk '{print \$1}'"
}

dev_render_nginx_conf() {
  dev_ensure_runtime_dirs
  local upstream_host
  local listen_port
  upstream_host="$(dev_detect_api_upstream_host)"
  listen_port="80"
  if [[ -z "$upstream_host" ]]; then
    echo "[dev] failed to detect Docker host gateway IPv4 for nginx upstream" >&2
    return 1
  fi

  DEV_NGINX_TEMPLATE="$MTY_DEV_NGINX_CONF_TEMPLATE_PATH" \
  DEV_NGINX_OUTPUT="$MTY_DEV_NGINX_CONF_PATH" \
  DEV_API_UPSTREAM_HOST="$upstream_host" \
  DEV_NGINX_LISTEN_PORT="$listen_port" \
  python3 - <<'PY'
import os
from pathlib import Path

template = Path(os.environ["DEV_NGINX_TEMPLATE"]).read_text(encoding="utf-8")
rendered = (
    template
    .replace("__MTY_DEV_API_UPSTREAM_HOST__", os.environ["DEV_API_UPSTREAM_HOST"])
    .replace("__MTY_DEV_NGINX_LISTEN_PORT__", os.environ["DEV_NGINX_LISTEN_PORT"])
)
Path(os.environ["DEV_NGINX_OUTPUT"]).write_text(rendered, encoding="utf-8")
PY
}

dev_use_local_minio() {
  case "$(dev_lower "$MTY_INFRA_USE_LOCAL_MINIO")" in
    1|true|yes|on)
      return 0
      ;;
    0|false|no|off)
      return 1
      ;;
    auto)
      if [[ "$MTY_MINIO_ENDPOINT" == *"127.0.0.1:${MTY_INFRA_MINIO_PORT}"* ]] || \
         [[ "$MTY_MINIO_ENDPOINT" == *"localhost:${MTY_INFRA_MINIO_PORT}"* ]]; then
        return 0
      fi
      return 1
      ;;
    *)
      echo "[dev] invalid MTY_INFRA_USE_LOCAL_MINIO: $MTY_INFRA_USE_LOCAL_MINIO" >&2
      return 1
      ;;
  esac
}

dev_use_local_postgres() {
  case "$(dev_lower "$MTY_INFRA_USE_LOCAL_POSTGRES")" in
    1|true|yes|on)
      return 0
      ;;
    0|false|no|off)
      return 1
      ;;
    auto)
      if [[ "$MTY_POSTGRES_DSN" == *"127.0.0.1:${MTY_INFRA_POSTGRES_PORT}"* ]] || \
         [[ "$MTY_POSTGRES_DSN" == *"localhost:${MTY_INFRA_POSTGRES_PORT}"* ]]; then
        return 0
      fi
      return 1
      ;;
    *)
      echo "[dev] invalid MTY_INFRA_USE_LOCAL_POSTGRES: $MTY_INFRA_USE_LOCAL_POSTGRES" >&2
      return 1
      ;;
  esac
}
