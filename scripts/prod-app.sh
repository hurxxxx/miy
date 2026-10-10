#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/ops/compose/miy-prod.app.yml"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_PROJECT_NAME="miy-prod-app"
IMAGE_REPOSITORY="miy-app"
CURRENT_IMAGE="$IMAGE_REPOSITORY:prod"
PREVIOUS_IMAGE="$IMAGE_REPOSITORY:prod-previous"
CANDIDATE_IMAGE="$IMAGE_REPOSITORY:candidate"
ROLLBACK_ENV_FILE=""
ROLLBACK_IMAGE=""
ROLLBACK_BUNDLE=""
RELEASE_MR=""
DEPLOY_IMAGE=""
RELEASE_SOURCE_REVISION=""
RELEASE_REVISION=""
RELEASE_TREE=""
RELEASE_PLATFORM=""
RELEASE_BENTO_URL_SHA256=""
RELEASE_PIPELINE=""
RELEASE_CONTRACT=""
TOPOLOGY="legacy"
RELEASE_SLICE="full"
OFFICIAL_API_IMAGE=""
OFFICIAL_WORKER_IMAGE=""
ROLLBACK_TOPOLOGY="legacy"
ROLLBACK_OFFICIAL_API_IMAGE=""
ROLLBACK_OFFICIAL_WORKER_IMAGE=""
FIRST_PARTY_COMPOSE_FILE="$ROOT_DIR/ops/first-party/compose.override.yml.example"
OFFICIAL_API_REPOSITORY="miy-official-api"
OFFICIAL_WORKER_REPOSITORY="miy-official-worker"

usage() {
  echo "Usage: $0 {prepare|deploy|migrate|rollback|smoke|status|up}" >&2
  echo "  prepare --release-mr <iid>" >&2
  echo "  deploy --release-mr <iid> --image sha256:<image-id> [--rollback-env-file <secure-backup> --rollback-image sha256:<image-id>]" >&2
  echo "  rollback [--rollback-env-file <secure-backup> --rollback-image sha256:<image-id>]" >&2
  echo "  first-party: --topology first-party [--slice official] --official-api-image sha256:<id> --official-worker-image sha256:<id>" >&2
  echo "  first-party deploy/rollback requires a secure rollback image/environment pair; add --rollback-topology first-party and both --rollback-official-*-image IDs for a split prior runtime." >&2
}

require_prod_checkout() {
  if [[ "$(basename "$ROOT_DIR")" != "prod" ]]; then
    echo "Refusing to manage the production app outside the prod checkout: $ROOT_DIR" >&2
    exit 1
  fi
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Production runtime env file is missing: $ENV_FILE" >&2
    exit 1
  fi
}

require_release_source() {
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
    echo "Refusing to deploy from a dirty production checkout." >&2
    exit 1
  fi
  local head_revision main_revision
  head_revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  main_revision="$(git -C "$ROOT_DIR" rev-parse origin/main)"
  if [[ "$head_revision" != "$main_revision" ]]; then
    echo "Refusing to deploy a production checkout that does not match origin/main." >&2
    exit 1
  fi
}

validate_environment() {
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then
    node "$ROOT_DIR/scripts/prod-app-config.mjs" "$ENV_FILE" --topology first-party || return 1
    require_first_party_ports_available
    return
  fi
  node "$ROOT_DIR/scripts/prod-app-config.mjs" "$ENV_FILE"
}

require_first_party_ports_available() {
  local port service id command expected_image definition hash
  command -v ss >/dev/null 2>&1 || return 1
  for port in 18779 18780; do
    if ! ss -H -ltn "sport = :$port" | grep -q .; then continue; fi
    service=api
    [[ "$port" != 18780 ]] || service=official-api
    id="$(compose ps --all --quiet "$service")" || return 1
    [[ "$id" =~ ^[a-f0-9]{64}$ ]] || return 1
    expected_image="$(runtime_service_image "$service" "$(image_id "$CURRENT_IMAGE")")" || return 1
    definition="$(prior_runtime_definition "$id")" || return 1
    hash="${definition##*|}"
    [[ "$hash" =~ ^[a-f0-9]{64}$ && "$definition" == "$expected_image|$COMPOSE_PROJECT_NAME|$service|$hash" ]] || return 1
    [[ "$(docker inspect --format '{{.State.Running}}|{{.HostConfig.NetworkMode}}' "$id")" == 'true|host' ]] || return 1
    command="$(docker inspect --format '{{json .Config.Cmd}}' "$id")" || return 1
    if [[ "$service" == api ]]; then
      [[ "$command" == *miy_api.platform_runtime:app* && "$command" == *'--host 127.0.0.1'* && "$command" == *'--port 18779'* ]] || return 1
    else
      [[ "$command" == *miy_official_api.runtime:app* && "$command" == *'"--host","127.0.0.1"'* && "$command" == *'"--port","18780"'* ]] || return 1
    fi
  done
}

acquire_operation_lock() {
  local lock_directory="$ROOT_DIR/.runtime/prod-app"
  if ! command -v flock >/dev/null 2>&1; then
    echo "Production release operations require flock from util-linux." >&2
    return 1
  fi
  mkdir -p "$lock_directory" || return 1
  chmod 700 "$lock_directory" || return 1
  exec 9>"$lock_directory/operation.lock"
  chmod 600 "$lock_directory/operation.lock" || return 1
  if ! flock -n 9; then
    echo "Another production release operation is already running." >&2
    return 1
  fi
}

require_terminal_broker_port_available() {
  local port expected_container expected_running expected_binding
  local config_script="${1:-$ROOT_DIR/scripts/prod-app-config.mjs}"
  local config_env="${2:-$ENV_FILE}"
  port="$(
    node "$config_script" \
      "$config_env" \
      --print-hermes-terminal-broker-port
  )" || return 1
  expected_container="${3:-miy-prod-hermes-terminal-broker}"

  if ! command -v ss >/dev/null 2>&1; then
    echo "Production port preflight requires the ss command." >&2
    return 1
  fi
  if ! ss -H -ltn "sport = :$port" | grep -q .; then
    return 0
  fi

  expected_running="$(
    docker inspect --format '{{.State.Running}}' "$expected_container" 2>/dev/null || true
  )"
  expected_binding="$(
    docker inspect \
      --format '{{range (index .NetworkSettings.Ports "18765/tcp")}}{{printf "%s:%s" .HostIp .HostPort}}{{end}}' \
      "$expected_container" 2>/dev/null || true
  )"
  if [[ "$expected_running" == "true" && "$expected_binding" == "127.0.0.1:$port" ]]; then
    return 0
  fi

  echo \
    "Production Hermes Terminal broker port 127.0.0.1:$port is already in use by another listener; refusing before release preparation or migration." \
    >&2
  return 1
}

