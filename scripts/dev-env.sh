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
    if key == "MIY_ENV_PROFILE" and key in os.environ:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(f"export {key}={shlex.quote(value)}")
PY
  )"
}

dev_export_miy_desktop_installer_defaults() {
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
    (root / "packages" / "contracts" / "miy-desktop-update-feed.manifest.json").read_text(
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
if fallback_url and not os.environ.get("VITE_MIY_DESKTOP_INSTALLER_URL"):
    print(f"export VITE_MIY_DESKTOP_INSTALLER_URL={shlex.quote(fallback_url)}")
PY
  )"
}

dev_lower() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

if [[ "${MIY_SKIP_DOTENV:-0}" != "1" ]]; then
  dev_load_dotenv "$ROOT_DIR/.env"
fi

export MIY_DEV_API_COUNT="${MIY_DEV_API_COUNT:-1}"
export MIY_DEV_API_HOST="${MIY_DEV_API_HOST:-127.0.0.1}"
export MIY_WEB_DEV_HOST="${MIY_WEB_DEV_HOST:-127.0.0.1}"
export MIY_INFRA_CONTAINER_PREFIX="${MIY_INFRA_CONTAINER_PREFIX:-miy-dev}"
export MIY_INFRA_BIND_HOST="${MIY_INFRA_BIND_HOST:-127.0.0.1}"
export MIY_INFRA_NGINX_PORT="${MIY_INFRA_NGINX_PORT:-14200}"
export MIY_INFRA_REDIS_PORT="${MIY_INFRA_REDIS_PORT:-56380}"
export MIY_INFRA_POSTGRES_DB="${MIY_INFRA_POSTGRES_DB:-miy_dev}"
export MIY_INFRA_POSTGRES_PASSWORD="${MIY_INFRA_POSTGRES_PASSWORD:-miy_dev}"
export MIY_INFRA_POSTGRES_PORT="${MIY_INFRA_POSTGRES_PORT:-55433}"
export MIY_INFRA_POSTGRES_USER="${MIY_INFRA_POSTGRES_USER:-miy_dev}"
export MIY_INFRA_USE_LOCAL_POSTGRES="${MIY_INFRA_USE_LOCAL_POSTGRES:-auto}"
export MIY_DEV_REDIS_URL="${MIY_DEV_REDIS_URL:-redis://127.0.0.1:${MIY_INFRA_REDIS_PORT}/0}"
export MIY_DEV_REDIS_RESULT_BACKEND="${MIY_DEV_REDIS_RESULT_BACKEND:-redis://127.0.0.1:${MIY_INFRA_REDIS_PORT}/1}"
export MIY_DEV_COLLAB_REDIS_URL="${MIY_DEV_COLLAB_REDIS_URL:-$MIY_DEV_REDIS_URL}"
export MIY_DEV_REALTIME_REDIS_URL="${MIY_DEV_REALTIME_REDIS_URL:-$MIY_DEV_REDIS_URL}"
export MIY_DEV_WORKER_BROKER_URL="${MIY_DEV_WORKER_BROKER_URL:-$MIY_DEV_REDIS_URL}"
export MIY_DEV_WORKER_RESULT_BACKEND="${MIY_DEV_WORKER_RESULT_BACKEND:-$MIY_DEV_REDIS_RESULT_BACKEND}"
export MIY_INFRA_MINIO_PORT="${MIY_INFRA_MINIO_PORT:-59010}"
export MIY_INFRA_MINIO_CONSOLE_PORT="${MIY_INFRA_MINIO_CONSOLE_PORT:-59011}"
export MIY_INFRA_OPENSEARCH_PORT="${MIY_INFRA_OPENSEARCH_PORT:-59210}"
export MIY_INFRA_OPENSEARCH_PERF_PORT="${MIY_INFRA_OPENSEARCH_PERF_PORT:-59610}"
export MIY_INFRA_QDRANT_PORT="${MIY_INFRA_QDRANT_PORT:-16333}"
export MIY_INFRA_QDRANT_GRPC_PORT="${MIY_INFRA_QDRANT_GRPC_PORT:-16334}"
export MIY_BENTO_BIND_HOST="${MIY_BENTO_BIND_HOST:-127.0.0.1}"
export MIY_BENTO_IMAGE_TAG="${MIY_BENTO_IMAGE_TAG:-1.0.17}"
export MIY_BENTO_PORT="${MIY_BENTO_PORT:-18084}"
export MIY_BENTO_SERVER_URL="${MIY_BENTO_SERVER_URL:-http://127.0.0.1:${MIY_BENTO_PORT}/}"
export MIY_HERMES_ENABLED="${MIY_HERMES_ENABLED:-false}"
export MIY_HERMES_RUNTIME_PORT="${MIY_HERMES_RUNTIME_PORT:-18642}"
export MIY_HERMES_MANAGEMENT_PORT="${MIY_HERMES_MANAGEMENT_PORT:-19119}"
export MIY_HERMES_RUNTIME_BASE_URL="${MIY_HERMES_RUNTIME_BASE_URL:-http://127.0.0.1:${MIY_HERMES_RUNTIME_PORT}}"
export MIY_HERMES_MANAGEMENT_BASE_URL="${MIY_HERMES_MANAGEMENT_BASE_URL:-http://127.0.0.1:${MIY_HERMES_MANAGEMENT_PORT}}"
export MIY_HERMES_API_KEY="${MIY_HERMES_API_KEY:-miy-dev-hermes-runtime-key-0001}"
export MIY_HERMES_MANAGEMENT_TOKEN="${MIY_HERMES_MANAGEMENT_TOKEN:-miy-dev-hermes-management-token-0001}"
export MIY_HERMES_MCP_SHARED_SECRET="${MIY_HERMES_MCP_SHARED_SECRET:-miy-dev-hermes-mcp-shared-secret-0000000000000001}"
export MIY_HERMES_MCP_SERVER_URL="${MIY_HERMES_MCP_SERVER_URL:-http://127.0.0.1:${MIY_API_DEV_PORT:-8001}/api/v1/internal/hermes/mcp}"
export MIY_HERMES_PROFILE_CLONE_SOURCE="${MIY_HERMES_PROFILE_CLONE_SOURCE:-default}"
export MIY_HERMES_REQUEST_TIMEOUT_SECONDS="${MIY_HERMES_REQUEST_TIMEOUT_SECONDS:-30}"
export MIY_HERMES_RUN_TIMEOUT_SECONDS="${MIY_HERMES_RUN_TIMEOUT_SECONDS:-3600}"
export MIY_HERMES_DISPATCH_LEASE_SECONDS="${MIY_HERMES_DISPATCH_LEASE_SECONDS:-300}"
export MIY_LIVEKIT_PORT="${MIY_LIVEKIT_PORT:-7880}"
export MIY_LIVEKIT_RTC_TCP_PORT="${MIY_LIVEKIT_RTC_TCP_PORT:-7881}"
export MIY_LIVEKIT_RTC_PORT_RANGE_START="${MIY_LIVEKIT_RTC_PORT_RANGE_START:-52000}"
export MIY_LIVEKIT_RTC_PORT_RANGE_END="${MIY_LIVEKIT_RTC_PORT_RANGE_END:-52100}"
export MIY_INFRA_USE_LOCAL_MINIO="${MIY_INFRA_USE_LOCAL_MINIO:-auto}"
export MIY_DEV_BASE_URL="${MIY_DEV_BASE_URL:-http://127.0.0.1:${MIY_INFRA_NGINX_PORT}}"
export MIY_DEV_RUNTIME_DIR="${MIY_DEV_RUNTIME_DIR:-$ROOT_DIR/.dev}"
export MIY_DEV_PID_DIR="${MIY_DEV_PID_DIR:-$MIY_DEV_RUNTIME_DIR/pids}"
export MIY_DEV_LOG_DIR="${MIY_DEV_LOG_DIR:-$MIY_DEV_RUNTIME_DIR/logs}"
export MIY_DEV_NGINX_CONF_TEMPLATE_PATH="${MIY_DEV_NGINX_CONF_TEMPLATE_PATH:-$ROOT_DIR/ops/dev/nginx.conf.template}"
export MIY_DEV_NGINX_CONF_PATH="${MIY_DEV_NGINX_CONF_PATH:-$MIY_DEV_RUNTIME_DIR/nginx.conf}"
export MIY_ENV_PROFILE="${MIY_ENV_PROFILE:-dev}"

