#!/usr/bin/env python3
"""Validate a confined, operator-provisioned executor before emitting settings.

Run with the Workbench API environment. The output file is private and contains
the capability token; stdout contains only bounded, synthetic probe outcomes.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/codex-console-api/src"))


def main():
    from codex_console.config import AppExecutionEnvironment
    from codex_console.executor_probe import ProbeFailure, prepare, secret_file

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--exec-server-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.token_file.resolve().is_relative_to(args.source_root.resolve()):
            raise ProbeFailure("executor_token_file_denied")
        environment = AppExecutionEnvironment(
            key=args.key,
            source_root=args.source_root,
            exec_server_url=args.exec_server_url,
            auth_bearer_token=secret_file(args.token_file),
        )
        result = asyncio.run(prepare(environment, args.output))
    except ProbeFailure as error:
        parser.exit(1, str(error) + ": no configuration emitted.\n")
    except Exception:
        parser.exit(1, "Executor verification failed: no configuration emitted.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
