"""Exact-identity GitLab integration; remote uncertainty is never a new request."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode

from . import git, workspace_git
from .errors import ConsoleError
from .workbench_sources import gitlab_origin


async def api(item, suffix="", *, method="GET", body=None, raw_response=False):
    root = Path(item.repository_root)
    host, project, _ = await asyncio.to_thread(gitlab_origin, root)
    route = "projects/" + quote(project, safe="") + suffix
    argv = ["glab", "api", "--method", method, "--hostname", host, route]
    if body is not None:
        argv += ["-H", "Content-Type: application/json", "--input", "-"]
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=root,
            env={key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ},
            stdin=asyncio.subprocess.PIPE if body is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        raise ConsoleError("workspace_gitlab_unavailable", 503) from None
    try:
        async with asyncio.timeout(20):
            if body is not None:
                process.stdin.write(json.dumps(body).encode())
                await process.stdin.drain()
                process.stdin.close()
            raw = bytearray()
            while chunk := await process.stdout.read(65536):
                raw += chunk
                if len(raw) > 1024 * 1024:
                    raise ConsoleError("workspace_gitlab_unavailable", 503)
            if await process.wait() != 0:
                raise ConsoleError("workspace_gitlab_unavailable", 503)
            return bytes(raw) if raw_response else json.loads(raw)
    except (TimeoutError, ValueError, RecursionError):
        raise ConsoleError("workspace_gitlab_unavailable", 503) from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def identity(item, project, mr, source):
    if (
        not isinstance(project.get("id"), int)
        or not isinstance(mr.get("iid"), int)
        or mr.get("source_project_id") != project["id"]
        or mr.get("target_project_id") != project["id"]
        or mr.get("source_branch") != item.branch
        or mr.get("target_branch") != "dev"
        or mr.get("sha") != source
    ):
        raise ConsoleError("workspace_integration_changed", 409)


def review_evidence(raw, *, project_id, mr_id, source, target, pipeline_id, job):
    """Read only the existing native review owner's safe pipeline evidence object."""
    try:
        objects = [
            json.loads(line) for line in raw.decode("utf-8").splitlines() if line.startswith("{")
        ]
        if len(objects) != 1:
            raise ValueError
        value = objects[0]
        expected = {
            "project_id": project_id,
            "mr_iid": mr_id,
            "source_sha": source,
            "target_sha": target,
            "pipeline_id": pipeline_id,
            "job_id": job["id"],
            "runner_id": (job.get("runner") or {}).get("id"),
            "conflicts": False,
            "unresolved_blocking_discussions": False,
            "pipeline_success_required_for_merge": True,
            "discussions_resolved_required_for_merge": True,
        }
        if not isinstance(expected["runner_id"], int) or any(
            value.get(key) != wanted for key, wanted in expected.items()
        ):
            raise ValueError
        return value["target_sha"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ConsoleError("workspace_gitlab_gate_unavailable", 409) from None


async def merged_result(item, saved, merged, persist):
    if not workspace_git.OID.fullmatch(merged or ""):
        raise ConsoleError("workspace_gitlab_ambiguous", 409)
    result = {**saved, "state": "unknown", "merged_revision": merged}
    # Save the irreversible result before fetching/proving it. GitLab's source
    # SHA guard is not an atomic expected-target guard; unknown cannot deploy.
    # The live executor owns this attempt until it exits. Only failure/startup
    # recovery may release its running fence into reconciliable unknown state.
    persist(result, "running")
    if not workspace_git.OID.fullmatch(saved.get("target_revision") or ""):
        raise ConsoleError("workspace_operation_unknown", 409)
    root = Path(item.repository_root)
    await asyncio.to_thread(
        git.git,
        root,
        "fetch",
        "--no-tags",
        "origin",
        "refs/heads/dev:refs/remotes/origin/dev",
        transport=True,
    )
    tree = await asyncio.to_thread(workspace_git.reviewed_merge_tree, item, saved, merged)
    result = {**result, "state": "merged", "merged_tree": tree}
    persist(result, "running")
    return result


async def integrate(settings, item, operation, persist):
    workspace_git.validate(settings, item)
    source = operation.source_revision
    if (
        workspace_git.revision(Path(item.worktree_root)) != source
        or git.status(Path(item.worktree_root))["changed"]
    ):
        raise ConsoleError("workspace_source_changed", 409)
    project = await api(item)
    if (
        project.get("only_allow_merge_if_pipeline_succeeds") is not True
        or project.get("only_allow_merge_if_all_discussions_are_resolved") is not True
        or project.get("merge_method") != "merge"
        or project.get("squash_option") not in {"never", "default_off", "default_on"}
    ):
        raise ConsoleError("workspace_gitlab_gate_unavailable", 409)
    _, _, web = gitlab_origin(Path(item.repository_root))
    saved = {**(operation.receipt or {}), "source_revision": source}
    if not saved.get("pushed") or (operation.receipt or {}).get("source_revision") != source:
        # A new managed feature ref can be created once; existing refs must equal
        # the frozen source. Append verified history with an exact ref lease.
        # Never push dev/main.
        rows = await asyncio.to_thread(
            git.git,
            Path(item.repository_root),
            "ls-remote",
            "--heads",
            "origin",
            "refs/heads/" + item.branch,
            transport=True,
        )
        existing = rows.decode().split()
        ref = "refs/heads/" + item.branch
        previous_source = (operation.receipt or {}).get("source_revision")
        if existing and existing != [source, ref]:
            if existing != [previous_source, ref] or not workspace_git.OID.fullmatch(
                previous_source or ""
            ):
                raise ConsoleError("workspace_remote_branch_changed", 409)
            from .app_checkpoints import _git

            await asyncio.to_thread(
                _git,
                Path(item.worktree_root),
                "merge-base",
                "--is-ancestor",
                previous_source,
                source,
            )
            persist({**saved, "push_attempted": True}, "running")
            # Native expected-ref CAS protects races after append-only history proof.
            await asyncio.to_thread(
                git.git,
                Path(item.worktree_root),
                "push",
                "--porcelain",
                "--force-with-lease=" + ref + ":" + previous_source,
                "origin",
                source + ":" + ref,
                transport=True,
            )
        elif not existing:
            persist({**saved, "push_attempted": True}, "running")
            await asyncio.to_thread(
                git.git,
                Path(item.worktree_root),
                "push",
                "--porcelain",
                "--force-with-lease=" + ref + ":",
                "origin",
                source + ":refs/heads/" + item.branch,
                transport=True,
            )
        saved = {**saved, "pushed": True}
        persist(saved, "running")
    marker = "MIY Workspace " + item.id + " source " + source
    if saved.get("mr_id"):
        mr = await api(item, "/merge_requests/" + str(saved["mr_id"]))
    else:
        query = urlencode(
            {
                "scope": "all",
                "state": "all",
                "source_branch": item.branch,
                "target_branch": "dev",
                "per_page": 2,
            }
        )
        rows = await api(item, "/merge_requests?" + query)
        if not isinstance(rows, list) or len(rows) > 1:
            raise ConsoleError("workspace_gitlab_ambiguous", 409)
        if rows:
            mr = rows[0]
            if marker not in (mr.get("description") or ""):
                raise ConsoleError("workspace_gitlab_ambiguous", 409)
        elif saved.get("create_attempted"):
            # No visible MR after an unacknowledged create is not proof of failure.
            raise ConsoleError("workspace_operation_unknown", 409)
        else:
            persist({**saved, "create_attempted": True}, "running")
            mr = await api(
                item,
                "/merge_requests",
                method="POST",
                body={
                    "source_branch": item.branch,
                    "target_branch": "dev",
                    "title": "Workbench: " + item.title,
                    "description": marker,
                    "remove_source_branch": False,
                },
            )
        identity(item, project, mr, source)
        saved = {**saved, "mr_id": mr["iid"], "mr_url": web + "/-/merge_requests/" + str(mr["iid"])}
        persist(saved, "running")
    identity(item, project, mr, source)
    if mr.get("state") == "merged":
        merged = mr.get("merge_commit_sha") or mr.get("squash_commit_sha")
        if not workspace_git.OID.fullmatch(merged or ""):
            raise ConsoleError("workspace_gitlab_ambiguous", 409)
        return await merged_result(item, {**saved, "source_revision": source}, merged, persist)
    if (
        mr.get("state") != "opened"
        or mr.get("has_conflicts") is not False
        or mr.get("blocking_discussions_resolved") is not True
    ):
        return {**saved, "state": "blocked", "failure_code": "workspace_gitlab_review_required"}
    head = mr.get("head_pipeline") or {}
    if (
        type(head.get("id")) is not int
        or head.get("sha") != source
        or head.get("status") != "success"
    ):
        return {**saved, "state": "reviewing"}
    pipeline = await api(item, "/pipelines/" + str(head["id"]))
    if (
        pipeline.get("sha") != source
        or pipeline.get("status") != "success"
        or pipeline.get("source") != "merge_request_event"
    ):
        raise ConsoleError("workspace_gitlab_gate_unavailable", 409)
    jobs = await api(item, f"/pipelines/{head['id']}/jobs?per_page=100&include_retried=false")
    if (
        not isinstance(jobs, list)
        or len(jobs) >= 100
        or any(
            not isinstance(row, dict) or type(row.get("allow_failure")) is not bool for row in jobs
        )
    ):
        raise ConsoleError("workspace_gitlab_gate_unavailable", 409)
    checks = [row for row in jobs if row["allow_failure"] is False]
    required = {row.get("name"): row for row in checks}
    # This adapter merges feature -> dev; release_validation belongs to dev -> main.
    # Require the actual feature checks and every other nonoptional pipeline job.
    if not {"codex_review", "personal_app_validation"}.issubset(required) or any(
        row.get("status") != "success" for row in checks
    ):
        return {**saved, "state": "reviewing"}
    target = await api(item, "/repository/branches/dev")
    if target.get("protected") is not True or not workspace_git.OID.fullmatch(
        (target.get("commit") or {}).get("id", "")
    ):
        raise ConsoleError("workspace_gitlab_gate_unavailable", 409)
    review = required["codex_review"]
    raw_evidence = await api(
        item,
        f"/jobs/{review['id']}/artifacts/codex-review-pipeline-context.md",
        raw_response=True,
    )
    review_evidence(
        raw_evidence,
        project_id=project["id"],
        mr_id=mr["iid"],
        source=source,
        target=target["commit"]["id"],
        pipeline_id=head["id"],
        job=review,
    )
    # Re-read MR before mutation. GitLab enforces native gates and exact source sha.
    current = await api(item, "/merge_requests/" + str(mr["iid"]))
    identity(item, project, current, source)
    if (current.get("head_pipeline") or {}).get("id") != head["id"]:
        raise ConsoleError("workspace_integration_changed", 409)
    latest_target = await api(item, "/repository/branches/dev")
    if (
        latest_target.get("protected") is not True
        or (latest_target.get("commit") or {}).get("id") != target["commit"]["id"]
    ):
        raise ConsoleError("workspace_integration_changed", 409)
    saved = {**saved, "merge_attempted": True, "target_revision": target["commit"]["id"]}
    persist(saved, "running")
    await api(
        item,
        f"/merge_requests/{mr['iid']}/merge",
        method="PUT",
        body={"sha": source, "should_remove_source_branch": False, "squash": False},
    )
    confirmed = await api(item, "/merge_requests/" + str(mr["iid"]))
    identity(item, project, confirmed, source)
    if confirmed.get("state") != "merged":
        return {**saved, "state": "unknown", "failure_code": "workspace_operation_unknown"}
    merged = confirmed.get("merge_commit_sha") or confirmed.get("squash_commit_sha")
    if not workspace_git.OID.fullmatch(merged or ""):
        raise ConsoleError("workspace_gitlab_ambiguous", 409)
    return await merged_result(item, {**saved, "source_revision": source}, merged, persist)


async def remove_remote(settings, item, record=None):
    source = item.source_revision
    if (item.integration or {}).get("source_revision") != source or not (
        item.integration or {}
    ).get("mr_id"):
        raise ConsoleError("workspace_not_integrated", 409)
    project = await api(item)
    mr = await api(item, "/merge_requests/" + str(item.integration["mr_id"]))
    identity(item, project, mr, source)
    if mr.get("state") != "merged":
        raise ConsoleError("workspace_not_integrated", 409)
    root = Path(item.repository_root)
    ref = "refs/heads/" + item.branch
    remote = await asyncio.to_thread(
        git.git, root, "ls-remote", "--heads", "origin", ref, transport=True
    )
    if not remote.strip():
        return
    if remote.decode().split() != [source, ref]:
        raise ConsoleError("workspace_remote_branch_changed", 409)
    # Native expected-OID lease makes DELETE atomic; no history is overwritten.
    if record:
        record(True)
    await asyncio.to_thread(
        git.git,
        root,
        "push",
        "--porcelain",
        "--force-with-lease=" + ref + ":" + source,
        "origin",
        ":" + ref,
        transport=True,
    )
    if record:
        record(False)


async def observe(settings, item, operation):
    """Inspect an exact lost remote acknowledgement without dispatching a write."""
    workspace_git.validate(settings, item)
    source = operation.source_revision
    saved = dict(operation.receipt or {})
    if source != item.source_revision:
        return None
    project = await api(item)
    query = urlencode(
        {
            "scope": "all",
            "state": "all",
            "source_branch": item.branch,
            "target_branch": "dev",
            "per_page": 2,
        }
    )
    if saved.get("mr_id"):
        mr = await api(item, "/merge_requests/" + str(saved["mr_id"]))
    else:
        rows = await api(item, "/merge_requests?" + query)
        if not isinstance(rows, list) or len(rows) > 1:
            raise ConsoleError("workspace_gitlab_ambiguous", 409)
        if not rows:
            if saved.get("create_attempted") or saved.get("merge_attempted"):
                return None
            remote = await asyncio.to_thread(
                git.git,
                Path(item.repository_root),
                "ls-remote",
                "--heads",
                "origin",
                "refs/heads/" + item.branch,
                transport=True,
            )
            if remote.decode().split() == [source, "refs/heads/" + item.branch]:
                return {"source_revision": source, "pushed": True, "state": "reviewing"}
            return None
        mr = rows[0]
        marker = "MIY Workspace " + item.id + " source " + source
        if marker not in (mr.get("description") or ""):
            raise ConsoleError("workspace_gitlab_ambiguous", 409)
    identity(item, project, mr, source)
    _, _, web = gitlab_origin(Path(item.repository_root))
    saved = {
        **saved,
        "source_revision": source,
        "pushed": True,
        "mr_id": mr["iid"],
        "mr_url": web + "/-/merge_requests/" + str(mr["iid"]),
    }
    if mr.get("state") == "merged":
        merged = mr.get("merge_commit_sha") or mr.get("squash_commit_sha")
        if not workspace_git.OID.fullmatch(merged or ""):
            raise ConsoleError("workspace_gitlab_ambiguous", 409)
        target = saved.get("target_revision")
        if not workspace_git.OID.fullmatch(target or ""):
            return None
        commit = await api(item, "/repository/commits/" + merged)
        if commit.get("id") != merged or commit.get("parent_ids") != [target, source]:
            return None
        # GETs preserve target proof without writing Git objects. Only explicit
        # same-intent continuation fetches and verifies the resulting merge tree.
        return {**saved, "state": "reviewing", "merged_revision": merged}
    if (operation.receipt or {}).get("merge_attempted"):
        # An opened MR is not proof that an unacknowledged merge was rejected.
        return None
    if mr.get("state") == "opened":
        return {**saved, "state": "reviewing"}
    return None


async def cleanup_observed(settings, item):
    """Read an exact deleted remote ref; a still-visible ref is not failure proof."""
    root = workspace_git.repository(settings)
    if root != Path(item.repository_root):
        raise ConsoleError("workspace_source_changed", 409)
    source = item.source_revision
    if (item.integration or {}).get("source_revision") != source or not (
        item.integration or {}
    ).get("mr_id"):
        raise ConsoleError("workspace_not_integrated", 409)
    project = await api(item)
    mr = await api(item, "/merge_requests/" + str(item.integration["mr_id"]))
    identity(item, project, mr, source)
    if mr.get("state") != "merged":
        return False
    remote = await asyncio.to_thread(
        git.git, root, "ls-remote", "--heads", "origin", "refs/heads/" + item.branch, transport=True
    )
    return not remote.strip()