export MIY_POSTGRES_DSN="${MIY_POSTGRES_DSN:-postgresql+psycopg://${MIY_INFRA_POSTGRES_USER}:${MIY_INFRA_POSTGRES_PASSWORD}@127.0.0.1:${MIY_INFRA_POSTGRES_PORT}/${MIY_INFRA_POSTGRES_DB}}"
export MIY_API_COLLAB_REDIS_URL="$MIY_DEV_COLLAB_REDIS_URL"
export MIY_API_REALTIME_REDIS_URL="$MIY_DEV_REALTIME_REDIS_URL"
export MIY_WORKER_BROKER_URL="$MIY_DEV_WORKER_BROKER_URL"
export MIY_WORKER_RESULT_BACKEND="$MIY_DEV_WORKER_RESULT_BACKEND"
export MIY_MINIO_ENDPOINT="${MIY_MINIO_ENDPOINT:-http://127.0.0.1:${MIY_INFRA_MINIO_PORT}}"
export MIY_MINIO_ACCESS_KEY="${MIY_MINIO_ACCESS_KEY:-miy_dev_minio}"
export MIY_MINIO_SECRET_KEY="${MIY_MINIO_SECRET_KEY:-miy_dev_minio}"
export MIY_MINIO_BUCKET="${MIY_MINIO_BUCKET:-miy-dev}"
export MIY_OPENSEARCH_URL="${MIY_OPENSEARCH_URL:-http://127.0.0.1:${MIY_INFRA_OPENSEARCH_PORT}}"
export MIY_OPENSEARCH_INDEX_PREFIX="${MIY_OPENSEARCH_INDEX_PREFIX:-miy-dev}"
export MIY_RAG_QDRANT_URL="${MIY_RAG_QDRANT_URL:-http://127.0.0.1:${MIY_INFRA_QDRANT_PORT}}"
export MIY_RAG_QDRANT_API_KEY="${MIY_RAG_QDRANT_API_KEY:-miy_dev_qdrant}"
export MIY_RAG_QDRANT_COLLECTION_PREFIX="${MIY_RAG_QDRANT_COLLECTION_PREFIX:-miy-dev-rag}"
export MIY_LIVEKIT_URL="${MIY_LIVEKIT_URL:-ws://127.0.0.1:${MIY_LIVEKIT_PORT}}"
export MIY_LIVEKIT_PUBLIC_URL="${MIY_LIVEKIT_PUBLIC_URL:-}"
export MIY_LIVEKIT_API_KEY="${MIY_LIVEKIT_API_KEY:-devkey}"
export MIY_LIVEKIT_API_SECRET="${MIY_LIVEKIT_API_SECRET:-devsecret-devsecret-devsecret-0001}"
export MIY_LLM_HEALTHCHECK_ON_STARTUP="${MIY_LLM_HEALTHCHECK_ON_STARTUP:-0}"
export MIY_LLM_REQUIRED="${MIY_LLM_REQUIRED:-0}"
export MIY_API_ALLOW_DEV_ADMIN_LOGIN="${MIY_API_ALLOW_DEV_ADMIN_LOGIN:-1}"
export MIY_API_OBJECT_STORAGE_REQUIRED="${MIY_API_OBJECT_STORAGE_REQUIRED:-1}"
export MIY_API_SEED_DEV_LOGIN_ACCOUNT="${MIY_API_SEED_DEV_LOGIN_ACCOUNT:-1}"
dev_export_miy_desktop_installer_defaults

