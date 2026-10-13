"""Generate or check contracts from the selected stable official Codex CLI."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from codex_console.protocol_contract import (
    build_contract,
    build_history_contract,
    history_schemas_are_compatible,
    schemas_are_compatible,
    supports_contract_version,
)

MINIMUM_VERSION = "0.162.1"
TARGET = Path(__file__).resolve().parents[1] / "src/codex_console/protocol.json"
HISTORY_TARGET = TARGET.with_name("history_protocol.generated.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binary", default=os.environ.get("MIY_CODEX_CONSOLE_BINARY", "codex"))
    args = parser.parse_args()
    version = subprocess.check_output([args.binary, "--version"], text=True).strip()
    if not supports_contract_version(version, MINIMUM_VERSION):
        raise SystemExit(f"Expected a stable codex-cli {MINIMUM_VERSION} or newer")
    selected_version = version.removeprefix("codex-cli ")
    with tempfile.TemporaryDirectory(prefix="codex-console-schema-") as directory:
        subprocess.run(
            [
                args.binary,
                "app-server",
                "generate-json-schema",
                "--experimental",
                "--out",
                directory,
            ],
            check=True,
        )
        if args.check:
            if not TARGET.exists() or not HISTORY_TARGET.exists():
                raise SystemExit("Codex generated contracts are missing")
            core = json.loads(TARGET.read_text())
            history = json.loads(HISTORY_TARGET.read_text())
            if (
                not supports_contract_version(version, core["codexVersion"])
                or not schemas_are_compatible(core, Path(directory))
                or not history_schemas_are_compatible(history, Path(directory))
            ):
                raise SystemExit(
                    "Codex RPC contract changed; review the adapter before regeneration"
                )
            print("Selected stable Codex CLI is compatible")
            return
        contracts = {
            TARGET: build_contract(
                selected_version, Path(directory), include_compatibility_schemas=True
            ),
            HISTORY_TARGET: build_history_contract(selected_version, Path(directory)),
        }
    for target, contract in contracts.items():
        target.write_text(json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
