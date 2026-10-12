"""Generate the request contracts we use from the pinned official Codex binary."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from codex_console.protocol_contract import (
    build_history_contract,
    render_contract,
    supports_contract_version,
)

VERSION = "0.162.1"
TARGET = Path(__file__).resolve().parents[1] / "src/codex_console/protocol.json"
HISTORY_TARGET = TARGET.with_name("history_protocol.generated.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    version = subprocess.check_output(["codex", "--version"], text=True).strip()
    if args.check:
        if not supports_contract_version(version, VERSION):
            raise SystemExit(f"Expected a stable codex-cli {VERSION} or newer")
    elif version != f"codex-cli {VERSION}":
        raise SystemExit(f"Regeneration requires codex-cli {VERSION}")
    with tempfile.TemporaryDirectory(prefix="codex-console-schema-") as directory:
        subprocess.run(
            ["codex", "app-server", "generate-json-schema", "--experimental", "--out", directory],
            check=True,
        )
        generated = render_contract(VERSION, Path(directory))
        history = json.dumps(
            build_history_contract(VERSION, Path(directory)),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != generated:
            raise SystemExit("Codex protocol contract drift")
        if not HISTORY_TARGET.exists() or HISTORY_TARGET.read_text() != history:
            raise SystemExit("Codex history protocol contract drift")
    else:
        TARGET.write_text(generated)
        HISTORY_TARGET.write_text(history)


if __name__ == "__main__":
    main()
