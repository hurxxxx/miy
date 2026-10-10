#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/dev-env.sh"

if [[ -n "${HOME:-}" && -d "$HOME/.local/bin" ]]; then
  case ":${PATH:-}:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:${PATH:-}" ;;
  esac
fi

if [[ "$(basename "$ROOT_DIR")" == "prod" && "${MIY_ALLOW_PROD_DEV_SH:-0}" != "1" ]]; then
  echo "Refusing to run dev.sh from the production checkout." >&2
  echo "Use ./prod.sh for production, or set MIY_ALLOW_PROD_DEV_SH=1 explicitly for one-off diagnostics." >&2
  exit 1
fi

# The Nx daemon is unstable in this environment; use direct Nx execution.
export NX_DAEMON=false
# dev-env.sh already loads the checkout .env. Letting Nx load .env.local again
# can make the API process disagree with scripts/dev-smoke.sh.
export NX_LOAD_DOT_ENV_FILES=false
WEB_DEV_PORT="${MIY_WEB_DEV_PORT:-4200}"
API_DEV_PORT="${MIY_API_DEV_PORT:-8001}"
OFFICIAL_WEB_DEV_PORT=4201
OFFICIAL_API_DEV_PORT=18781
export MIY_WEB_DEV_PORT="$WEB_DEV_PORT"
export MIY_WEB_API_PROXY_TARGET="${MIY_WEB_API_PROXY_TARGET:-http://127.0.0.1:${API_DEV_PORT}}"

usage() {
  cat <<'EOF'
Usage: ./dev.sh [options]

Options:
  --with-worker  Start the Celery worker in addition to web and api.
  --first-party  Explicit platform/official API and worker composition.
  --web-only     Start only the frontend dev server.
  --api-only     Start only the FastAPI dev server.
  --no-infra     Skip starting the dev docker infra (redis, etc).
  --minimal-infra
                 Start only PostgreSQL and Redis and disable optional startup dependencies.
  --status       Show repo-managed dev server status for the selected projects and exit.
  --stop         Stop repo-managed dev servers for the selected projects and exit.
  --restart      Stop repo-managed dev servers for the selected projects, then start them again.
  --reset-nx     Reset the Nx daemon before starting servers.
  --plain-logs   Use raw Nx stream logs instead of the default readable local format.
  -h, --help     Show this help message.

Defaults:
  - Starts `web`, its independent official UI, and the legacy `api`
  - `--first-party` uses common API 8001 (or MIY_API_DEV_PORT), official API 18781,
    two owned consumers and one Beat; --api-only/--web-only retain their scope
  - Bootstrap legacy workers once before the first namespace transition, then
    use `--first-party --restart`; unknown drain state holds the transition
  - Boots the dev docker infra (redis/search/vector; postgres/minio when MIY_INFRA_USE_LOCAL_* is on)
    so features like the docs collab relay can reach redis at 127.0.0.1:56380
  - `--minimal-infra` is intended for authentication and core UI smoke tests;
    storage, AI, search, video, and RAG-dependent features remain unavailable
  - Uses `dynamic-legacy` Nx output for readable local logs
  - Stops all child servers when you press Ctrl+C or close the session
    (docker infra keeps running across sessions; stop it with `scripts/infra-stack.sh dev stop`)
  - Stop only the minimal containers with `pnpm dev:infra:minimal:down`
EOF
}

declare -a projects=("web" "api")
with_worker=0
first_party=0
status_only=0
stop_only=0
restart=0
reset_nx=0
infra_enabled=1
minimal_infra=0
output_style="dynamic-legacy"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-worker)
      with_worker=1
      ;;
    --first-party)
      first_party=1
      ;;
    --web-only)
      projects=("web")
      ;;
    --api-only)
      projects=("api")
      ;;
    --no-infra)
      infra_enabled=0
      ;;
    --minimal-infra)
      minimal_infra=1
      ;;
    --status)
      status_only=1
      ;;
    --stop)
      stop_only=1
      ;;
    --restart)
      restart=1
      ;;
    --reset-nx)
      reset_nx=1
      ;;
    --plain-logs)
      output_style="stream"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if (( minimal_infra )); then
  export MIY_INFRA_USE_LOCAL_POSTGRES=1
  export MIY_INFRA_USE_LOCAL_MINIO=0
  export MIY_POSTGRES_DSN="postgresql+psycopg://${MIY_INFRA_POSTGRES_USER}:${MIY_INFRA_POSTGRES_PASSWORD}@127.0.0.1:${MIY_INFRA_POSTGRES_PORT}/${MIY_INFRA_POSTGRES_DB}"
  export MIY_API_OBJECT_STORAGE_REQUIRED=0
  export MIY_API_SEED_DEV_LOGIN_ACCOUNT=1
  export MIY_API_VIDEO_CHAT_ENABLED=false
  export MIY_LLM_HEALTHCHECK_ON_STARTUP=false
  export MIY_LLM_REQUIRED=false
  export MIY_OPF_ENABLED=false
  export MIY_OPF_HEALTHCHECK_ON_STARTUP=false
  export MIY_OPF_REQUIRED=false
  export MIY_RAG_ENABLED=false
  export MIY_RAG_PRELOAD_ON_STARTUP=false
  export MIY_HERMES_ENABLED=false
  export MIY_API_RECORDING_SPOOL_DIR="$MIY_DEV_RUNTIME_DIR/recording-spool"