compose() (
  # Compose interpolation prefers exported shell values over --env-file. The
  # validated release file owns product/provider configuration in both paths.
  local compose_env_name compose_product_prefix
  compose_product_prefix="${COMPOSE_PROJECT_NAME%-prod-app}"
  compose_product_prefix="${compose_product_prefix//-/_}"
  compose_product_prefix="${compose_product_prefix^^}_"
  while IFS= read -r compose_env_name; do
    case "$compose_env_name" in
      MIY_*|"$compose_product_prefix"*|OPENROUTER_API_KEY) unset "$compose_env_name" || return 1 ;;
    esac
  done < <(compgen -e)
  local -a override=()
  if [[ "${TOPOLOGY:-legacy}" == "first-party" ]]; then
    local api_image worker_image
    api_image="${COMPOSE_OFFICIAL_API_IMAGE:-$(image_id "$OFFICIAL_API_REPOSITORY:prod")}" || return 1
    worker_image="${COMPOSE_OFFICIAL_WORKER_IMAGE:-$(image_id "$OFFICIAL_WORKER_REPOSITORY:prod")}" || return 1
    [[ "$api_image" =~ ^sha256:[a-f0-9]{64}$ && "$worker_image" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
    # These are private operation bindings, never values from the product .env.
    export MIY_OFFICIAL_API_IMAGE="$api_image" MIY_OFFICIAL_WORKER_IMAGE="$worker_image"
    override=(-f "$FIRST_PARTY_COMPOSE_FILE")
  fi
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    "${override[@]}" \
    "$@"
)

image_revision() {
  docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    "${1:?image is required}"
}

image_id() {
  docker image inspect --format '{{.Id}}' "${1:?image is required}"
}

image_label() {
  local image="${1:?image is required}"
  local label="${2:?label is required}"
  docker image inspect --format "{{ index .Config.Labels \"$label\" }}" "$image"
}

load_release_contract() {
  local release_mr="${1:?release MR is required}"
  local evidence bento_server_url
  local -a fields
  evidence="$(
    node "$ROOT_DIR/scripts/prod-app-release.mjs" "$ROOT_DIR" "$release_mr"
  )" || return 1
  mapfile -t fields <<<"$evidence"
  if [[ "${#fields[@]}" -ne 3 ]]; then
    echo "Release MR evidence returned an invalid contract." >&2
    return 1
  fi
  RELEASE_SOURCE_REVISION="${fields[0]}"
  RELEASE_REVISION="${fields[1]}"
  RELEASE_PIPELINE="${fields[2]}"
  RELEASE_TREE="$(git -C "$ROOT_DIR" rev-parse 'HEAD^{tree}')" || return 1
  RELEASE_PLATFORM="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')" || return 1
  if [[ ! "$RELEASE_PLATFORM" =~ ^linux/(amd64|arm64)$ ]]; then
    echo "Production image platform must be linux/amd64 or linux/arm64." >&2
    return 1
  fi
  bento_server_url="$(
    node "$ROOT_DIR/scripts/prod-app-config.mjs" \
      "$ENV_FILE" \
      --print-bento-server-url
  )" || return 1
  RELEASE_BENTO_URL_SHA256="$(
    printf '%s' "$bento_server_url" | sha256sum | awk '{print $1}'
  )" || return 1
  RELEASE_CONTRACT="$(
    printf '%s\n' \
      'miy-production-release-v1' \
      "$RELEASE_REVISION" \
      "$RELEASE_SOURCE_REVISION" \
      "$RELEASE_TREE" \
      "$RELEASE_PLATFORM" \
      "$RELEASE_BENTO_URL_SHA256" \
      | sha256sum | awk '{print $1}'
  )" || return 1
}

candidate_matches_contract() {
  local image="${1:?image is required}"
  [[ "$(image_label "$image" 'io.miy.release.contract')" == "$RELEASE_CONTRACT" ]]
}

verify_release_image() {
  local image="${1:?image is required}"
  local expected_revision="${2:?revision is required}"
  local role="${3:-platform}"
  if [[ "$(image_revision "$image")" != "$expected_revision" ]]; then
    echo "Release image revision does not match the production source." >&2
    return 1
  fi
  if [[ "$role" != "platform" ]]; then
    [[ "$(image_label "$image" 'io.miy.artifact.activation')" == 'first-party-runtime' \
      && "$(image_label "$image" 'io.miy.artifact.source-dirty')" == 'false' ]] || return 1
    case "$role" in
      official-api)
        docker run --rm --network none --entrypoint /bin/sh "$image" -ec '
          test "$(id -u)" = 10001
          test -x apps/api/.venv/bin/uvicorn
          test -f dist/apps/official-suite/index.html
          test -f scripts/blocknote-collab-codec.mjs
          apps/api/.venv/bin/python -c "from importlib.util import find_spec; assert find_spec(\"miy_official_api.runtime\")"
          node scripts/blocknote-collab-codec.mjs encode </dev/null >/dev/null
        '
        ;;
      official-worker)
        docker run --rm --network none --entrypoint /bin/sh "$image" -ec '
          test "$(id -u)" = 10001
          test -x apps/worker/.venv/bin/celery
          test -f scripts/blocknote-collab-codec.mjs
          apps/worker/.venv/bin/python -c "from importlib.util import find_spec; assert find_spec(\"miy_official_worker.runtime\")"
          node scripts/blocknote-collab-codec.mjs encode </dev/null >/dev/null
        '
        ;;
      *) return 1 ;;
    esac
    return
  fi
  docker run --rm --entrypoint /bin/sh "$image" -ec '
    test "$(id -u)" = 10001
    test -x apps/api/.venv/bin/uvicorn
    test -x apps/worker/.venv/bin/celery
    test -f dist/apps/web/index.html
    test -f dist/apps/official-suite/index.html
    test -f dist/apps/official-suite/.miy-platform-build-id
    test -f ops/first-party/gateway.py
    test -x /usr/sbin/nginx
    /usr/sbin/nginx -v
    apps/api/.venv/bin/python -c "from pathlib import Path; core=Path(\"dist/apps/web/.miy-build-id\"); expected=core.read_text().strip() if core.is_file() else \"\"; assert Path(\"dist/apps/official-suite/.miy-platform-build-id\").read_text().strip() == expected"
    test -f scripts/blocknote-collab-codec.mjs
    node --version >/dev/null
    node scripts/blocknote-collab-codec.mjs encode </dev/null >/dev/null
    apps/api/.venv/bin/python -c "import miy_api"
    MIY_POSTGRES_DSN=sqlite:///migration-config-smoke.db \
      apps/api/.venv/bin/python -c \
      "from alembic.script import ScriptDirectory; from miy_api.core.db import _alembic_config; assert ScriptDirectory.from_config(_alembic_config()).get_current_head()"
    apps/api/.venv/bin/python -c "import opf, torch"
    apps/worker/.venv/bin/python -c "import miy_worker"
  '
}

