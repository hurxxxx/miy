"""Prepared Core Recording publication operations; no broker/service activation."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "poll-once", help="Prepare at most 20 Core bindings; does not send"
    )
    for name in ("status", "reconcile-one"):
        commands.add_parser(name).add_argument("publication_id", type=UUID)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from the platform checkout")
    from miy_api.core.db import get_session_factory
    from miy_api.core.model_registry import import_all_models
    from miy_api.domains.official_apps.recording_publication_models import (
        CoreRecordingPublication,
    )
    from miy_api.domains.official_apps.recording_publications import (
        poll_once,
        reconcile_publication,
    )
    from miy_api.domains.recording.pipeline_contracts import RecordingCommandError

    import_all_models()
    try:
        with get_session_factory()() as db:
            if args.command == "poll-once":
                result = {"prepared": poll_once(db), "publication_enabled": False}
            elif args.command == "reconcile-one":
                result = {
                    "publication_id": str(args.publication_id),
                    "state": reconcile_publication(db, str(args.publication_id)),
                }
            else:
                row = db.get(CoreRecordingPublication, str(args.publication_id))
                if row is None:
                    raise RecordingCommandError("recording_publication_missing")
                result = {
                    "publication_id": row.publication_id,
                    "command_id": row.command_id,
                    "state": row.state,
                    "task_id": row.task_id,
                }
        print(json.dumps(result))
    except RecordingCommandError as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(1) from None
    except Exception:  # noqa: BLE001 - never print driver credentials or SQL
        print(json.dumps({"error": "recording_publication_unavailable"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
