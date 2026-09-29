#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATUS=0

run_segment() {
  local name="${1:?segment name is required}"
  shift

  printf '[api-test-full] start %s\n' "$name" >&2
  if (cd "$ROOT_DIR/apps/api" && "$@"); then
    printf '[api-test-full] pass %s\n' "$name" >&2
  else
    local segment_status=$?
    printf '[api-test-full] fail %s status=%s\n' "$name" "$segment_status" >&2
    STATUS=1
  fi
}

default_external_integration_env() {
  export MTY_TEST_REDIS_URL="${MTY_TEST_REDIS_URL:-${MTY_API_COLLAB_REDIS_URL:-}}"
  export MTY_TEST_MINIO_ENDPOINT="${MTY_TEST_MINIO_ENDPOINT:-${MTY_MINIO_ENDPOINT:-}}"
  export MTY_TEST_MINIO_ACCESS_KEY="${MTY_TEST_MINIO_ACCESS_KEY:-${MTY_MINIO_ACCESS_KEY:-}}"
  export MTY_TEST_MINIO_SECRET_KEY="${MTY_TEST_MINIO_SECRET_KEY:-${MTY_MINIO_SECRET_KEY:-}}"
  export MTY_TEST_OPENSEARCH_URL="${MTY_TEST_OPENSEARCH_URL:-${MTY_OPENSEARCH_URL:-}}"
}

run_segment \
  fast \
  uv run --python 3.12 --group dev python -m pytest \
  -n "${MTY_API_PYTEST_WORKERS:-8}" \
  --dist=worksteal \
  -m "not slow and not external_integration and not migration"

run_segment \
  slow \
  uv run --python 3.12 --group dev python -m pytest \
  -m "slow and not external_integration and not migration"

run_segment \
  migration \
  uv run --python 3.12 --group dev python -m pytest \
  -m migration

default_external_integration_env
run_segment \
  external_integration \
  bash "$ROOT_DIR/scripts/api-test-vm.sh" -m external_integration

exit "$STATUS"