verify_files_gate_executable() {
  local image="${1:?immutable image is required}"
  if [[ ! "$image" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "Files cutover gate requires an immutable image ID." >&2
    return 1
  fi
  docker run --rm --network none --entrypoint /bin/sh "$image" \
    -ec 'test -x /usr/bin/timeout'
}

verify_candidate_image() {
  local image="${1:?image is required}"
  local role="${2:-platform}"
  local actual_id
  actual_id="$(image_id "$image")" || return 1
  if [[ ! "$actual_id" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "Release candidate does not have an immutable image ID." >&2
    return 1
  fi
  verify_release_image "$image" "$RELEASE_REVISION" "$role" || return 1
  local label expected
  while IFS=$'\t' read -r label expected; do
    if [[ "$(image_label "$image" "$label")" != "$expected" ]]; then
      echo "Release candidate metadata does not match the verified release." >&2
      return 1
    fi
  done <<EOF
io.miy.release.contract	$RELEASE_CONTRACT
io.miy.release.source-revision	$RELEASE_SOURCE_REVISION
io.miy.release.tree	$RELEASE_TREE
io.miy.release.platform	$RELEASE_PLATFORM
io.miy.release.bento-url-sha256	$RELEASE_BENTO_URL_SHA256
io.miy.release.merge-request	$RELEASE_MR
EOF
  local recorded_pipeline
  recorded_pipeline="$(
    image_label "$image" 'io.miy.release.pipeline'
  )" || return 1
  if [[ ! "$recorded_pipeline" =~ ^[1-9][0-9]*$ ]]; then
    echo "Release candidate does not record valid build-time pipeline evidence." >&2
    return 1
  fi
  if [[ "$role" == 'platform' ]]; then verify_files_gate_executable "$actual_id"; fi
}

prepare_candidate_image() {
  local role="${1:-platform}" repository="$IMAGE_REPOSITORY" dockerfile='ops/app/Dockerfile' target='runtime'
  case "$role" in
    platform) ;;
    official-api) repository="$OFFICIAL_API_REPOSITORY"; dockerfile='ops/official-suite-api/Dockerfile'; target='service-runtime' ;;
    official-worker) repository="$OFFICIAL_WORKER_REPOSITORY"; dockerfile='ops/official-suite-worker/Dockerfile' ;;
    *) return 1 ;;
  esac
  local bento_server_url build_image candidate_image="$repository:candidate" platform_build_id=''
  if [[ "$role" == 'platform' ]]; then candidate_image="$CANDIDATE_IMAGE"; fi
  if [[ "$role" == 'official-api' ]]; then
    platform_build_id="$(platform_web_build_id "${PREPARED_PLATFORM_IMAGE:-$CURRENT_IMAGE}")" || return 1
  fi
  build_image="$repository:candidate-${RELEASE_CONTRACT:0:12}"
  if [[ "$role" == 'official-api' ]]; then
    local compatibility_digest
    compatibility_digest="$(printf '%s' "$platform_build_id" | sha256sum | awk '{print $1}')" || return 1
    build_image="$build_image-${compatibility_digest:0:12}"
  fi
  if docker image inspect "$candidate_image" >/dev/null 2>&1 \
    && candidate_matches_contract "$candidate_image" \
    && { [[ "$role" != 'official-api' ]] || require_official_web_compatibility "${PREPARED_PLATFORM_IMAGE:-$CURRENT_IMAGE}" "$candidate_image"; }; then
    verify_candidate_image "$candidate_image" "$role" || return 1
    image_id "$candidate_image"
    return
  fi
  if docker image inspect "$build_image" >/dev/null 2>&1; then
    verify_candidate_image "$build_image" "$role" || return 1
    docker tag "$build_image" "$candidate_image" || return 1
    image_id "$candidate_image"
    return
  fi
  node "$ROOT_DIR/scripts/docker-storage.mjs" check >&2 || return 1
  bento_server_url="$(
    node "$ROOT_DIR/scripts/prod-app-config.mjs" \
      "$ENV_FILE" \
      --print-bento-server-url
  )" || return 1
  git -C "$ROOT_DIR" archive --format=tar HEAD \
    | docker build \
    --file "$dockerfile" \
    --target "$target" \
    --platform "$RELEASE_PLATFORM" \
    --build-arg "MIY_BENTO_SERVER_URL=$bento_server_url" \
    --build-arg "MIY_BUILD_REVISION=$RELEASE_REVISION" \
    --build-arg "MIY_BUILD_SOURCE_DIRTY=false" \
    --build-arg "MIY_PLATFORM_WEB_BUILD_ID=$platform_build_id" \
    --build-arg "MIY_RELEASE_CONTRACT=$RELEASE_CONTRACT" \
    --build-arg "MIY_RELEASE_SOURCE_REVISION=$RELEASE_SOURCE_REVISION" \
    --build-arg "MIY_RELEASE_TREE=$RELEASE_TREE" \
    --build-arg "MIY_RELEASE_PLATFORM=$RELEASE_PLATFORM" \
    --build-arg "MIY_RELEASE_BENTO_URL_SHA256=$RELEASE_BENTO_URL_SHA256" \
    --build-arg "MIY_RELEASE_MR=$RELEASE_MR" \
    --build-arg "MIY_RELEASE_PIPELINE=$RELEASE_PIPELINE" \
    --tag "$build_image" \
    - >&2 || return 1
  verify_candidate_image "$build_image" "$role" || return 1
  docker tag "$build_image" "$candidate_image" || return 1
  image_id "$candidate_image"
}

require_deploy_image() {
  local image="${1:?image is required}"
  local role="${2:-platform}"
  local actual_id
  if [[ ! "$image" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "Deployment requires the full immutable candidate image ID." >&2
    return 1
  fi
  actual_id="$(image_id "$image")" || return 1
  if [[ "$actual_id" != "$image" ]]; then
    echo "Deployment image ID does not resolve to the requested candidate." >&2
    return 1
  fi
  verify_candidate_image "$image" "$role"
}

promote_image() {
  local image="${1:?image is required}"
  local CURRENT_IMAGE="${2:-$CURRENT_IMAGE}" PREVIOUS_IMAGE="${3:-$PREVIOUS_IMAGE}"
  local candidate_id current_id
  candidate_id="$(image_id "$image")" || return 1
  if docker image inspect "$CURRENT_IMAGE" >/dev/null 2>&1; then
    current_id="$(image_id "$CURRENT_IMAGE")" || return 1
    if [[ "$current_id" == "$candidate_id" ]]; then
      return 0
    fi
    docker tag "$CURRENT_IMAGE" "$PREVIOUS_IMAGE" || return 1
  fi
  docker tag "$image" "$CURRENT_IMAGE" || return 1
}

run_migrations() {
  compose run --rm migrate
}

runtime_services() {
  printf '%s\n' api worker beat
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then printf '%s\n' official-api official-worker gateway; fi
}

runtime_service_image() {
  case "${1:?service is required}" in
    official-api) image_id "$OFFICIAL_API_REPOSITORY:prod" ;;
    official-worker) image_id "$OFFICIAL_WORKER_REPOSITORY:prod" ;;
    *) printf '%s\n' "${2:?platform image is required}" ;;
  esac
}

