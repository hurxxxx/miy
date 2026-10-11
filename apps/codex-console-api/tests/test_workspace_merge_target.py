"""Real disposable Git objects prove exact reviewed merges; remote transport is doubled."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_workspace_gitlab import feature_jobs, mr, project
from test_workspace_gitlab import item as item

from codex_console import app_checkpoints
from codex_console import workspace_gitlab as integration
from codex_console.errors import ConsoleError


def gated_api(item, target, merged, parents, calls, *, target_changes=False, lost_ack=False):
    merged_remote, target_reads = False, 0

    async def api(selected, suffix="", *, method="GET", **kwargs):
        nonlocal merged_remote, target_reads
        calls.append((method, suffix))
        source = item.source_revision
        request = {
            **mr(item),
            "sha": source,
            "head_pipeline": {"id": 3, "sha": source, "status": "success"},
        }
        if not suffix:
            return project()
        if suffix == "/merge_requests/2":
            return (
                {**request, "state": "merged", "merge_commit_sha": merged}
                if merged_remote
                else request
            )
        if suffix == "/pipelines/3":
            return {"sha": source, "status": "success", "source": "merge_request_event"}
        if suffix.startswith("/pipelines/3/jobs"):
            return feature_jobs()
        if suffix == "/repository/branches/dev":
            target_reads += 1
            value = "f" * 40 if target_changes and target_reads == 2 else target
            return {"protected": True, "commit": {"id": value}}
        if suffix == "/jobs/10/artifacts/codex-review-pipeline-context.md":
            assert kwargs["raw_response"]
            return json.dumps(
                {
                    "project_id": 1,
                    "mr_iid": 2,
                    "source_sha": source,
                    "target_sha": target,
                    "pipeline_id": 3,
                    "job_id": 10,
                    "runner_id": 4,
                    "conflicts": False,
                    "unresolved_blocking_discussions": False,
                    "pipeline_success_required_for_merge": True,
                    "discussions_resolved_required_for_merge": True,
                }
            ).encode()
        if suffix == "/merge_requests/2/merge":
            assert method == "PUT"
            assert kwargs["body"] == {
                "sha": source,
                "should_remove_source_branch": False,
                "squash": False,
            }
            assert target_reads == 2
            merged_remote = True
            if lost_ack:
                raise ConsoleError("workspace_gitlab_unavailable", 503)
            return {"state": "merged"}
        if suffix == "/repository/commits/" + merged:
            return {"id": merged, "parent_ids": parents}
        raise AssertionError("Unexpected native request")

    return api


def test_target_changed_before_merge_refuses_any_merge_dispatch(item, monkeypatch):
    calls, receipts = [], []
    monkeypatch.setattr(
        integration,
        "api",
        gated_api(item, "b" * 40, "c" * 40, [], calls, target_changes=True),
    )
    with pytest.raises(ConsoleError, match="workspace_integration_changed"):
        asyncio.run(
            integration.integrate(
                None,
                item,
                SimpleNamespace(
                    source_revision=item.source_revision,
                    receipt={"pushed": True, "mr_id": 2, "source_revision": item.source_revision},
                ),
                lambda receipt, state: receipts.append((receipt, state)),
            )
        )
    assert not receipts and all(method == "GET" for method, _ in calls)


def merge_objects(root, variant):
    native = app_checkpoints._git
    base = native(root, "rev-parse", "HEAD").decode().strip()
    entries = native(root, "ls-tree", "-z", base)

    def child(name):
        blob = native(root, "hash-object", "-w", "--stdin", data=name.encode()).strip()
        tree = native(
            root,
            "mktree",
            "-z",
            data=entries + b"100644 blob " + blob + b"\t" + name.encode() + b"\0",
        ).strip()
        return native(root, "commit-tree", tree.decode(), "-p", base, "-m", name).decode().strip()

    source, target = child("source.txt"), child("target.txt")
    expected_tree = native(root, "merge-tree", "--write-tree", "--no-messages", target, source)
    actual_target = target
    if variant == "advanced_target":
        target_tree = native(root, "rev-parse", target + "^{tree}").decode().strip()
        actual_target = (
            native(root, "commit-tree", target_tree, "-p", target, "-m", "Concurrent dev")
            .decode()
            .strip()
        )
    tree = (
        (
            native(root, "rev-parse", base + "^{tree}")
            if variant == "altered_tree"
            else expected_tree
        )
        .decode()
        .strip()
    )
    merged = (
        native(root, "commit-tree", tree, "-p", actual_target, "-p", source, "-m", "Merge")
        .decode()
        .strip()
    )
    native(root, "update-ref", "refs/remotes/origin/dev", merged)
    return source, target, merged, expected_tree.decode().strip(), [actual_target, source]


@pytest.mark.parametrize("variant", ["valid", "advanced_target", "altered_tree", "lost_ack"])
def test_native_merge_proof_and_same_intent_recovery_hold_wrong_target_or_tree(
    item, repository, monkeypatch, variant
):
    source, target, merged, expected_tree, parents = merge_objects(repository, variant)
    item.repository_root, item.source_revision = str(repository), source
    monkeypatch.setattr(integration.workspace_git, "revision", lambda *_: source)
    calls, receipts, fetches = [], [], []
    monkeypatch.setattr(
        integration,
        "api",
        gated_api(item, target, merged, parents, calls, lost_ack=variant == "lost_ack"),
    )
    native_git = integration.git.git

    def transport(root, *args, **kwargs):
        if kwargs.get("transport"):
            assert args == (
                "fetch",
                "--no-tags",
                "origin",
                "refs/heads/dev:refs/remotes/origin/dev",
            )
            assert receipts[-1][1] == "running"
            assert receipts[-1][0]["state"] == "unknown"
            assert receipts[-1][0]["merged_revision"] == merged
            fetches.append(args)
            return b""
        return native_git(root, *args, **kwargs)

    monkeypatch.setattr(integration.git, "git", transport)
    operation = SimpleNamespace(
        source_revision=source,
        receipt={"pushed": True, "mr_id": 2, "source_revision": source},
    )

    def persist(receipt, state):
        receipts.append((receipt, state))

    if variant == "valid":
        result = asyncio.run(integration.integrate(None, item, operation, persist))
        assert result["state"] == "merged" and result["merged_tree"] == expected_tree
        assert result["target_revision"] == target and receipts[-1][1] == "running"
    else:
        error = (
            "workspace_gitlab_unavailable"
            if variant == "lost_ack"
            else "workspace_operation_unknown"
        )
        with pytest.raises(ConsoleError, match=error):
            asyncio.run(integration.integrate(None, item, operation, persist))
        operation.receipt = receipts[-1][0]
        assert operation.receipt["target_revision"] == target
        if variant != "lost_ack":
            assert receipts[-1][1] == "running" and operation.receipt["state"] == "unknown"
            assert operation.receipt["merged_revision"] == merged
        before_calls, before_fetches = len(calls), len(fetches)
        observed = asyncio.run(integration.observe(None, item, operation))
        assert len(fetches) == before_fetches
        assert all(method == "GET" for method, _ in calls[before_calls:])
        if variant == "advanced_target":
            assert observed is None
        else:
            assert observed["state"] == "reviewing" and observed["target_revision"] == target
            assert observed["merge_attempted"] and observed["merged_revision"] == merged
            operation.receipt = observed
        if variant == "lost_ack":
            result = asyncio.run(integration.integrate(None, item, operation, persist))
            assert result["state"] == "merged" and result["merged_tree"] == expected_tree
        else:
            # Explicit same-intent continuation cannot turn wrong merge evidence into
            # deployment authority. It preserves the irreversible SHA and does not remerge.
            with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
                asyncio.run(integration.integrate(None, item, operation, persist))
            assert receipts[-1][1] == "running" and receipts[-1][0]["state"] == "unknown"
            assert receipts[-1][0]["merged_revision"] == merged
    assert sum(method == "PUT" for method, _ in calls) == 1
    assert all(method != "POST" for method, _ in calls)