dev_docker() {
  case "$MIY_ENV_PROFILE" in
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
      echo "[dev] MIY_ENV_PROFILE=$MIY_ENV_PROFILE is not supported for dev docker commands" >&2
      return 1
      ;;
    *)
      echo "[dev] invalid MIY_ENV_PROFILE: $MIY_ENV_PROFILE (expected local, dev, prod)" >&2
      return 1
      ;;
  esac
}

dev_docker_available() {
  dev_docker info >/dev/null 2>&1
}

dev_compose_file() {
  case "$MIY_ENV_PROFILE" in
    local|dev|"")
      printf '%s/ops/compose/miy-dev.infra.yml\n' "$ROOT_DIR"
      ;;
    prod|production)
      echo "[dev] MIY_ENV_PROFILE=$MIY_ENV_PROFILE is not supported for dev compose commands" >&2
      return 1
      ;;
    *)
      echo "[dev] invalid MIY_ENV_PROFILE: $MIY_ENV_PROFILE (expected local, dev, prod)" >&2
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
  mkdir -p "$MIY_DEV_RUNTIME_DIR" "$MIY_DEV_PID_DIR" "$MIY_DEV_LOG_DIR"
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

  DEV_NGINX_TEMPLATE="$MIY_DEV_NGINX_CONF_TEMPLATE_PATH" \
  DEV_NGINX_OUTPUT="$MIY_DEV_NGINX_CONF_PATH" \
  DEV_API_UPSTREAM_HOST="$upstream_host" \
  DEV_NGINX_LISTEN_PORT="$listen_port" \
  python3 - <<'PY'