current_runtime_topology() {
  local id command
  id="$(TOPOLOGY=legacy compose ps --all --quiet worker)" || return 1
  if [[ -z "$id" ]]; then printf 'none\n'; return; fi
  command="$(docker inspect --format '{{json .Config.Cmd}}' "$id")" || return 1
  case "$command" in
    *miy_worker.celery_app:celery_app*) printf 'legacy\n' ;;
    *miy_worker.first_party_platform:celery_app*) printf 'first-party\n' ;;
    *) echo 'Current worker profile is not a known owned runtime; activation HOLD.' >&2; return 1 ;;
  esac
}

drain_current_workers() {
  local current="${1:?current topology is required}" id hostname service profile
  local -a bindings=() services=(worker)
  if [[ "$current" == 'first-party' ]]; then services+=(official-worker); fi
  for service in "${services[@]}"; do
    id="$(compose ps --all --quiet "$service")" || return 1
    [[ "$id" =~ ^[a-f0-9]{64}$ ]] || return 1
    hostname="$(docker inspect --format '{{.Config.Hostname}}' "$id")" || return 1
    [[ "$hostname" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1
    if [[ "$current" == 'legacy' ]]; then
      bindings+=(--consumer "prod-worker@$hostname|legacy")
    elif [[ "$service" == 'worker' ]]; then
      bindings+=(--consumer "prod-platform-worker@$hostname|platform")
    else
      bindings+=(--consumer "prod-official-worker@$hostname|official")
    fi
  done
  id="$(compose ps --all --quiet worker)" || return 1
  command -v timeout >/dev/null 2>&1 || return 1
  timeout --signal=TERM --kill-after=5 3930 \
    docker exec -i "$id" apps/worker/.venv/bin/python - "${bindings[@]}" \
    <"$ROOT_DIR/scripts/prod-app-drain.py"
}

stop_previous_writers() {
  # Honor each service definition: worker graceful shutdown can take 65 minutes.
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then
    local current
    current="$(current_runtime_topology)" || return 1
    [[ "$current" != 'none' ]] || return 0
    if [[ "$current" == 'legacy' ]]; then
      compose stop api beat || return 1
      drain_current_workers legacy || return 1
      compose stop worker
    else
      compose stop gateway || return 1
      compose stop api official-api beat || return 1
      compose stop worker official-worker
    fi
    return
  fi
  compose stop api worker beat
}

check_files_content_cutover() {
  compose run --rm --no-deps --entrypoint /usr/bin/timeout migrate \
    --signal=TERM --kill-after=5 130 \
    apps/api/.venv/bin/python -m miy_api.domains.files.cutover_gate
}

start_forward_runtime() {
  FORWARD_START_ATTEMPTED=0
  stop_previous_writers && run_migrations && check_files_content_cutover || return 1
  FORWARD_START_ATTEMPTED=1
  start_runtime && run_smoke
}

prior_runtime_definition() {
  docker inspect --format \
    '{{.Image}}|{{ index .Config.Labels "com.docker.compose.project" }}|{{ index .Config.Labels "com.docker.compose.service" }}|{{ index .Config.Labels "com.docker.compose.config-hash" }}' \
    "${1:?container is required}"
}

capture_prior_runtime() {
  local image="${1:?pre-up image is required}" service id hash definition actual_image project role index state status running health present=0 recoverable=1
  local -a services=() ids=() definitions=()
  mapfile -t services < <(runtime_services)
  UP_PRIOR_IMAGE=""
  UP_PRIOR_IDS=()
  UP_PRIOR_DEFINITIONS=()
  for service in "${services[@]}"; do
    id="$(compose ps --all --quiet "$service")" || return 1
    if [[ -n "$id" ]]; then
      [[ "$id" =~ ^[a-f0-9]{64}$ ]] || return 1
      present=$((present + 1))
    fi
    ids+=("$id")
  done
  # First startup has no recovery target; only the forward gate may start it.
  [[ "$present" -ne 0 ]] || return 0
  [[ "$present" -eq "${#services[@]}" ]] || return 1
  for index in "${!services[@]}"; do
    service="${services[$index]}"
    definition="$(prior_runtime_definition "${ids[$index]}")" || return 1
    IFS='|' read -r actual_image project role hash <<<"$definition"
    [[ "$hash" =~ ^[a-f0-9]{64}$ \
      && "$definition" == "$(runtime_service_image "$service" "$image")|$COMPOSE_PROJECT_NAME|$service|$hash" ]] || return 1
    state="$(docker inspect --format '{{.State.Status}}|{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${ids[$index]}")" || return 1
    IFS='|' read -r status running health <<<"$state"
    [[ "$state" == "$status|$running|$health" ]] || return 1
    case "$status" in
      created|running|paused|restarting|exited|dead) ;;
      *) return 1 ;;
    esac
    case "$running" in
      true|false) ;;
      *) return 1 ;;
    esac
    case "$health" in
      ''|healthy|starting|unhealthy) ;;
      *) return 1 ;;
    esac
    [[ "$state" == 'running|true|healthy' ]] || recoverable=0
    definitions+=("$definition")
  done
  # Known nonhealthy/stopped containers may proceed through the forward gate,
  # but cannot become a healthy automatic recovery target if it refuses.
  [[ "$recoverable" == 1 ]] || return 0
  UP_PRIOR_IMAGE="$image"
  UP_PRIOR_IDS=("${ids[@]}")
  UP_PRIOR_DEFINITIONS=("${definitions[@]}")
}

wait_prior_runtime() {
  local deadline=$((SECONDS + 600)) index service id state ready
  local -a services=()
  mapfile -t services < <(runtime_services)
  while ((SECONDS < deadline)); do
    [[ "$(image_id "$CURRENT_IMAGE")" == "$UP_PRIOR_IMAGE" ]] || return 1
    ready=1
    for index in "${!services[@]}"; do
      service="${services[$index]}"
      id="$(compose ps --all --quiet "$service")" || return 1
      [[ "$id" == "${UP_PRIOR_IDS[$index]}" \
        && "$(prior_runtime_definition "$id")" == "${UP_PRIOR_DEFINITIONS[$index]}" ]] || return 1
      state="$(docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")" || return 1
      case "$state" in
        'running|healthy') ;;
        'running|starting') ready=0 ;;
        *) return 1 ;;
      esac
    done
    [[ "$ready" != 1 ]] || return 0
    sleep 2 || return 1
  done
  return 1
}

restore_same_runtime() {
  local expected_image="${1:?pre-up image identity is required}" index service id definition
  local -a services=()
  mapfile -t services < <(runtime_services)
  # No image-tag inference, no newly created containers and no partial-start recovery.
  if [[ "${UP_PRIOR_IMAGE:-}" != "$expected_image" \
    || "${FORWARD_START_ATTEMPTED:-0}" != 0 \
    || "$(image_id "$CURRENT_IMAGE")" != "$expected_image" ]]; then
    echo "No unchanged attested pre-up runtime is available; refusing restoration." >&2
    return 1
  fi
  for index in "${!services[@]}"; do
    service="${services[$index]}"
    id="$(compose ps --all --quiet "$service")" || return 1
    [[ "$id" == "${UP_PRIOR_IDS[$index]}" ]] || return 1
    definition="$(prior_runtime_definition "$id")" || return 1
    [[ "$definition" == "${UP_PRIOR_DEFINITIONS[$index]}" ]] || return 1
  done
  # Start those existing definitions only; never force-recreate a refused candidate.
  docker start "${UP_PRIOR_IDS[@]}" >/dev/null && wait_prior_runtime && run_smoke
}

