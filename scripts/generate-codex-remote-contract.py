#!/usr/bin/env python3
"""Generate the core and supplemental contracts for the pinned native controller."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="codex")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = root / "apps/codex-console-api/src/codex_console"
    loader = importlib.util.spec_from_file_location(
        "remote_contract", package / "protocol_contract.py"
    )
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    version = "0.160.1"
    try:
        observed = subprocess.run(
            [arguments.binary, "--version"], capture_output=True, timeout=10, check=True
        )
        if observed.stdout.decode().strip() != "codex-cli " + version:
            raise ValueError("Select the tested native executor version")
        with tempfile.TemporaryDirectory(prefix="miy-remote-contract-") as directory:
            subprocess.run(
                [
                    arguments.binary,
                    "app-server",
                    "generate-json-schema",
                    "--experimental",
                    "--out",
                    directory,
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
            contracts = {
                "remote_protocol.generated.json": module.build_remote_contract(
                    version, Path(directory)
                ),
                "remote_core_protocol.generated.json": module.build_contract(version, Path(directory)),
            }
        for filename, contract in contracts.items():
            rendered = json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            target = package / filename
            if arguments.check:
                if not target.exists() or target.read_text() != rendered:
                    raise ValueError("Remote protocol contract requires regeneration")
            else:
                target.write_text(rendered)
    except (OSError, subprocess.SubprocessError, ValueError):
        parser.exit(
            1, "Native executor contract generation/check failed. Use the pinned 0.160.1 binary.\n"
        )
    print("Native controller core and supplemental contracts match 0.160.1.")


if __name__ == "__main__":
    main()
