#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/dev-env.sh"
unset OPENROUTER_API_KEY

COMPOSITION=legacy
case "${1:-}" in
  --first-party)
    COMPOSITION=platform
    shift
    ;;
  --official)
    COMPOSITION=official
    shift
    ;;
esac

SELECTED_TOPOLOGY="$(python3 "$ROOT_DIR/scripts/dev-topology.py" --read)"
if [[ "$COMPOSITION" == "legacy" && "$SELECTED_TOPOLOGY" == "first-party" ]] ||
   [[ "$COMPOSITION" != "legacy" && "$SELECTED_TOPOLOGY" != "first-party" ]]; then
  echo "Standalone API namespace change HOLD; use dev.sh --restart and native consumer drain." >&2
  exit 1
fi

TARGET="${1:?instance index or port is required}"

if [[ "$TARGET" =~ ^[0-9]+$ ]] && (( TARGET >= 8000 )); then
  PORT="$TARGET"
  INSTANCE_INDEX="$((PORT - 8000))"
else
  INSTANCE_INDEX="$TARGET"
  PORT="$(dev_api_port "$INSTANCE_INDEX")"
fi

INSTANCE_ID="${2:-$(dev_api_name "$INSTANCE_INDEX")}"

export MIY_API_INSTANCE_ID="$INSTANCE_ID"

if [[ "$COMPOSITION" == "official" ]]; then
  if [[ "$PORT" != "18781" ]]; then
    echo "The official development API uses port 18781; production owns 18780." >&2
    exit 1
  fi
  export MIY_API_AUTO_MIGRATE=0
  export MIY_API_SEED_DEV_LOGIN_ACCOUNT=0
elif [[ "${MIY_API_AUTO_MIGRATE:-}" == "" ]]; then
  if [[ "$PORT" == "8001" ]]; then
    export MIY_API_AUTO_MIGRATE=1
  else
    export MIY_API_AUTO_MIGRATE=0
  fi
fi

cd "$ROOT_DIR/apps/api"
case "$COMPOSITION" in
  legacy) ENTRY=miy_api.main:app; APP_DIR=src ;;
  platform) ENTRY=miy_api.platform_runtime:app; APP_DIR=src ;;
  official) ENTRY=miy_official_api.development:app; APP_DIR=../official-suite/api/src ;;
esac
exec "$ROOT_DIR/apps/api/.venv/bin/python" -m uvicorn "$ENTRY" --app-dir "$APP_DIR" --host "$MIY_DEV_API_HOST" --port "$PORT"