start_runtime() {
  local -a official_services=()
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then official_services=(official-api official-worker gateway); fi
  compose up \
    --detach \
    --force-recreate \
    --remove-orphans \
    --wait \
    --wait-timeout 600 \
    hermes-bootstrap hermes-gateway hermes-dashboard \
    hermes-terminal-egress hermes-terminal-broker \
    privacy-filter api worker beat "${official_services[@]}"
}

run_smoke() {
  local revision
  revision="$(image_revision "$CURRENT_IMAGE")" || return 1
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then
    MIY_EXPECTED_REVISION="$revision" \
      MIY_EXPECTED_OFFICIAL_REVISION="$(image_revision "$OFFICIAL_API_REPOSITORY:prod")" \
      node "$ROOT_DIR/scripts/prod-app-smoke.mjs" "$ENV_FILE" --topology first-party
    return
  fi
  MIY_EXPECTED_REVISION="$revision" \
    node "$ROOT_DIR/scripts/prod-app-smoke.mjs" "$ENV_FILE"
}

platform_web_build_id() {
  local value
  value="$(docker run --rm --network none --entrypoint /bin/sh "${1:?platform image is required}" \
    -ec 'if test -f dist/apps/web/.miy-build-id; then test "$(wc -c <dist/apps/web/.miy-build-id)" -le 129; cat dist/apps/web/.miy-build-id; fi')" || return 1
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || return 1
  printf '%s\n' "$value"
}

require_official_web_compatibility() {
  local expected actual
  expected="$(platform_web_build_id "${1:?platform image is required}")" || return 1
  actual="$(docker run --rm --network none --entrypoint /bin/sh "${2:?official API image is required}" \
    -ec 'test -f dist/apps/official-suite/.miy-platform-build-id; test "$(wc -c <dist/apps/official-suite/.miy-platform-build-id)" -le 129; cat dist/apps/official-suite/.miy-platform-build-id')" || return 1
  [[ "$actual" == "$expected" ]] || {
    echo 'Official frontend is not compatible with the exact platform web artifact; activation HOLD.' >&2
    return 1
  }
}

require_official_gateway_compatibility() {
  local platform_image="${1:?platform image is required}" official_image="${2:?official API image is required}"
  local image projection prior='' api_prefix
  api_prefix="$(node "$ROOT_DIR/scripts/prod-app-config.mjs" "$ENV_FILE" --print-api-prefix)" || return 1
  [[ "$api_prefix" =~ ^/[A-Za-z0-9/_-]+$ && "$api_prefix" != */ ]] || return 1
  for image in "$platform_image" "$official_image"; do
    projection="$(docker run --rm --network none --entrypoint apps/api/.venv/bin/python "$image" \
      -m miy_api.first_party_routes --json --api-prefix "$api_prefix")" || return 1
    [[ "${#projection}" -le 1048576 ]] || return 1
    printf '%s' "$projection" | python3 -c '
import json,sys
projection=json.load(sys.stdin)
assert isinstance(projection,dict) and set(projection)=={"api_prefix","official_patterns"}
assert projection["api_prefix"]==sys.argv[1]
patterns=projection["official_patterns"]
assert isinstance(patterns,list) and patterns and all(isinstance(pattern,str) for pattern in patterns)
assert patterns==sorted(set(patterns))
' "$api_prefix" || return 1
    if [[ -n "$prior" && "$projection" != "$prior" ]]; then
      echo 'Official route ownership differs from the retained Core gateway; use a coordinated full release.' >&2
      return 1
    fi
    prior="$projection"
  done
}

require_official_slice() {
  [[ "$(current_runtime_topology)" == 'first-party' && "$ROLLBACK_TOPOLOGY" == 'first-party' ]] || return 1
  cmp -s "$ENV_FILE" "$ROLLBACK_BUNDLE/.env" || {
    echo 'An official slice cannot change shared production configuration.' >&2; return 1;
  }
  local platform_image prior_revision
  platform_image="$(image_id "$CURRENT_IMAGE")" || return 1
  capture_prior_runtime "$platform_image" || return 1
  [[ "${UP_PRIOR_IMAGE:-}" == "$platform_image" ]] || return 1
  slice_platform_identity || return 1
  prior_revision="$(image_revision "$OFFICIAL_API_REPOSITORY:prod")" || return 1
  [[ "$(image_revision "$OFFICIAL_WORKER_REPOSITORY:prod")" == "$prior_revision" ]] || return 1
  python3 "$ROOT_DIR/scripts/prod-app-official-slice.py" "$ROOT_DIR" "$prior_revision" || return 1
  require_official_web_compatibility "$platform_image" "$OFFICIAL_API_IMAGE" || return 1
  require_official_gateway_compatibility "$platform_image" "$OFFICIAL_API_IMAGE"
}

slice_platform_identity() {
  local image index service id definition hash state
  local -a services=(api worker beat gateway) ids=() definitions=()
  image="$(image_id "$CURRENT_IMAGE")" || return 1
  [[ -z "${SLICE_PLATFORM_IMAGE:-}" || "$image" == "$SLICE_PLATFORM_IMAGE" ]] || return 1
  for index in "${!services[@]}"; do
    service="${services[$index]}"
    id="$(compose ps --all --quiet "$service")" || return 1
    [[ "$id" =~ ^[a-f0-9]{64}$ ]] || return 1
    definition="$(prior_runtime_definition "$id")" || return 1
    hash="${definition##*|}"
    [[ "$hash" =~ ^[a-f0-9]{64}$ && "$definition" == "$image|$COMPOSE_PROJECT_NAME|$service|$hash" ]] || return 1
    state="$(docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")" || return 1
    [[ "$state" == 'running|healthy' ]] || return 1
    if [[ -n "${SLICE_PLATFORM_IMAGE:-}" ]]; then
      [[ "$id" == "${SLICE_PLATFORM_IDS[$index]}" && "$definition" == "${SLICE_PLATFORM_DEFINITIONS[$index]}" ]] || return 1
    fi
    ids+=("$id"); definitions+=("$definition")
  done
  SLICE_PLATFORM_IMAGE="$image"
  SLICE_PLATFORM_IDS=("${ids[@]}")
  SLICE_PLATFORM_DEFINITIONS=("${definitions[@]}")
}