fi

# The independently owned UI is served by its own Vite process in both modes.
if [[ " ${projects[*]} " == *" web "* ]]; then
  projects+=("official-suite")
fi
if (( first_party )) && [[ " ${projects[*]} " == *" web "* && " ${projects[*]} " == *" api "* ]]; then
  with_worker=1
fi
if (( with_worker )); then
  projects+=("worker")
fi

project_csv="$(IFS=,; echo "${projects[*]}")"
parallelism="${#projects[@]}"
if [[ " ${projects[*]} " == *" web "* && "$WEB_DEV_PORT" == "$OFFICIAL_WEB_DEV_PORT" ]]; then
  echo "The common web port conflicts with the fixed official UI port 4201." >&2
  exit 1
fi
if (( first_party )) && [[ " ${projects[*]} " == *" api "* && "$API_DEV_PORT" == "$OFFICIAL_API_DEV_PORT" ]]; then
  echo "The common API port conflicts with the fixed official development port 18781." >&2
  exit 1
fi

find_listener() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true
}

show_project_status() {
  local project="$1"
  local listeners=""
  local process_lines=""

  case "$project" in
    web)
      listeners="$(find_listener "$WEB_DEV_PORT")"
      if [[ -n "$listeners" ]]; then
        echo "web    running  http://localhost:${WEB_DEV_PORT}"
        echo "$listeners"
      else
        echo "web    stopped"
      fi
      ;;
    api)
      listeners="$(find_listener "$API_DEV_PORT")"
      if [[ -n "$listeners" ]]; then
        echo "api    running  http://127.0.0.1:${API_DEV_PORT}/docs"
        echo "$listeners"
      else
        echo "api    stopped"
      fi
      if (( first_party )); then
        listeners="$(find_listener "$OFFICIAL_API_DEV_PORT")"
        if [[ -n "$listeners" ]]; then
          echo "official API running http://127.0.0.1:${OFFICIAL_API_DEV_PORT}/docs"
          echo "$listeners"
        else
          echo "official API stopped"
        fi
      fi
      ;;
    official-suite)
      listeners="$(find_listener "$OFFICIAL_WEB_DEV_PORT")"
      if [[ -n "$listeners" ]]; then
        echo "official UI running http://localhost:${OFFICIAL_WEB_DEV_PORT}/official-suite/"
        echo "$listeners"
      else
        echo "official UI stopped"
      fi
      ;;
    worker)
      process_lines="$(find_worker_processes worker)"
      if [[ -n "$process_lines" ]]; then
        echo "worker running"
        while read -r pid _; do
          printf '  %s repo-managed Celery worker\n' "$pid"
        done <<< "$process_lines"
      else
        echo "worker stopped"
      fi
      ;;
  esac
}

