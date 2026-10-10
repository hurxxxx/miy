"""Offline inspection of matching installed wheel imports, with no consumer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def inspect_profile(profile: str, wheels: list[Path]) -> dict:
    def audit(event, args):
        if (
            event == "open"
            and isinstance(args[0], (str, bytes))
            and Path(os.fsdecode(args[0])).name.startswith(".env")
        ):
            raise RuntimeError("environment_file_read_forbidden")
        if event in {"socket.connect", "socket.bind"}:
            raise RuntimeError("network_forbidden")

    sys.addaudithook(audit)
    # Resolve only the supplied wheels, never this checkout's API fallback.
    sys.path[:0] = [str(wheel) for wheel in wheels]
    import importlib
    import importlib.metadata
    import importlib.util

    roots = tuple(str(wheel) + os.sep for wheel in wheels)
    versions = {
        importlib.metadata.version(name)
        for name in ("miy-api", "miy-worker", "miy-official-worker")
    }
    assert len(versions) == 1, "matching_runtime_wheels_required"
    for entry in (
        "miy_worker.first_party_platform",
        "miy_worker.first_party_beat",
        "miy_official_worker.runtime",
    ):
        specification = importlib.util.find_spec(entry)
        assert specification is not None and specification.origin
        assert specification.origin.startswith(roots), ("missing_runtime_entry", entry)

    import miy_api.platform_extensions as extensions
    from miy_worker import runtime, settings

    def unavailable(*_args, **_kwargs):
        raise AssertionError("runtime_initialization_forbidden")

    runtime.configure_database = unavailable
    runtime.postgres_engine = unavailable
    settings.get_settings = unavailable
    extensions.initialize_platform_extensions = unavailable
    from miy_api.core.worker_queue_contract import (
        WorkerProfileUnavailable,
        worker_profile_modules,
        worker_profile_queues,
        worker_profile_task_names,
        worker_profile_task_routes,
    )

    entry = (
        "miy_official_worker.celery_app"
        if profile == "official"
        else "miy_worker.platform_app"
    )
    app = importlib.import_module(entry).celery_app
    own_tasks = set(worker_profile_task_names(profile))
    assert {name for name in app.tasks if not name.startswith("celery.")} == own_tasks
    assert app.conf.task_routes == worker_profile_task_routes(profile)
    assert set(app.amqp.queues) == set(worker_profile_queues(profile))
    assert "miy_worker.celery_app" not in sys.modules
    other = "platform" if profile == "official" else "official"
    assert not set(worker_profile_modules(other)).intersection(sys.modules)
    if profile == "official":
        official_wheel = next(
            wheel for wheel in wheels if wheel.name.startswith("miy_official_worker-")
        )
        for name in worker_profile_modules("official"):
            owner = name.replace("miy_worker.tasks.", "miy_official_worker.tasks.")
            assert sys.modules[name] is sys.modules[owner], ("task_alias_identity", name)
            assert sys.modules[owner].__file__.startswith(str(official_wheel) + os.sep), (
                "business_task_not_in_owner_wheel",
                name,
            )
    task = app.tasks[min(own_tasks)]
    for invoke in (
        lambda: app.Worker(queues="celery"),
        lambda: app.Beat(),
        lambda: app.send_task(task.name),
        lambda: app.connection_for_write(),
        lambda: task.run("fixture"),
        lambda: task.apply(args=["fixture"], throw=True),
    ):
        try:
            invoke()
        except WorkerProfileUnavailable:
            pass
        else:
            raise AssertionError("inactive_profile_executed")
    imports = {}
    for name, module in sys.modules.items():
        if name in {"miy_api", "miy_worker", "miy_official_worker"} or name.startswith(
            ("miy_api.", "miy_worker.", "miy_official_worker.")
        ):
            path = getattr(module, "__file__", None)
            if path:
                assert path.startswith(roots), ("source_checkout_import", name)
                imports[name] = path
    app.close()
    return {
        "profile": profile,
        "activation": "inactive",
        "task_count": len(own_tasks),
        "beat_count": len(app.conf.beat_schedule),
        "queues": list(worker_profile_queues(profile)),
        "wheel_module_count": len(imports),
        "runtime_initialized": False,
        "network": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel_dir", type=Path)
    parser.add_argument("--profile", choices=("platform", "official"))
    args = parser.parse_args()
    root = args.wheel_dir.resolve(strict=True)
    wheels = []
    for prefix in ("miy_api-", "miy_worker-", "miy_official_worker-"):
        matches = list(root.glob(prefix + "*.whl"))
        if len(matches) != 1 or matches[0].is_symlink():
            raise RuntimeError("exact_matching_wheels_required")
        wheels.append(matches[0])
    hashes = {}
    for wheel in wheels:
        hashes[wheel.name] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if (
                    name.startswith("/")
                    or ".." in Path(name).parts
                    or Path(name).name.startswith(".env")
                ):
                    raise RuntimeError("unexpected_wheel_path")
    if args.profile:
        print(json.dumps(inspect_profile(args.profile, wheels), sort_keys=True))
        return
    results = []
    for profile in ("platform", "official"):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key != "PYTHONPATH" and not key.startswith("MIY_")
        }
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(root),
                "--profile",
                profile,
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"profile_verification_failed:{profile}\n{result.stderr}"
            )
        results.append(json.loads(result.stdout))
    print(json.dumps({"wheels": hashes, "profiles": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