prepare_rollback_runtime() {
  local expected_image="${1:?expected image is required}"
  if [[ -z "$ROLLBACK_IMAGE" ]]; then
    return 0
  fi
  local -a extra=()
  if [[ "${ROLLBACK_TOPOLOGY:-legacy}" == 'first-party' ]]; then
    local expected_official_tag='prod'
    if [[ "${COMMAND:-deploy}" == 'rollback' ]]; then expected_official_tag='prod-previous'; fi
    extra=(--topology first-party --official-api-image "$ROLLBACK_OFFICIAL_API_IMAGE" --official-worker-image "$ROLLBACK_OFFICIAL_WORKER_IMAGE"
      --expected-official-api-image "$OFFICIAL_API_REPOSITORY:$expected_official_tag" --expected-official-worker-image "$OFFICIAL_WORKER_REPOSITORY:$expected_official_tag")
  fi
  ROLLBACK_BUNDLE="$(
    node "$ROOT_DIR/scripts/prod-app-rollback.mjs" prepare \
      "$ROOT_DIR" "$ROLLBACK_ENV_FILE" "$ROLLBACK_IMAGE" "$expected_image" "${extra[@]}"
  )" || return 1
  local metadata
  local -a fields
  metadata="$(node "$ROOT_DIR/scripts/prod-app-rollback.mjs" runtime "$ROLLBACK_BUNDLE")" || return 1
  mapfile -t fields <<<"$metadata"
  [[ "${#fields[@]}" -eq 5 || "${#fields[@]}" -eq 9 ]] || return 1
  ROLLBACK_COMPOSE_FILE="$ROLLBACK_BUNDLE/${fields[0]}"
  ROLLBACK_PROJECT="${fields[1]}"
  ROLLBACK_CURRENT_IMAGE="${fields[2]}"
  ROLLBACK_BROKER="${fields[3]}"
  ROLLBACK_REVISION_ENV="${fields[4]}"
  if [[ "${#fields[@]}" -eq 9 ]]; then
    ROLLBACK_TOPOLOGY='first-party'
    ROLLBACK_OFFICIAL_API_IMAGE="${fields[5]}"
    ROLLBACK_OFFICIAL_WORKER_IMAGE="${fields[6]}"
    ROLLBACK_FIRST_PARTY_COMPOSE_FILE="$ROLLBACK_BUNDLE/${fields[7]}"
    ROLLBACK_OFFICIAL_REVISION="${fields[8]}"
  fi
  require_terminal_broker_port_available \
    "$ROLLBACK_BUNDLE/scripts/prod-app-config.mjs" "$ROLLBACK_BUNDLE/.env" "$ROLLBACK_BROKER" || return 1
}

rollback_compose() {
  local ENV_FILE="$ROLLBACK_BUNDLE/.env"
  local COMPOSE_FILE="${ROLLBACK_COMPOSE_FILE:?pinned rollback Compose is required}"
  local COMPOSE_PROJECT_NAME="${ROLLBACK_PROJECT:?pinned rollback project is required}"
  local TOPOLOGY="${ROLLBACK_TOPOLOGY:-legacy}"
  local FIRST_PARTY_COMPOSE_FILE="${ROLLBACK_FIRST_PARTY_COMPOSE_FILE:-${FIRST_PARTY_COMPOSE_FILE:-}}"
  local COMPOSE_OFFICIAL_API_IMAGE="${ROLLBACK_OFFICIAL_API_IMAGE:-}"
  local COMPOSE_OFFICIAL_WORKER_IMAGE="${ROLLBACK_OFFICIAL_WORKER_IMAGE:-}"
  compose "$@"
}

restore_previous_runtime() {
  if [[ -n "$ROLLBACK_IMAGE" ]]; then
    if [[ -z "$ROLLBACK_BUNDLE" ]]; then
      echo "An explicit rollback requires a validated image/environment bundle." >&2
      return 1
    fi
    echo "Restoring the pinned production image, environment, and deployment definitions." >&2
    if [[ "${RELEASE_SLICE:-full}" == 'official' ]]; then
      # The slice cannot change environment or topology. Keep every existing
      # platform/Beat definition and container identity untouched on recovery.
      [[ "$ROLLBACK_TOPOLOGY" == 'first-party' ]] || return 1
      cmp -s "$ENV_FILE" "$ROLLBACK_BUNDLE/.env" || return 1
      [[ "$(current_runtime_topology)" == 'first-party' ]] || return 1
      local platform_image platform_revision
      platform_image="$(image_id "$CURRENT_IMAGE")" || return 1
      # A failed official candidate need not be healthy to restore its prior
      # pair. The platform/Beat must remain the exact healthy retained runtime.
      slice_platform_identity || return 1
      platform_revision="$(image_revision "$CURRENT_IMAGE")" || return 1
      python3 "$ROOT_DIR/scripts/prod-app-official-slice.py" "$ROOT_DIR" "$ROLLBACK_OFFICIAL_REVISION" "$platform_revision" || return 1
      require_official_web_compatibility "$platform_image" "$ROLLBACK_OFFICIAL_API_IMAGE" || return 1
      require_official_gateway_compatibility "$platform_image" "$ROLLBACK_OFFICIAL_API_IMAGE" || return 1
      compose stop official-api official-worker || return 1
      docker tag "$ROLLBACK_OFFICIAL_API_IMAGE" "$OFFICIAL_API_REPOSITORY:prod" || return 1
      docker tag "$ROLLBACK_OFFICIAL_WORKER_IMAGE" "$OFFICIAL_WORKER_REPOSITORY:prod" || return 1
      rollback_compose up -d --no-deps --force-recreate --wait --wait-timeout 600 official-api official-worker || return 1
      slice_platform_identity || return 1
      run_smoke
      return
    fi
    if [[ "${TOPOLOGY:-legacy}" == 'first-party' && "${ROLLBACK_TOPOLOGY:-legacy}" == 'legacy' ]]; then
      local current
      current="$(current_runtime_topology)" || return 1
      if [[ "$current" == 'first-party' ]]; then
        compose stop gateway || return 1
        compose stop api official-api beat || return 1
        drain_current_workers first-party || return 1
      fi
    fi
    # Stop every container in this application project, including new release
    # orphans. Persistent volumes and the separate database project are retained.
    compose down --remove-orphans || return 1
    node "$ROOT_DIR/scripts/prod-app-rollback.mjs" restore-env \
      "$ROOT_DIR" "$ROLLBACK_BUNDLE" "$ROLLBACK_IMAGE" || return 1
    docker tag "$ROLLBACK_IMAGE" "$CURRENT_IMAGE" || return 1
    docker tag "$ROLLBACK_IMAGE" "$ROLLBACK_CURRENT_IMAGE" || return 1
    if [[ "${ROLLBACK_TOPOLOGY:-legacy}" == 'first-party' ]]; then
      docker tag "$ROLLBACK_OFFICIAL_API_IMAGE" "$OFFICIAL_API_REPOSITORY:prod" || return 1
      docker tag "$ROLLBACK_OFFICIAL_WORKER_IMAGE" "$OFFICIAL_WORKER_REPOSITORY:prod" || return 1
    fi
    rollback_compose up -d --remove-orphans --wait --wait-timeout 600 || return 1
    local revision
    revision="$(image_revision "$ROLLBACK_IMAGE")" || return 1
    if [[ "${ROLLBACK_TOPOLOGY:-legacy}" == 'first-party' ]]; then
      (export "$ROLLBACK_REVISION_ENV=$revision" MIY_EXPECTED_OFFICIAL_REVISION="$ROLLBACK_OFFICIAL_REVISION"
        node "$ROLLBACK_BUNDLE/scripts/prod-app-smoke.mjs" "$ROLLBACK_BUNDLE/.env" --topology first-party) || return 1
    else
      (export "$ROLLBACK_REVISION_ENV=$revision"
        node "$ROLLBACK_BUNDLE/scripts/prod-app-smoke.mjs" "$ROLLBACK_BUNDLE/.env") || return 1
      # An older pinned smoke predates split ingress. Check restored locations
      # with its own config owner before claiming public routing was recovered.
      node "$ROOT_DIR/scripts/prod-app-rollback.mjs" smoke-routing "$ROLLBACK_BUNDLE" || return 1
    fi
    return 0
  fi
  if ! docker image inspect "$PREVIOUS_IMAGE" >/dev/null 2>&1; then
    echo "No previous production image is available for automatic restoration." >&2
    return 1
  fi
  echo "Restoring the previous production application image." >&2
  docker tag "$PREVIOUS_IMAGE" "$CURRENT_IMAGE" || return 1
  start_runtime || return 1
  run_smoke || return 1
}

