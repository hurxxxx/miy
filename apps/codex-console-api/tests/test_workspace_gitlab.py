"""Exact native GitLab gate/uncertainty doubles; no real remote mutation."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_console import workspace_gitlab as integration
from codex_console.errors import ConsoleError

SOURCE = "a" * 40
TARGET = "b" * 40
MERGED = "c" * 40


@pytest.fixture
def item(monkeypatch):
    value = SimpleNamespace(
        id=str(uuid4()),
        title="Disposable",
        branch="feature/wb-test",
        repository_root="/disposable/repository",
        worktree_root="/disposable/worktree",
        source_revision=SOURCE,
    )
    monkeypatch.setattr(
        integration.workspace_git, "validate", lambda *_: (Path(value.worktree_root), None, None)
    )
    monkeypatch.setattr(integration.workspace_git, "revision", lambda *_: SOURCE)
    monkeypatch.setattr(integration.git, "status", lambda *_: {"changed": False})
    monkeypatch.setattr(
        integration,
        "gitlab_origin",
        lambda *_: ("git.invalid", "team/miy", "https://git.invalid/team/miy"),
    )
    return value


def project():
    return {
        "id": 1,
        "only_allow_merge_if_pipeline_succeeds": True,
        "only_allow_merge_if_all_discussions_are_resolved": True,
        "merge_method": "merge",
        "squash_option": "default_off",
    }


def mr(item):
    return {
        "iid": 2,
        "source_project_id": 1,
        "target_project_id": 1,
        "source_branch": item.branch,
        "target_branch": "dev",
        "sha": SOURCE,
        "state": "opened",
        "has_conflicts": False,
        "blocking_discussions_resolved": True,
        "head_pipeline": {"id": 3, "sha": SOURCE, "status": "success"},
    }


def test_native_api_json_input_declares_content_type_without_changing_get(item, monkeypatch):
    calls = []

    class Input:
        def __init__(self):
            self.body = bytearray()
            self.closed = False

        def write(self, value):
            self.body.extend(value)

        async def drain(self):
            pass

        def close(self):
            self.closed = True

    async def spawn(*argv, **kwargs):
        output = asyncio.StreamReader()
        output.feed_data(b'{"iid": 2}')
        output.feed_eof()
        process = SimpleNamespace(stdin=Input(), stdout=output, returncode=None)

        async def wait():
            process.returncode = 0
            return 0

        process.wait = wait
        calls.append((argv, kwargs, process))
        return process

    monkeypatch.setattr(integration.asyncio, "create_subprocess_exec", spawn)
    body = {"source_branch": item.branch, "target_branch": "dev", "title": "Example"}
    assert asyncio.run(integration.api(item, "/merge_requests", method="POST", body=body)) == {
        "iid": 2
    }
    argv, options, process = calls[0]
    assert argv == (
        "glab",
        "api",
        "--method",
        "POST",
        "--hostname",
        "git.invalid",
        "projects/team%2Fmiy/merge_requests",
        "-H",
        "Content-Type: application/json",
        "--input",
        "-",
    )
    assert options["cwd"] == Path(item.repository_root)
    assert options["stdin"] == asyncio.subprocess.PIPE
    assert json.loads(process.stdin.body) == body and process.stdin.closed

    assert (
        asyncio.run(integration.api(item, "/merge_requests/2", raw_response=True)) == b'{"iid": 2}'
    )
    argv, options, process = calls[1]
    assert "-H" not in argv and "--input" not in argv
    assert options["stdin"] == asyncio.subprocess.DEVNULL
    assert not process.stdin.body and not process.stdin.closed


def test_app_validation_and_review_target_are_both_required_before_merge(item, monkeypatch):
    methods = []
    jobs = [
        {
            "id": index,
            "name": name,
            "allow_failure": False,
            "status": "success",
            "runner": {"id": 4},
        }
        for index, name in enumerate(("codex_review",), 10)
    ]

    async def api(selected, suffix="", *, method="GET", **kwargs):
        methods.append(method)
        if not suffix:
            return project()
        if suffix == "/merge_requests/2":
            return mr(item)
        if suffix == "/pipelines/3":
            return {"sha": SOURCE, "status": "success", "source": "merge_request_event"}
        if suffix.startswith("/pipelines/3/jobs"):
            return jobs
        raise AssertionError("Missing app validation must block before merge")

    monkeypatch.setattr(integration, "api", api)
    result = asyncio.run(
        integration.integrate(
            None,
            item,
            SimpleNamespace(
                source_revision=SOURCE,
                receipt={"pushed": True, "mr_id": 2, "source_revision": SOURCE},
            ),
            lambda *_: None,
        )
    )
    assert result["state"] == "reviewing"
    assert set(methods) == {"GET"}


def feature_jobs():
    return [
        {
            "id": index,
            "name": name,
            "allow_failure": False,
            "status": "success",
            "runner": {"id": 4},
        }
        for index, name in enumerate(("codex_review", "personal_app_validation"), 10)
    ]


def test_actual_feature_pipeline_merges_after_exact_review_without_release_job(item, monkeypatch):
    methods, receipts = [], []
    merged = False
    jobs = feature_jobs() + [
        {"id": 12, "name": "optional_check", "allow_failure": True, "status": "failed"}
    ]
    evidence = {
        "project_id": 1,
        "mr_iid": 2,
        "source_sha": SOURCE,
        "target_sha": TARGET,
        "pipeline_id": 3,
        "job_id": 10,
        "runner_id": 4,
        "conflicts": False,
        "unresolved_blocking_discussions": False,
        "pipeline_success_required_for_merge": True,
        "discussions_resolved_required_for_merge": True,
    }

    async def api(selected, suffix="", *, method="GET", **kwargs):
        nonlocal merged
        methods.append(method)
        if not suffix:
            return project()
        if suffix == "/merge_requests/2":
            return (
                {**mr(item), "state": "merged", "merge_commit_sha": MERGED} if merged else mr(item)
            )
        if suffix == "/pipelines/3":
            return {"sha": SOURCE, "status": "success", "source": "merge_request_event"}
        if suffix.startswith("/pipelines/3/jobs"):
            return jobs
        if suffix == "/repository/branches/dev":
            return {"protected": True, "commit": {"id": TARGET}}
        if suffix == "/jobs/10/artifacts/codex-review-pipeline-context.md":
            assert kwargs["raw_response"]
            return ("# Native evidence\n" + json.dumps(evidence)).encode()
        if suffix == "/merge_requests/2/merge":
            assert method == "PUT"
            assert kwargs["body"] == {
                "sha": SOURCE,
                "should_remove_source_branch": False,
                "squash": False,
            }
            assert receipts[-1][0]["merge_attempted"] is True
            merged = True
            return {"state": "merged"}
        raise AssertionError("Unexpected native request")

    async def merged_result(selected, receipt, revision, persist):
        assert selected is item and revision == MERGED and receipt["source_revision"] == SOURCE
        assert receipt["target_revision"] == TARGET and receipt["merge_attempted"] is True
        return {**receipt, "state": "merged", "merged_revision": revision}

    monkeypatch.setattr(integration, "api", api)
    monkeypatch.setattr(integration, "merged_result", merged_result)
    result = asyncio.run(
        integration.integrate(
            None,
            item,
            SimpleNamespace(
                source_revision=SOURCE,
                receipt={"pushed": True, "mr_id": 2, "source_revision": SOURCE},
            ),
            lambda receipt, state: receipts.append((receipt, state)),
        )
    )
    assert result["state"] == "merged" and result["merged_revision"] == MERGED
    assert methods.count("PUT") == 1 and methods.count("POST") == 0


@pytest.mark.parametrize(
    ("name", "status", "remove", "duplicate"),
    [
        ("codex_review", "success", True, False),
        ("personal_app_validation", "success", True, False),
        ("codex_review", "failed", False, False),
        ("personal_app_validation", "failed", False, False),
        ("additional_check", "pending", False, False),
        ("additional_check", "failed", False, False),
        ("codex_review", "failed", False, True),
    ],
)
def test_feature_pipeline_waits_for_missing_or_unsuccessful_nonoptional_checks(
    item, monkeypatch, name, status, remove, duplicate
):
    jobs = feature_jobs()
    if remove:
        jobs = [row for row in jobs if row["name"] != name]
    elif duplicate or name == "additional_check":
        # A successful same-name row must not conceal another required failure.
        jobs.insert(0, {"id": 12, "name": name, "allow_failure": False, "status": status})
    else:
        next(row for row in jobs if row["name"] == name)["status"] = status

    async def api(selected, suffix="", *, method="GET", **kwargs):
        assert method == "GET"
        if not suffix:
            return project()
        if suffix == "/merge_requests/2":
            return mr(item)
        if suffix == "/pipelines/3":
            return {"sha": SOURCE, "status": "success", "source": "merge_request_event"}
        if suffix.startswith("/pipelines/3/jobs"):
            return jobs
        raise AssertionError("The gate must hold before mutation or accepting review evidence")

    monkeypatch.setattr(integration, "api", api)
    result = asyncio.run(
        integration.integrate(
            None,
            item,
            SimpleNamespace(
                source_revision=SOURCE,
                receipt={"pushed": True, "mr_id": 2, "source_revision": SOURCE},
            ),
            lambda *_: pytest.fail("No merge intent may be recorded"),
        )
    )
    assert result["state"] == "reviewing"


def test_exact_target_review_evidence_rejects_stale_target():
    job = {"id": 10, "runner": {"id": 4}}
    value = {
        "project_id": 1,
        "mr_iid": 2,
        "source_sha": SOURCE,
        "target_sha": TARGET,
        "pipeline_id": 3,
        "job_id": 10,
        "runner_id": 4,
        "conflicts": False,
        "unresolved_blocking_discussions": False,
        "pipeline_success_required_for_merge": True,
        "discussions_resolved_required_for_merge": True,
    }
    raw = ("# Native safe review evidence\n" + json.dumps(value)).encode()
    assert (
        integration.review_evidence(
            raw, project_id=1, mr_id=2, source=SOURCE, target=TARGET, pipeline_id=3, job=job
        )
        == TARGET
    )
    with pytest.raises(ConsoleError, match="workspace_gitlab_gate_unavailable"):
        integration.review_evidence(
            raw, project_id=1, mr_id=2, source=SOURCE, target="d" * 40, pipeline_id=3, job=job
        )


def test_lost_mr_create_records_attempt_and_never_blindly_recreates(item, monkeypatch):
    markers = []

    async def api(selected, suffix="", *, method="GET", **kwargs):
        if not suffix:
            return project()
        if method == "GET":
            return []
        assert markers[-1]["create_attempted"] is True
        raise ConsoleError("workspace_gitlab_unavailable", 503)

    monkeypatch.setattr(integration, "api", api)
    operation = SimpleNamespace(
        source_revision=SOURCE, receipt={"pushed": True, "source_revision": SOURCE}
    )
    with pytest.raises(ConsoleError, match="workspace_gitlab_unavailable"):
        asyncio.run(
            integration.integrate(
                None, item, operation, lambda receipt, state: markers.append(receipt)
            )
        )
    operation.receipt = markers[-1]
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        asyncio.run(
            integration.integrate(None, item, operation, lambda *_: pytest.fail("No second write"))
        )


def test_get_reconciliation_accepts_only_exact_merged_mr_without_writes(item, monkeypatch):
    async def api(selected, suffix="", *, method="GET", **kwargs):
        assert method == "GET"
        if not suffix:
            return project()
        if suffix == "/repository/commits/" + MERGED:
            return {"id": MERGED, "parent_ids": [TARGET, SOURCE]}
        return {**mr(item), "state": "merged", "merge_commit_sha": MERGED}

    monkeypatch.setattr(integration, "api", api)
    result = asyncio.run(
        integration.observe(
            None,
            item,
            SimpleNamespace(
                source_revision=SOURCE,
                receipt={"mr_id": 2, "merge_attempted": True, "target_revision": TARGET},
            ),
        )
    )
    assert result["state"] == "reviewing" and result["merged_revision"] == MERGED
    assert result["target_revision"] == TARGET and result["merge_attempted"] is True
    item.branch = "feature/different"

    # A server response with another source branch must never resolve uncertainty.
    async def wrong(selected, suffix="", **kwargs):
        return project() if not suffix else {**mr(item), "source_branch": "feature/old"}

    monkeypatch.setattr(integration, "api", wrong)
    with pytest.raises(ConsoleError, match="workspace_integration_changed"):
        asyncio.run(
            integration.observe(
                None, item, SimpleNamespace(source_revision=SOURCE, receipt={"mr_id": 2})
            )
        )


def test_opened_mr_does_not_resolve_unknown_merge_attempt(item, monkeypatch):
    async def api(selected, suffix="", **kwargs):
        return project() if not suffix else mr(item)

    monkeypatch.setattr(integration, "api", api)
    assert (
        asyncio.run(
            integration.observe(
                None,
                item,
                SimpleNamespace(
                    source_revision=SOURCE, receipt={"mr_id": 2, "merge_attempted": True}
                ),
            )
        )
        is None
    )


def test_confirmed_merge_receipt_precedes_fixed_dev_ref_fetch(item, monkeypatch):
    calls = []

    def native_git(root, *args, **kwargs):
        assert root == Path(item.repository_root)
        assert args == ("fetch", "--no-tags", "origin", "refs/heads/dev:refs/remotes/origin/dev")
        assert kwargs["transport"]
        assert calls[0] == "running_unknown_receipt"
        calls.append("fetch")
        return b""

    monkeypatch.setattr(integration.git, "git", native_git)

    def proof(selected, saved, merged):
        assert selected is item and saved["target_revision"] == TARGET and merged == MERGED
        calls.append("merge_tree_proof")
        return "d" * 40

    monkeypatch.setattr(integration.workspace_git, "reviewed_merge_tree", proof)
    result = asyncio.run(
        integration.merged_result(
            item,
            {"source_revision": SOURCE, "target_revision": TARGET},
            MERGED,
            lambda value, state: calls.append(state + "_" + value["state"] + "_receipt"),
        )
    )
    assert result["merged_revision"] == MERGED
    assert result["merged_tree"] == "d" * 40
    assert calls == [
        "running_unknown_receipt",
        "fetch",
        "merge_tree_proof",
        "running_merged_receipt",
    ]
