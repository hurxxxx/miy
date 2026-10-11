import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_independent_app_builds import repo

SPEC = importlib.util.spec_from_file_location(
    "personal_app_ci", Path(__file__).parents[3] / "scripts/personal-app-ci.py"
)
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


def test_personal_configs_are_read_as_data_and_passed_only_to_isolated_builder(tmp_path):
    source, base, definition, git = repo(tmp_path)
    app = source / "personal-apps/build-app"
    app.mkdir(parents=True)
    definition = definition.model_copy(
        update={
            "source": definition.source.model_copy(update={"directory": "personal-apps/build-app"})
        }
    )
    (app / "app.manifest.json").write_text(definition.model_dump_json())
    (app / "vite.config.ts").write_text("throw new Error('must never execute on CI host')")
    git("add", ".")
    git("commit", "-m", "personal CI fixture")
    head = git("rev-parse", "HEAD")
    calls = []

    def builder(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(source_revision=head, artifact_digest="sha256:" + "c" * 64)

    result = ci.validate(
        source,
        base=base,
        revision=head,
        repository=definition.source.repository,
        image="sha256:" + "a" * 64,
        work_root=tmp_path / "work",
        build=builder,
    )
    assert result[0]["app_id"] == "build-app"
    assert (
        len(calls) == 1
        and calls[0]["expected_definition"]["source"]["directory"] == "personal-apps/build-app"
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        ci.validate(
            source,
            base=base,
            revision=head,
            repository="https://foreign.test/repo.git",
            image="sha256:" + "a" * 64,
            work_root=tmp_path / "work",
            build=builder,
        )
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["failed", "timeout"])
def test_each_success_is_durable_before_later_build_failure_or_timeout(tmp_path, failure):
    source, base, definition, git = repo(tmp_path)
    for app_id in ("build-app", "second-app"):
        directory = f"personal-apps/{app_id}"
        app = source / directory
        app.mkdir(parents=True)
        value = definition.model_copy(
            update={
                "app_id": app_id,
                "source": definition.source.model_copy(update={"directory": directory}),
            }
        )
        (app / "app.manifest.json").write_text(value.model_dump_json())
    git("add", ".")
    git("commit", "-m", "Two synthetic app changes")
    head = git("rev-parse", "HEAD")
    scratch, jobs = tmp_path / "scratch", tmp_path / "jobs"
    scratch.mkdir(mode=0o700)
    jobs.mkdir(mode=0o700)
    root = jobs / "123"
    root.mkdir(mode=0o700)
    checkout = root / "source"
    shutil.copytree(source, checkout)
    config = {
        "project_id": 1,
        "repository": definition.source.repository,
        "toolchain_image": "sha256:" + "a" * 64,
        "work_root": str(scratch),
    }
    environment = {
        "CI_JOB_ID": "123",
        "CI_PROJECT_ID": "1",
        "CI_MERGE_REQUEST_SOURCE_PROJECT_ID": "1",
        "CI_PIPELINE_SOURCE": "merge_request_event",
        "CI_COMMIT_SHA": head,
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": base,
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "dev",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "feat/two-apps",
    }
    marker = root / "ownership.json"
    marker.write_text(
        json.dumps(
            {
                "identity": {
                    "job_id": "123",
                    "head": head,
                    "base": base,
                    "target": "dev",
                    "source_branch": "feat/two-apps",
                },
                "repository": definition.source.repository,
                "verification": {"project_id": 1, "pipeline_id": 45, "merge_request_iid": 7},
                "state": "validating",
                "artifacts": [],
                "removed": [],
            }
        )
    )
    marker.chmod(0o600)
    executor = ci.executor_for_source(config, checkout, environment)
    artifact = "sha256:" + "c" * 64
    calls = []

    def builder(**kwargs):
        calls.append(kwargs["expected_definition"]["app_id"])
        if calls[-1] == "second-app":
            # A new reader sees the first app's durable marker before this fails.
            observed = ci.executor_for_source(config, checkout, environment).read()
            assert observed["artifacts"][0]["artifact"] == artifact
            if failure == "timeout":
                raise subprocess.TimeoutExpired(["fixed-builder"], 180)
            raise RuntimeError("synthetic second build failed")
        return SimpleNamespace(source_revision=head, artifact_digest=artifact)

    error = subprocess.TimeoutExpired if failure == "timeout" else RuntimeError
    with pytest.raises(error):
        ci.validate(
            checkout,
            base=base,
            revision=head,
            repository=config["repository"],
            image=config["toolchain_image"],
            work_root=scratch,
            build=builder,
            record_artifact=executor.record_artifact,
        )
    assert calls == ["build-app", "second-app"]
    assert executor.read()["artifacts"] == [
        {"app_id": "build-app", "source_revision": head, "artifact": artifact, "state": "passed"}
    ]
    assert marker.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Exact runner checkout"):
        ci.executor_for_source(config, source, environment)
    with pytest.raises(RuntimeError, match="job_ownership_required"):
        ci.executor_for_source(
            config | {"repository": "https://foreign.test/repo"}, checkout, environment
        )
    receipt = json.loads(marker.read_text())
    receipt["verification"] = None
    marker.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Runner validation intent"):
        ci.executor_for_source(config, checkout, environment)