report_deployment_failure() {
  local restore_image="${1:?restoration decision is required}"
  echo "Production application deployment failed." >&2
  if [[ "$restore_image" == "yes" || -n "$ROLLBACK_IMAGE" ]]; then
    if ! restore_previous_runtime; then
      echo "Production application restoration failed; operator recovery is required." >&2
      return 1
    fi
    echo "The previous production application was restored and passed smoke." >&2
  fi
  return 1
}

deploy() {
  local image="${1:?image is required}"
  # Exact verified candidate IDs remain usable if a role-tag operation fails
  # partway through initial split promotion. Recovery does not depend on tags
  # which the failed operation may not yet have created.
  local COMPOSE_OFFICIAL_API_IMAGE="${OFFICIAL_API_IMAGE:-}"
  local COMPOSE_OFFICIAL_WORKER_IMAGE="${OFFICIAL_WORKER_IMAGE:-}"
  if [[ "${TOPOLOGY:-legacy}" == 'first-party' ]]; then
    local current platform_image
    current="$(current_runtime_topology)" || return 1
    if [[ "$RELEASE_SLICE" == 'official' ]]; then
      require_official_slice || return 1
    else
      # Check all existing writer image/Compose identities before changing tags.
      if [[ "$current" != 'none' ]]; then
        platform_image="$(image_id "$CURRENT_IMAGE")" || return 1
        TOPOLOGY="$current" capture_prior_runtime "$platform_image" || return 1
      fi
      [[ "$ROLLBACK_TOPOLOGY" == "$current" ]] || return 1
    fi
    promote_image "$OFFICIAL_API_IMAGE" "$OFFICIAL_API_REPOSITORY:prod" "$OFFICIAL_API_REPOSITORY:prod-previous" \
      && promote_image "$OFFICIAL_WORKER_IMAGE" "$OFFICIAL_WORKER_REPOSITORY:prod" "$OFFICIAL_WORKER_REPOSITORY:prod-previous" || {
        report_deployment_failure yes; return 1;
      }
    if [[ "$RELEASE_SLICE" == 'official' ]]; then
      if ! compose stop official-api official-worker \
        || ! compose up -d --no-deps --force-recreate --wait --wait-timeout 600 official-api official-worker \
        || ! slice_platform_identity \
        || ! run_smoke; then report_deployment_failure yes; return 1; fi
      echo 'Official bundle deployment completed; platform, Beat and gateway container identities were retained.'
      return
    fi
  fi
  if ! promote_image "$image"; then
    report_deployment_failure yes
    return 1
  fi
  if ! start_forward_runtime; then
    report_deployment_failure yes
    return 1
  fi
  echo "Production application deployment completed and passed public smoke."
  if ! node "$ROOT_DIR/scripts/docker-storage.mjs" cleanup --apply; then
    echo "Deployment is healthy, but project image retention needs operator attention." >&2
    return 1
  fi
}

COMMAND="${1:-}"
if [[ -z "$COMMAND" ]]; then
  usage
  exit 2