import os
from pathlib import Path

template = Path(os.environ["DEV_NGINX_TEMPLATE"]).read_text(encoding="utf-8")
rendered = (
    template
    .replace("__MIY_DEV_API_UPSTREAM_HOST__", os.environ["DEV_API_UPSTREAM_HOST"])
    .replace("__MIY_DEV_NGINX_LISTEN_PORT__", os.environ["DEV_NGINX_LISTEN_PORT"])
)
Path(os.environ["DEV_NGINX_OUTPUT"]).write_text(rendered, encoding="utf-8")
PY
}

dev_use_local_minio() {
  case "$(dev_lower "$MIY_INFRA_USE_LOCAL_MINIO")" in
    1|true|yes|on)
      return 0
      ;;
    0|false|no|off)
      return 1
      ;;
    auto)
      if [[ "$MIY_MINIO_ENDPOINT" == *"127.0.0.1:${MIY_INFRA_MINIO_PORT}"* ]] || \
         [[ "$MIY_MINIO_ENDPOINT" == *"localhost:${MIY_INFRA_MINIO_PORT}"* ]]; then
        return 0
      fi
      return 1
      ;;
    *)
      echo "[dev] invalid MIY_INFRA_USE_LOCAL_MINIO: $MIY_INFRA_USE_LOCAL_MINIO" >&2
      return 1
      ;;
  esac
}

dev_use_local_postgres() {
  case "$(dev_lower "$MIY_INFRA_USE_LOCAL_POSTGRES")" in
    1|true|yes|on)
      return 0
      ;;
    0|false|no|off)
      return 1
      ;;
    auto)
      if [[ "$MIY_POSTGRES_DSN" == *"127.0.0.1:${MIY_INFRA_POSTGRES_PORT}"* ]] || \
         [[ "$MIY_POSTGRES_DSN" == *"localhost:${MIY_INFRA_POSTGRES_PORT}"* ]]; then
        return 0
      fi
      return 1
      ;;
    *)
      echo "[dev] invalid MIY_INFRA_USE_LOCAL_POSTGRES: $MIY_INFRA_USE_LOCAL_POSTGRES" >&2
      return 1
      ;;
  esac
}