project_selected() {
  local needle="$1"
  local project
  for project in "${projects[@]}"; do
    if [[ "$project" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

find_worker_processes() {
  local role="${1:-}"
  local -a selector=(--root "$ROOT_DIR")
  if [[ -n "$role" ]]; then selector+=(--role "$role"); fi
  python3 "$ROOT_DIR/scripts/dev-worker-processes.py" "${selector[@]}"
}

process_is_owned() {
  local pid="$1"
  local process_cwd
  [[ "$pid" =~ ^[0-9]+$ && -O "/proc/$pid" ]] || return 1
  process_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  case "$process_cwd" in
    "$ROOT_DIR"|"$ROOT_DIR"/*) return 0 ;;
    *) return 1 ;;
  esac
}

find_api_processes() {
  local pid args
  while read -r pid args; do
    if process_is_owned "$pid" && [[ "$args" =~ uvicorn\ (miy_api\.(main|platform_runtime)|miy_official_api\.development):app ]]; then
      printf '%s %s\n' "$pid" "$args"
    fi
  done < <(pgrep -af 'uvicorn' || true)
}

stop_owned_listener() {
  local port="$1" label="$2" pid ancestor args parent owned matched signaled=0
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    owned=0
    ancestor="$pid"
    for _ in 1 2 3 4; do
      if ! process_is_owned "$ancestor"; then
        break
      fi
      args="$(ps -p "$ancestor" -o args= 2>/dev/null || true)"
      matched=0
      case "$label:$args" in
        api:*uvicorn\ miy_api.main:app*|api:*uvicorn\ miy_api.platform_runtime:app*|official-api:*uvicorn\ miy_official_api.development:app*) matched=1 ;;
        web:*vite*apps/web/vite.config.*|official-suite:*vite*apps/official-suite/vite.config.*) matched=1 ;;
      esac
      if (( matched )); then
        owned=1
        if kill_if_running "$ancestor"; then
          signaled=1
        fi
      fi
      parent="$(ps -p "$ancestor" -o ppid= 2>/dev/null | tr -d ' ' || true)"
      [[ "$parent" =~ ^[0-9]+$ && "$parent" != "$ancestor" ]] || break
      ancestor="$parent"
    done
    if (( ! owned )); then
      echo "Leaving ${label} port ${port} listener ${pid}: outside this checkout's launcher." >&2
    fi
  done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  (( signaled ))
}

find_consumer_bindings() {
  local pid args profile node processes
  local -A seen=()
  processes="$(find_worker_processes worker)" || return 1
  while read -r pid args; do
    process_is_owned "$pid" || continue
    case "$args" in
      *miy_worker.celery_app:celery_app*) profile=legacy ;;
      *miy_worker.first_party_platform:celery_app*) profile=platform ;;
      *miy_official_worker.runtime:celery_app*) profile=official ;;
      *) continue ;;
    esac
    node="celery@$(hostname)"
    if [[ "$args" =~ --hostname[=\ ]([[:alnum:]_.@%+-]+) ]]; then
      node="${BASH_REMATCH[1]}"
      node="${node//%h/$(hostname)}"
    elif [[ "$args" =~ \ -n\ ([[:alnum:]_.@%+-]+) ]]; then
      node="${BASH_REMATCH[1]}"
      node="${node//%h/$(hostname)}"
    fi
    if [[ "$node" == *"%"* || "$node" != *@* ]]; then
      echo "Native consumer hostname is unavailable; namespace transition HOLD." >&2
      return 1
    fi
    if [[ -n "${seen[$node]:-}" && "${seen[$node]}" != "$profile" ]]; then
      echo "Native consumer hostname is ambiguous; namespace transition HOLD." >&2
      return 1
    fi
    if [[ -z "${seen[$node]:-}" ]]; then
      seen[$node]="$profile"
      printf '%s|%s\n' "$node" "$profile"
    fi
  done <<< "$processes"
}

require_free_port() {
  local port="$1"
  local label="$2"
  local listeners
  listeners="$(find_listener "$port")"

  if [[ -n "$listeners" ]]; then
    echo "Cannot start ${label}: port ${port} is already in use." >&2
    echo >&2
    echo "$listeners" >&2
    echo >&2
    echo "Stop the existing process before running ./dev.sh again; no fallback port will be selected." >&2
    exit 1
  fi
}

run_api_migration_preflight() {
  if [[ "${MIY_DEV_API_MIGRATION_PREFLIGHT:-1}" == "0" ]]; then
    return 0
  fi

  local auto_migrate
  auto_migrate="$(printf '%s' "${MIY_API_AUTO_MIGRATE:-1}" | tr '[:upper:]' '[:lower:]')"
  case "$auto_migrate" in
    1|true|yes) ;;
    *) return 0 ;;
  esac

  echo "Checking API migrations before starting dev server..."
  (
    cd "$ROOT_DIR/apps/api"
    MIY_API_AUTO_MIGRATE=0 uv run --python 3.12 alembic upgrade head
  )
  export MIY_API_AUTO_MIGRATE=0
}

kill_if_running() {
  local pid="$1"
  if process_is_owned "$pid" && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    return 0
  fi
  return 1
}

start_dev_infra() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker CLI not found; skipping dev infra startup." >&2
    return 0
  fi
  if ! dev_docker_available; then
    echo "Docker daemon not reachable; skipping dev infra startup." >&2
    return 0
  fi

  local desired=()
  if (( minimal_infra )); then
    desired=(postgres redis)
  else
    desired=(redis opensearch qdrant)
    if [[ "$(printf '%s' "${MIY_API_VIDEO_CHAT_ENABLED:-true}" | tr '[:upper:]' '[:lower:]')" != "false" ]]; then
      desired+=(livekit)
    fi
    if [[ "$(dev_lower "${MIY_HERMES_ENABLED:-false}")" == "true" ]]; then
      desired+=(
        hermes-bootstrap
        hermes-gateway
        hermes-dashboard
        hermes-terminal-egress
        hermes-terminal-broker
      )
    fi
    if dev_use_local_postgres; then
      desired+=(postgres)
    fi
    if dev_use_local_minio; then
      desired+=(minio)
    fi
  fi

  # Stop dev-nginx only when it is configured to collide with the web dev server.
  local dev_nginx_container="${MIY_INFRA_CONTAINER_PREFIX:-miy-dev}-nginx"
  local dev_nginx_port="${MIY_INFRA_NGINX_PORT:-14200}"
  local web_in_projects=0
  local project
  for project in "${projects[@]}"; do
    if [[ "$project" == "web" ]]; then
      web_in_projects=1
      break
    fi
  done
  if (( web_in_projects )) && [[ "$dev_nginx_port" == "$WEB_DEV_PORT" ]]; then
    if dev_docker inspect "$dev_nginx_container" >/dev/null 2>&1; then
      local nginx_owner
      nginx_owner="$(dev_docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$dev_nginx_container" 2>/dev/null || true)"
      if [[ "$nginx_owner" == "$ROOT_DIR/ops/compose/miy-dev.infra.yml" ]]; then
        echo "Neutralizing ${dev_nginx_container} (conflicts with web dev server on ${WEB_DEV_PORT})..."
        dev_docker update --restart=no "$dev_nginx_container" >/dev/null 2>&1 || true
        dev_docker stop "$dev_nginx_container" >/dev/null 2>&1 || true
      else
        echo "Leaving ${dev_nginx_container}: its Compose owner is outside this checkout." >&2
      fi
    fi
  fi

  # If a service's host port is already bound (e.g., a sibling repo's compose
  # project started redis under the same fixed container name), reuse it
  # instead of colliding on `docker compose up`.
  local redis_port="${MIY_INFRA_REDIS_PORT:-56380}"
  local postgres_port="${MIY_INFRA_POSTGRES_PORT:-55433}"
  local minio_port="${MIY_INFRA_MINIO_PORT:-59010}"
  local opensearch_port="${MIY_INFRA_OPENSEARCH_PORT:-59210}"
  local qdrant_port="${MIY_INFRA_QDRANT_PORT:-16333}"
  local livekit_port="${MIY_LIVEKIT_PORT:-7880}"
  local hermes_runtime_port="${MIY_HERMES_RUNTIME_PORT:-18642}"
  local hermes_management_port="${MIY_HERMES_MANAGEMENT_PORT:-19119}"
  local hermes_terminal_broker_port="${MIY_HERMES_TERMINAL_BROKER_PORT:-18765}"
  local services=()
  local skipped=()
  local svc
  for svc in "${desired[@]}"; do
    local port=""
    case "$svc" in
      redis) port="$redis_port" ;;
      postgres) port="$postgres_port" ;;
      minio) port="$minio_port" ;;
      opensearch) port="$opensearch_port" ;;
      qdrant) port="$qdrant_port" ;;
      livekit) port="$livekit_port" ;;
      hermes-bootstrap|hermes-gateway) port="$hermes_runtime_port" ;;
      hermes-dashboard) port="$hermes_management_port" ;;
      hermes-terminal-broker) port="$hermes_terminal_broker_port" ;;
    esac
    if [[ -n "$port" && -n "$(find_listener "$port")" ]]; then
      if [[ "$svc" == "hermes-terminal-broker" ]]; then
        local broker_container="miy-dev-hermes-terminal-broker"
        local broker_running
        local broker_binding
        broker_running="$(dev_docker inspect -f '{{.State.Running}}' "$broker_container" 2>/dev/null || true)"
        broker_binding="$(dev_docker port "$broker_container" 18765/tcp 2>/dev/null || true)"
        if [[ "$broker_running" != "true" || "$broker_binding" != "127.0.0.1:${port}" ]]; then
          echo "Cannot start Hermes Terminal broker: fixed port ${port} is already in use." >&2
          echo >&2
          find_listener "$port" >&2
          echo >&2
          echo "Stop the existing process; no fallback port will be selected." >&2
          exit 1
        fi
      fi
      skipped+=("${svc}(:${port})")
    else
      services+=("$svc")
    fi
  done

  if (( ${#skipped[@]} > 0 )); then
    echo "Reusing already-running infra: ${skipped[*]}"
  fi

  if (( ${#services[@]} == 0 )); then
    return 0
  fi

  echo "Starting dev infra: ${services[*]}"
  local compose_file
  local compose_env_file
  compose_file="$(dev_compose_file)"
  compose_env_file="$(dev_compose_env_file)"
  if ! dev_docker compose --env-file "$compose_env_file" -f "$compose_file" up -d "${services[@]}"; then
    echo "Failed to start dev infra via docker compose." >&2
    exit 1
  fi

  # PING-verify redis only if we just started it via this compose project.
  # If we're reusing an existing redis, the port-listener check above already
  # confirmed it's bound; `compose exec redis` would not address it anyway.
  local started_redis=0
  local started_postgres=0
  for svc in "${services[@]}"; do
    [[ "$svc" == "redis" ]] && started_redis=1
    [[ "$svc" == "postgres" ]] && started_postgres=1
  done
  if (( started_redis )); then
    local attempts=0
    while (( attempts < 30 )); do
      if dev_docker compose --env-file "$compose_env_file" -f "$compose_file" exec -T redis redis-cli ping >/dev/null 2>&1; then
        break
      fi
      attempts=$((attempts + 1))
      sleep 0.3
    done
    if (( attempts == 30 )); then
      echo "Warning: redis did not respond to PING within ~9s; continuing anyway." >&2
    fi
  fi
  if (( started_postgres )); then
    local attempts=0
    while (( attempts < 60 )); do
      if dev_docker compose --env-file "$compose_env_file" -f "$compose_file" exec -T postgres \
        pg_isready -U "$MIY_INFRA_POSTGRES_USER" -d "$MIY_INFRA_POSTGRES_DB" >/dev/null 2>&1; then
        break
      fi
      attempts=$((attempts + 1))
      sleep 0.5
    done
    if (( attempts == 60 )); then
      echo "PostgreSQL did not become ready within 30s." >&2
      exit 1
    fi
  fi
}

stop_project_processes() {
  local project="$1"
  local worker_role="${2:-}"
  local stopped=0
  local processes

  case "$project" in
    web)
      if stop_owned_listener "$WEB_DEV_PORT" web; then stopped=1; fi
      ;;
    official-suite)
      if stop_owned_listener "$OFFICIAL_WEB_DEV_PORT" official-suite; then stopped=1; fi
      ;;
    api)
      if stop_owned_listener "$API_DEV_PORT" api; then stopped=1; fi
      if (( first_party || transition_required )); then
        if stop_owned_listener "$OFFICIAL_API_DEV_PORT" official-api; then stopped=1; fi
      fi
      ;;
    worker)
      processes="$(find_worker_processes "$worker_role")" || return 1
      while read -r pid args; do
        [[ -n "$pid" ]] || continue
        if kill_if_running "$pid"; then stopped=1; fi
      done <<< "$processes"
      ;;
  esac

  if (( stopped )); then
    sleep 1
  fi
}

stop_selected_projects() {
  local project processes
  if project_selected worker; then
    # Warm TERM belongs to the native Main. Keep Nx, publishers and Beat alive
    # until its pool finishes; no fixed timeout proves task completion.
    stop_project_processes worker worker || return 1
    while :; do
      processes="$(find_worker_processes worker)" || return 1
      [[ -z "$processes" ]] && break
      sleep 0.25
    done
  fi
  for project in "${projects[@]}"; do
    [[ "$project" == "worker" ]] && continue
    stop_project_processes "$project" || return 1
  done
  if project_selected worker; then
    stop_project_processes worker beat || return 1
  fi
}

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "Ignoring active virtualenv: ${VIRTUAL_ENV}"
  echo "This repo uses project-local environments via uv; dev.sh will unset VIRTUAL_ENV."
  unset VIRTUAL_ENV
fi

unset PYTHONHOME

transition_required=0
if (( stop_only )); then
  stop_selected_projects
  echo "Stopped repo-managed dev servers for: ${project_csv}"
  exit 0
fi

if (( status_only )); then
  echo "miy dev server status"
  echo "  projects : ${project_csv}"
  echo
  for project in "${projects[@]}"; do
    show_project_status "$project"
    echo
  done
  exit 0
fi

if ! command -v setsid >/dev/null 2>&1; then
  echo "Native setsid is unavailable; development startup HOLD." >&2
  exit 1
fi

# Namespace changes use the current live consumers as their native drain
# witness. No response, missing consumer, or partial topology is an empty-state
# proof. Bootstrap legacy once before the first explicit first-party transition.
declare -a drain_args=()
legacy_consumers=0
first_party_consumers=0
selected_topology=unselected
desired_topology=legacy
if (( first_party )); then
  desired_topology=first-party
fi
if project_selected api || project_selected worker; then
  selected_topology="$(python3 "$ROOT_DIR/scripts/dev-topology.py" --read)"
  bindings="$(find_consumer_bindings)"
  while IFS='|' read -r node profile; do
    [[ -n "$node" ]] || continue
    drain_args+=(--consumer "${node}|${profile}")
    if [[ "$profile" == "legacy" ]]; then
      legacy_consumers=$((legacy_consumers + 1))
    else
      first_party_consumers=$((first_party_consumers + 1))
    fi
  done <<< "$bindings"
  api_process_lines="$(find_api_processes)"
  observed_topology=none
  if (( legacy_consumers )) || [[ "$api_process_lines" == *"miy_api.main:app"* ]]; then
    observed_topology=legacy
  fi
  if (( first_party_consumers )) || [[ "$api_process_lines" == *"miy_api.platform_runtime:app"* || "$api_process_lines" == *"miy_official_api.development:app"* ]]; then
    if [[ "$observed_topology" == "legacy" ]]; then
      echo "Development namespace inventory is mixed; startup HOLD." >&2
      exit 1
    fi
    observed_topology=first-party
  fi
  if [[ "$observed_topology" != "none" && "$selected_topology" != "unselected" && "$observed_topology" != "$selected_topology" ]] ||
     [[ "$selected_topology" == "unselected" && "$observed_topology" == "first-party" ]]; then
    echo "Development namespace inventory contradicts the owner selection; startup HOLD." >&2
    exit 1
  fi
  # An unchanged stored namespace can restart its own native queues after a
  # full stop/reboot. This record never proves another namespace is empty.
  if [[ "$desired_topology" != "$selected_topology" ]] &&
     [[ "$desired_topology" != "legacy" || "$selected_topology" != "unselected" ]]; then
    transition_required=1
    if (( ${#drain_args[@]} == 0 )); then
      echo "Namespace transition HOLD: no live native consumer drain witness." >&2
      echo "For first-party initial setup, bootstrap ./dev.sh --with-worker, then --first-party --restart." >&2
      exit 1
    fi
  fi
  if (( transition_required && ! restart && ! reset_nx )); then
    echo "Namespace transition HOLD: use --restart to stop publishers and Beat before native drain." >&2
    exit 1
  fi
  if (( transition_required )) && ! project_selected api; then
    echo "Namespace transition HOLD: include API selection so old publishers can stop before drain." >&2
    exit 1
  fi
fi

if (( restart || reset_nx )); then
  if (( transition_required )); then
    # Pause old publications first; keep consumers alive until the exact native
    # active/reserved/scheduled and queue inventories have drained twice.
    for project in "${projects[@]}"; do
      if [[ "$project" != "worker" ]]; then
        stop_project_processes "$project"
      fi
    done
    stop_project_processes worker beat
    for _ in {1..20}; do
      beat_processes="$(find_worker_processes beat)" || exit 1
      if [[ -z "$(find_api_processes)" && -z "$beat_processes" ]]; then
        break
      fi
      sleep 0.25
    done
    beat_processes="$(find_worker_processes beat)" || exit 1
    if [[ -n "$(find_api_processes)" || -n "$beat_processes" ]]; then
      echo "Namespace transition HOLD: owned API/Beat shutdown has not completed." >&2
      exit 1
    fi
    if [[ ! -x "$ROOT_DIR/apps/worker/.venv/bin/python" ]]; then
      echo "Namespace transition HOLD: the current native worker environment is unavailable." >&2
      exit 1
    fi
    echo "Checking exact live consumer drain before changing the development namespace..."
    "$ROOT_DIR/apps/worker/.venv/bin/python" "$ROOT_DIR/scripts/prod-app-drain.py" "${drain_args[@]}" --timeout 60
    # Retire the old namespace even for an API-only transition. API-only starts
    # no replacement consumers; old workers cannot remain a conflicting owner.
    stop_project_processes worker
    for _ in {1..20}; do
      worker_processes="$(find_worker_processes)" || exit 1
      [[ -z "$worker_processes" ]] && break
      sleep 0.25
    done
    worker_processes="$(find_worker_processes)" || exit 1
    if [[ -n "$worker_processes" ]]; then
      echo "Namespace transition HOLD: native consumer shutdown has not completed." >&2
      exit 1
    fi
  else
    stop_selected_projects
  fi
fi

if (( reset_nx )); then
  pnpm exec nx reset >/dev/null
fi

if (( infra_enabled )); then
  start_dev_infra
fi

# The provider credential belongs to the isolated Hermes containers. API,
# worker, web, and migration subprocesses only receive Hermes control tokens.
unset OPENROUTER_API_KEY

for project in "${projects[@]}"; do
  case "$project" in
    web)
      require_free_port "$WEB_DEV_PORT" "web dev server"
      ;;
    official-suite)
      require_free_port "$OFFICIAL_WEB_DEV_PORT" "official UI dev server"
      ;;
    api)
      require_free_port "$API_DEV_PORT" "api dev server"
      if (( first_party )); then
        require_free_port "$OFFICIAL_API_DEV_PORT" "official API dev server"
      fi
      ;;
    worker)
      worker_processes="$(find_worker_processes)" || exit 1
      if [[ -n "$worker_processes" ]]; then
        echo "Cannot start a second owned worker/Beat; wait for native shutdown or use --restart." >&2
        exit 1
      fi
      ;;
  esac
done

if project_selected api; then
  run_api_migration_preflight
fi

declare -a nx_configuration=()
if (( first_party )); then
  mkdir -p "$ROOT_DIR/.runtime"
  inventory_next="$(mktemp "$ROOT_DIR/.runtime/first-party-api-routes.json.XXXXXX")"
  if ! uv run --directory "$ROOT_DIR/apps/api" --python 3.12 python -m miy_api.first_party_routes --json > "$inventory_next"; then
    rm -- "$inventory_next"
    exit 1
  fi
  chmod 0644 "$inventory_next"
  mv -- "$inventory_next" "$ROOT_DIR/.runtime/first-party-api-routes.json"
  nx_configuration=(--configuration=first-party)
fi

if { project_selected api || project_selected worker; } && [[ "$desired_topology" != "$selected_topology" ]]; then
  # Only the implicit legacy bootstrap or the successful native transition
  # above reaches this write. Never overwrite an invalid or changed record.
  python3 "$ROOT_DIR/scripts/dev-topology.py" --select "$desired_topology" --expect "$selected_topology"
fi

cat <<EOF
Starting miy development servers
  projects : ${project_csv}
  web      : http://localhost:${WEB_DEV_PORT}
  api      : http://127.0.0.1:${API_DEV_PORT}/docs
  official UI  : http://localhost:${OFFICIAL_WEB_DEV_PORT}/official-suite/
  composition  : $([[ "$first_party" == "1" ]] && echo first-party || echo legacy)

Press Ctrl+C to stop all running servers.
EOF

cleanup() {
  trap - INT TERM HUP EXIT
  stop_selected_projects || return 1
  if [[ -n "${nx_pid:-}" ]]; then
    # All unfinished native workers have completed before waiting for Nx's
    # remaining API/Beat/UI commands to exit. Never signal its task trees early.
    wait "$nx_pid" || true
  fi
}

handle_interrupt() {
  cleanup || exit 1
  exit 130
}

trap handle_interrupt INT TERM HUP
trap cleanup EXIT

# The terminal signals Bash alone, rather than Nx's whole prefork task tree.
# --wait also preserves the child status if native setsid needs to fork.
setsid --wait pnpm exec nx run-many -t dev --projects="$project_csv" --parallel="$parallelism" --outputStyle="$output_style" "${nx_configuration[@]}" &
nx_pid=$!
wait "$nx_pid"