fi

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-mr)
      if [[ $# -lt 2 || -n "$RELEASE_MR" || -z "$2" ]]; then usage; exit 2; fi
      RELEASE_MR="$2"
      shift 2
      ;;
    --image)
      if [[ $# -lt 2 || -n "$DEPLOY_IMAGE" || -z "$2" ]]; then usage; exit 2; fi
      DEPLOY_IMAGE="$2"
      shift 2
      ;;
    --topology)
      if [[ $# -lt 2 || "$TOPOLOGY" != 'legacy' || "$2" != 'first-party' ]]; then usage; exit 2; fi
      TOPOLOGY="$2"; shift 2 ;;
    --slice)
      if [[ $# -lt 2 || "$RELEASE_SLICE" != 'full' || "$2" != 'official' ]]; then usage; exit 2; fi
      RELEASE_SLICE="$2"; shift 2 ;;
    --official-api-image|--official-worker-image|--rollback-official-api-image|--rollback-official-worker-image)
      if [[ $# -lt 2 || ! "$2" =~ ^sha256:[a-f0-9]{64}$ ]]; then usage; exit 2; fi
      case "$1" in
        --official-api-image) [[ -z "$OFFICIAL_API_IMAGE" ]] || exit 2; OFFICIAL_API_IMAGE="$2" ;;
        --official-worker-image) [[ -z "$OFFICIAL_WORKER_IMAGE" ]] || exit 2; OFFICIAL_WORKER_IMAGE="$2" ;;
        --rollback-official-api-image) [[ -z "$ROLLBACK_OFFICIAL_API_IMAGE" ]] || exit 2; ROLLBACK_OFFICIAL_API_IMAGE="$2" ;;
        --rollback-official-worker-image) [[ -z "$ROLLBACK_OFFICIAL_WORKER_IMAGE" ]] || exit 2; ROLLBACK_OFFICIAL_WORKER_IMAGE="$2" ;;
      esac
      shift 2 ;;
    --rollback-topology)
      if [[ $# -lt 2 || "$ROLLBACK_TOPOLOGY" != 'legacy' || "$2" != 'first-party' ]]; then usage; exit 2; fi
      ROLLBACK_TOPOLOGY="$2"; shift 2 ;;
    --rollback-env-file)
      if [[ $# -lt 2 || -n "$ROLLBACK_ENV_FILE" || -z "$2" ]]; then usage; exit 2; fi
      ROLLBACK_ENV_FILE="$2"
      shift 2
      ;;
    --rollback-image)
      if [[ $# -lt 2 || -n "$ROLLBACK_IMAGE" || -z "$2" ]]; then usage; exit 2; fi
      ROLLBACK_IMAGE="$2"
      shift 2
      ;;
    *) usage; exit 2 ;;
  esac
done
if [[ "$COMMAND" == "prepare" ]]; then
  if [[ -z "$RELEASE_MR" || -n "$DEPLOY_IMAGE" || -n "$ROLLBACK_ENV_FILE" || -n "$ROLLBACK_IMAGE" ]]; then
    usage
    exit 2
  fi
elif [[ "$COMMAND" == "deploy" ]]; then
  if [[ -z "$RELEASE_MR" || ( "$RELEASE_SLICE" == 'full' && -z "$DEPLOY_IMAGE" ) || ( "$RELEASE_SLICE" == 'official' && -n "$DEPLOY_IMAGE" ) ]]; then
    usage
    exit 2
  fi
elif [[ -n "$RELEASE_MR" || -n "$DEPLOY_IMAGE" ]]; then
  usage
  exit 2
fi
if [[ "$TOPOLOGY" == 'legacy' ]]; then
  if [[ "$RELEASE_SLICE" != 'full' || -n "$OFFICIAL_API_IMAGE$OFFICIAL_WORKER_IMAGE$ROLLBACK_OFFICIAL_API_IMAGE$ROLLBACK_OFFICIAL_WORKER_IMAGE" || "$ROLLBACK_TOPOLOGY" != 'legacy' ]]; then usage; exit 2; fi
else
  if [[ "$COMMAND" == 'deploy' ]]; then
    if [[ -z "$OFFICIAL_API_IMAGE" || -z "$OFFICIAL_WORKER_IMAGE" || -z "$ROLLBACK_IMAGE" ]]; then usage; exit 2; fi
  elif [[ -n "$OFFICIAL_API_IMAGE$OFFICIAL_WORKER_IMAGE" ]]; then usage; exit 2; fi
  if [[ "$COMMAND" == 'rollback' && -z "$ROLLBACK_IMAGE" ]]; then usage; exit 2; fi
  if [[ "$ROLLBACK_TOPOLOGY" == 'first-party' ]]; then
    if [[ -z "$ROLLBACK_OFFICIAL_API_IMAGE" || -z "$ROLLBACK_OFFICIAL_WORKER_IMAGE" || -z "$ROLLBACK_IMAGE" ]]; then usage; exit 2; fi
  elif [[ -n "$ROLLBACK_OFFICIAL_API_IMAGE$ROLLBACK_OFFICIAL_WORKER_IMAGE" ]]; then usage; exit 2; fi
  if [[ "$RELEASE_SLICE" == 'official' && "$COMMAND" != 'prepare' && "$COMMAND" != 'deploy' && "$COMMAND" != 'rollback' ]]; then usage; exit 2; fi
fi
if [[ -n "$ROLLBACK_ENV_FILE" || -n "$ROLLBACK_IMAGE" ]]; then
  if [[ -z "$ROLLBACK_ENV_FILE" || -z "$ROLLBACK_IMAGE" || ( "$COMMAND" != "deploy" && "$COMMAND" != "rollback" ) ]]; then
    usage
    exit 2
  fi
fi

case "$COMMAND" in
  prepare)
    require_prod_checkout
    require_release_source
    acquire_operation_lock
    validate_environment
    load_release_contract "$RELEASE_MR"
    if [[ "$TOPOLOGY" == 'first-party' ]]; then
      if [[ "$RELEASE_SLICE" == 'full' ]]; then
        PREPARED_PLATFORM_IMAGE="$(prepare_candidate_image)"
        printf 'platform=%s\n' "$PREPARED_PLATFORM_IMAGE"
      else
        [[ "$(current_runtime_topology)" == 'first-party' ]] || exit 1
        PREPARED_PLATFORM_IMAGE="$(image_id "$CURRENT_IMAGE")"
        prior_revision="$(image_revision "$OFFICIAL_API_REPOSITORY:prod")"
        python3 "$ROOT_DIR/scripts/prod-app-official-slice.py" "$ROOT_DIR" "$prior_revision"
      fi
      prepared_api="$(prepare_candidate_image official-api)"
      require_official_web_compatibility "$PREPARED_PLATFORM_IMAGE" "$prepared_api"
      if [[ "$RELEASE_SLICE" == 'official' ]]; then
        require_official_gateway_compatibility "$PREPARED_PLATFORM_IMAGE" "$prepared_api"
      fi
      prepared_worker="$(prepare_candidate_image official-worker)"
      printf 'official-api=%s\nofficial-worker=%s\n' "$prepared_api" "$prepared_worker"
    else
      prepare_candidate_image
    fi
    ;;
  deploy)
    require_prod_checkout
    require_release_source
    acquire_operation_lock
    prepare_rollback_runtime "$CURRENT_IMAGE"
    validate_environment
    require_terminal_broker_port_available
    load_release_contract "$RELEASE_MR"
    if [[ "$TOPOLOGY" == 'first-party' ]]; then
      require_deploy_image "$OFFICIAL_API_IMAGE" official-api
      require_deploy_image "$OFFICIAL_WORKER_IMAGE" official-worker
      if [[ "$RELEASE_SLICE" == 'full' ]]; then
        require_deploy_image "$DEPLOY_IMAGE"
        require_official_web_compatibility "$DEPLOY_IMAGE" "$OFFICIAL_API_IMAGE"
      fi
    else
      require_deploy_image "$DEPLOY_IMAGE"
    fi
    deploy "${DEPLOY_IMAGE:-$CURRENT_IMAGE}"
    ;;
  migrate)
    require_prod_checkout
    require_release_source
    validate_environment
    run_migrations
    ;;
  rollback)
    require_prod_checkout
    require_release_source
    acquire_operation_lock
    if [[ -n "$ROLLBACK_IMAGE" ]]; then
      if [[ "$RELEASE_SLICE" == 'official' ]]; then prepare_rollback_runtime "$CURRENT_IMAGE";
      else prepare_rollback_runtime "$PREVIOUS_IMAGE"; fi
    else
      validate_environment
      require_terminal_broker_port_available
    fi
    restore_previous_runtime
    ;;
  smoke)
    require_prod_checkout
    validate_environment
    run_smoke
    ;;
  status)
    require_prod_checkout
    compose ps
    ;;
  up)
    require_prod_checkout
    require_release_source
    acquire_operation_lock
    validate_environment
    require_terminal_broker_port_available
    docker image inspect "$CURRENT_IMAGE" >/dev/null
    up_image="$(image_id "$CURRENT_IMAGE")"
    if ! capture_prior_runtime "$up_image"; then
      echo "Existing runtime does not match the current image/prior container identities; refusing before stop." >&2
      exit 1
    fi
    verify_files_gate_executable "$up_image"
    if ! start_forward_runtime; then
      echo "Forward startup failed; restoring the pre-up image." >&2
      if ! restore_same_runtime "$up_image"; then
        echo "Pre-up runtime restoration failed; operator recovery is required." >&2
      fi
      exit 1
    fi
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
