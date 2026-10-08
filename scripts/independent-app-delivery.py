"""Core-operator CLI for local app builds and durable development deployment intents.

Run from the platform checkout. Never install this CLI or platform credentials in
an app workspace, and never expose it as an unrestricted coding-agent command.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def run(args) -> dict:
    from miy_api.core.db import get_session_factory
    from miy_api.core.model_registry import import_all_models
    from miy_api.core.settings import get_settings
    from miy_api.domains.auth.models import utcnow_naive
    from miy_api.domains.independent_apps.builds import BuildFailure, build_app
    from miy_api.domains.independent_apps.data_store import configured_store
    from miy_api.domains.independent_apps.delegation import build_out
    from miy_api.domains.independent_apps.delivery import (
        deployment_out,
        execute_deployment,
        persist_verified_build,
        reconcile_deployment,
        start_build_job,
    )
    from miy_api.domains.independent_apps.delivery_models import (
        AppBuildJob,
        AppDeploymentRequest,
    )
    from miy_api.domains.independent_apps.local_runtime import DockerRuntime
    from miy_api.domains.independent_apps.models import (
        AppDefinitionRecord,
        AppInstallationRecord,
        AppReleaseRecord,
    )

    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run the core operator CLI from the platform checkout")
    import_all_models()
    if args.command == "poll-once":
        from miy_api.domains.independent_apps.executor import poll_once

        return poll_once(get_settings(), get_session_factory(), safe_run)
    with get_session_factory()() as db:
        if args.command in {"build", "build-request"}:
            if args.command == "build-request":
                intent = db.get(AppBuildJob, str(UUID(args.build_id)))
                if (
                    intent is None
                    or intent.delegation_id is None
                    or (intent.app_id, intent.installation_id)
                    != (args.app_id, str(UUID(args.installation_id)))
                ):
                    raise ValueError("The requested build does not match the operator binding")
                args.revision = intent.source_revision
            job, claimed = start_build_job(db, args.app_id, args.revision, str(UUID(args.build_id)))
            if claimed:
                # Hold the job fence until completion; durable running state remains
                # after process loss. Another invocation returns status, never reruns.
                job = db.scalar(
                    select(AppBuildJob).where(AppBuildJob.id == job.id).with_for_update()
                )
                definition = db.get(AppDefinitionRecord, args.app_id)
                try:
                    evidence = build_app(
                        source=args.source,
                        revision=args.revision,
                        expected_definition=definition.manifest,
                        toolchain_image=args.toolchain_image,
                        work_root=args.work_root,
                        build_id=job.id,
                    )
                    persist_verified_build(db, job, evidence)
                except BuildFailure as exc:
                    db.rollback()
                    job = db.get(AppBuildJob, job.id)
                    job.failure_code = str(exc)
                    job.state = "unknown" if str(exc) == "build_cleanup_required" else "failed"
                    job.active_slot = 1 if job.state == "unknown" else None
                    job.updated_at = utcnow_naive()
                    db.commit()
                except HTTPException:
                    db.rollback()
                    job = db.get(AppBuildJob, job.id)
                    job.state, job.failure_code, job.active_slot = (
                        "failed",
                        "authority_changed",
                        None,
                    )
                    job.updated_at = utcnow_naive()
                    db.commit()
                except Exception:  # noqa: BLE001 - uncertain side effects must retain the durable slot
                    db.rollback()
                    job = db.get(AppBuildJob, job.id)
                    job.state, job.failure_code = (
                        "unknown",
                        "build_reconciliation_required",
                    )
                    db.commit()
            return build_out(job).model_dump(mode="json")
        request = db.get(AppDeploymentRequest, str(UUID(args.request_id)))
        installation = db.get(AppInstallationRecord, request.installation_id) if request else None
        if (
            installation is None
            or installation.app_id != args.app_id
            or installation.id != str(UUID(args.installation_id))
        ):
            raise ValueError("The requested deployment does not match the operator binding")
        if args.command == "status":
            return deployment_out(request).model_dump(mode="json")
        settings = get_settings()
        if args.platform_origin not in settings.independent_app_platform_origins:
            raise ValueError("Platform origin must be configured in the platform's typed allowlist")
        runtime = DockerRuntime(
            state_root=args.state_root,
            ingress_image=args.ingress_image,
            platform_origin=args.platform_origin,
            platform_api_origin=args.platform_api_origin,
            data_store=(
                configured_store(settings)
                if db.get(AppReleaseRecord, request.release_id).definition_snapshot[
                    "runtime_profile"
                ]
                == "web-api-postgres-v1"
                else None
            ),
        )
        operation = execute_deployment if args.command == "execute" else reconcile_deployment
        return operation(db, request.id, runtime).model_dump(mode="json")


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "poll-once", help="Consume or reconcile one existing intent in the core allowlist"
    )
    worker = commands.add_parser(
        "serve", help="Opt-in foreground consumer; never installs a service"
    )
    worker.add_argument("--poll-seconds", type=float, default=5)
    for name in ("build", "build-request"):
        build = commands.add_parser(
            name, help="Consume an exact registered commit with the trusted offline profile"
        )
        for option in ("app-id", "build-id", "toolchain-image"):
            build.add_argument("--" + option, required=True)
        build.add_argument("--revision" if name == "build" else "--installation-id", required=True)
        build.add_argument("--source", required=True, type=Path)
        build.add_argument("--work-root", required=True, type=Path)
    for name in ("status", "execute", "reconcile"):
        command = commands.add_parser(name)
        for option in ("app-id", "installation-id", "request-id"):
            command.add_argument("--" + option, required=True)
        if name != "status":
            command.add_argument("--state-root", required=True, type=Path)
            command.add_argument("--ingress-image", required=True)
            command.add_argument("--platform-origin", required=True)
            command.add_argument("--platform-api-origin")
    return parser


def safe_run(args) -> dict:
    try:
        return run(args)
    except HTTPException as exc:
        return {"state": "rejected", "http_status": exc.status_code}
    except Exception:  # noqa: BLE001 - operator boundary must not leak credentials/daemon output
        # Never print operator credentials, app output or daemon diagnostics.
        return {"state": "unknown", "failure_code": "operator_check_required"}


def main() -> int:
    args = parser().parse_args()
    if args.command != "serve":
        result = safe_run(args)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] in {"succeeded", "idle"} else 2
    from miy_api.domains.independent_apps.executor import serve
    from miy_api.core.settings import get_settings

    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if (
            Path.cwd().resolve() != ROOT
            or not 1 <= args.poll_seconds <= 60
            or not get_settings().independent_app_delivery_targets
        ):
            raise ValueError("The consumer requires valid core settings and checkout")
        serve(
            lambda: safe_run(argparse.Namespace(command="poll-once")),
            stop=stop,
            emit=lambda result: print(json.dumps(result, sort_keys=True), flush=True),
            poll_seconds=args.poll_seconds,
        )
        return 0
    except Exception:  # noqa: BLE001 - bounded operator error, never configuration values
        print(json.dumps({"state": "rejected", "failure_code": "consumer_configuration_required"}))
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
