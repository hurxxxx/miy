#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_DIR="${1:?Usage: bash scripts/build-codex-console.sh /absolute/new/release-directory [python-executable]}"
PYTHON_BIN="${2:-python3}"
if [[ "$RELEASE_DIR" != /* || -e "$RELEASE_DIR" ]]; then
  echo 'Choose an absolute, new release directory. Existing releases are never overwritten.' >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sqlite3
import sys

assert sys.version_info[:2] == (3, 12), 'Use Python 3.12'
v = sqlite3.sqlite_version_info
assert v >= (3, 51, 3) or (3, 50, 7) <= v < (3, 51, 0) or (3, 44, 6) <= v < (3, 45, 0), 'Use SQLite with the WAL-reset fix (3.51.3+ recommended)'
PY

pnpm --dir "$ROOT_DIR/apps/codex-console-web" build
mkdir -p "$RELEASE_DIR/apps/codex-console-api" "$RELEASE_DIR/apps/codex-console-web"
cp -a "$ROOT_DIR/apps/codex-console-web/dist" "$RELEASE_DIR/apps/codex-console-web/"
tar -C "$ROOT_DIR/apps/codex-console-api" --exclude=__pycache__ -cf - \
  src migrations sqlite_migrations pyproject.toml uv.lock alembic.ini \
  | tar -C "$RELEASE_DIR/apps/codex-console-api" -xf -
"$PYTHON_BIN" - "$ROOT_DIR" "$RELEASE_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

source, release = map(Path, sys.argv[1:])
revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
dirty = bool(subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']))
identity = release / 'apps/codex-console-api/src/codex_console/_build.json'
digest = hashlib.sha256()
for path in sorted(release.rglob('*')):
    if path.is_file() and path != identity:
        digest.update(str(path.relative_to(release)).encode() + b'\0')
        digest.update(path.read_bytes())
identity.write_text(json.dumps({'source_revision': revision, 'source_dirty': dirty, 'digest': 'sha256:' + digest.hexdigest()}) + '\n')
PY
uv sync --frozen --no-dev --directory "$RELEASE_DIR/apps/codex-console-api" --python "$PYTHON_BIN"
echo 'Release built. Configure the dedicated database and origin before starting the service.'
