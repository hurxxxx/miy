"""Installed Core entrypoint: validate changed app subtrees in the offline builder.

The runner calls this file from a trusted installation, never from the MR checkout.
No manifest command, package manager, Vite config or app test executes on the host.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE_ROOT / "apps/api/src"))

from miy_api.domains.independent_apps import builds
from miy_api.domains.independent_apps.contracts import AppDefinition

_SHA = re.compile(r"^[a-f0-9]{40}$")
_APP_PATH = re.compile(r"^personal-apps/([a-z][a-z0-9-]{1,63})/")


def executor_for_source(config, source, environment):
    # This sibling belongs to the same protected Core installation, not the MR.
    spec = importlib.util.spec_from_file_location(
        "miy_personal_app_fixed_runner",
        Path(__file__).with_name("personal-app-runner.py"),
    )
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)
    owned = runner.Config(
        config["project_id"],
        config["repository"],
        config["toolchain_image"],
        Path(config["work_root"]),
    )
    job = runner.job_from_environment(
        owned, {"CUSTOM_ENV_" + key: value for key, value in environment.items()}
    )
    executor = runner.Executor(owned, job)
    if source != executor.source:
        raise ValueError("Exact runner checkout required")
    receipt = executor.read()
    if receipt["state"] != "validating" or receipt.get("verification") is None:
        raise ValueError("Runner validation intent required")
    return executor


def validate(
    source,
    *,
    revision,
    base,
    repository,
    image,
    work_root,
    build=builds.build_app,
    record_artifact=None,
):
    if not _SHA.fullmatch(revision) or not _SHA.fullmatch(base):
        raise ValueError("Exact commit identities required")
    env = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
    }
    command = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(source),
    ]

    def git(*args):
        return builds._required([*command, *args], env=env).decode("utf-8")

    if git("rev-parse", "HEAD").strip() != revision:
        raise ValueError("Pipeline checkout identity mismatch")
    paths = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        base,
        revision,
        "--",
        "personal-apps/",
    ).split("\0")
    apps = set()
    for path in filter(None, paths):
        match = _APP_PATH.match(path)
        if not match:
            raise ValueError("Invalid personal app source boundary")
        apps.add(match[1])
    if len(apps) > 16:
        raise ValueError("Bounded app validation batch exceeded")
    results = []
    for app_id in sorted(apps):
        directory = f"personal-apps/{app_id}"
        # Read manifest as bounded Git data, then the builder verifies every
        # selected object hash against this exact commit before running anything.
        raw = builds._required(
            [*command, "show", f"{revision}:{directory}/app.manifest.json"],
            env=env,
            limit=65536,
        )
        definition = AppDefinition.model_validate_json(raw)
        if (
            definition.app_id,
            definition.source.directory,
            builds._identity(definition.source.repository),
        ) != (
            app_id,
            directory,
            builds._identity(repository),
        ):
            raise ValueError("App source identity mismatch")
        evidence = build(
            source=source,
            revision=revision,
            expected_definition=definition.model_dump(mode="json"),
            toolchain_image=image,
            work_root=work_root,
        )
        result = {
            "app_id": app_id,
            "source_revision": evidence.source_revision,
            "artifact": evidence.artifact_digest,
            "state": "passed",
        }
        if record_artifact is not None:
            record_artifact(result)
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config_path = args.config
        if not config_path.is_absolute() or config_path.resolve() != config_path:
            raise ValueError("Protected operator configuration required")
        stat = config_path.stat()
        if (
            stat.st_uid not in {0, os.getuid()}
            or stat.st_mode & 0o022
            or stat.st_size > 16384
        ):
            raise ValueError("Protected operator configuration required")
        config = json.loads(config_path.read_text())
        if set(config) != {"project_id", "repository", "toolchain_image", "work_root"}:
            raise ValueError("Invalid operator configuration")
        source = Path.cwd().resolve()
        work_root = Path(config["work_root"])
        if (
            source == CORE_ROOT
            or source in CORE_ROOT.parents
            or CORE_ROOT in source.parents
        ):
            raise ValueError("CI checkout must differ from installed Core")
        if (
            not work_root.is_absolute()
            or work_root.resolve() != work_root
            or not work_root.is_dir()
            or work_root.stat().st_mode & 0o077
        ):
            raise ValueError("Private preconfigured build scratch required")
        if (
            source == work_root
            or source in work_root.parents
            or work_root in source.parents
        ):
            raise ValueError("Build scratch must differ from source")
        env = os.environ
        if (
            env.get("CI_PIPELINE_SOURCE") != "merge_request_event"
            or env.get("CI_PROJECT_ID") != str(config["project_id"])
            or env.get("CI_MERGE_REQUEST_SOURCE_PROJECT_ID")
            != str(config["project_id"])
            or env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") not in {"dev", "main"}
            or (
                env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") == "main"
                and env.get("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME") != "dev"
            )
        ):
            raise ValueError("Same-project integration or release pipeline required")
        executor = executor_for_source(config, source, env)
        results = validate(
            source,
            revision=env.get("CI_COMMIT_SHA", ""),
            base=env.get("CI_MERGE_REQUEST_DIFF_BASE_SHA", ""),
            repository=config["repository"],
            image=config["toolchain_image"],
            work_root=work_root,
            record_artifact=executor.record_artifact,
        )
        print(json.dumps({"state": "passed", "apps": results}, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 — app/daemon diagnostics must never escape.
        print(
            json.dumps({"state": "failed", "code": "personal_app_validation_required"})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
