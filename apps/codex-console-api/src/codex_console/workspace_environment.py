"""Managed native SDK and Core lifecycle; no source-selected execution commands."""

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from . import delivery_tools, git
from .config import AppExecutionEnvironment
from .errors import ConsoleError

LIMIT = 256 * 1024
POLL_SECONDS = 2
POLL_ATTEMPTS = 150


def _public(snapshot):
    keys = (
        "id",
        "app_id",
        "repository_root",
        "worktree_path",
        "app_directory",
        "branch",
        "base_revision",
        "source_revision",
        "profile_id",
    )
    return {key: snapshot[key] for key in keys if key in snapshot}


def _helper(settings, snapshot, action):
    command = settings.managed_environment_command
    if not command or not Path(command[0]).is_absolute():
        raise ConsoleError("workspace_environment_unconfigured", 503)
    if str(UUID(snapshot["id"])) != snapshot["id"]:
        raise ConsoleError("workspace_environment_unavailable", 409)
    # Only the trusted, fixed operator command selects the native environment.
    try:
        result = subprocess.run(
            [*command, action],
            input=json.dumps(_public(snapshot)).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60 if action != "describe" else 10,
            env={
                "PATH": os.defpath,
                **{
                    key: os.environ[key]
                    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
                    if key in os.environ
                },
            },
            check=False,
        )
        if len(result.stdout) > LIMIT:
            raise ConsoleError("workspace_environment_unavailable", 503)
        value = json.loads(result.stdout)
        if result.returncode:
            if isinstance(value, dict) and (
                value.get("state") == "unknown"
                or value.get("failure_code") == "workspace_operation_unknown"
            ):
                raise ConsoleError("workspace_operation_unknown", 409)
            if isinstance(value, dict) and value.get("failure_code") == "workspace_busy":
                raise ConsoleError("workspace_busy", 409)
            raise ConsoleError("workspace_environment_unavailable", 503)
        if not isinstance(value, dict):
            raise ValueError("Object required")
        return value
    except subprocess.TimeoutExpired:
        raise ConsoleError("workspace_operation_unknown", 409) from None
    except (OSError, ValueError):
        raise ConsoleError("workspace_environment_unavailable", 503) from None


def environment_for(settings, snapshot):
    """Server-only descriptor; credentials never enter Task context or UI output."""
    try:
        value = AppExecutionEnvironment.model_validate(_helper(settings, snapshot, "describe"))
    except ValueError:
        raise ConsoleError("workspace_environment_unavailable", 503) from None
    expected = Path(snapshot["worktree_path"]) / snapshot["app_directory"]
    if value.source_root != expected or value.source_root.resolve() != expected:
        raise ConsoleError("app_executor_changed", 409)
    return value


def _grant(settings, snapshot):
    values = [grant for grant in settings.app_delivery_grants if grant.app_id == snapshot["app_id"]]
    if len(values) != 1 or not settings.miy_api_origin:
        raise ConsoleError("app_delivery_unconfigured", 422)
    return values[0]


def _prefix(snapshot):
    return "/workspaces/" + str(UUID(snapshot["id"]))


async def _call(settings, snapshot, suffix, body=None, *, permanent=False, allow_missing=False):
    grant = _grant(settings, snapshot)
    evidence = None
    if body is not None and snapshot.get("record"):
        evidence = {
            "stage": suffix,
            "permanent": permanent,
            "acknowledged": False,
            "request_id": body.get("request_id"),
            "source_revision": snapshot.get("source_revision"),
        }
        snapshot["record"](evidence)
    try:
        result = await delivery_tools.api_request(
            settings,
            grant,
            ("" if permanent else _prefix(snapshot)) + suffix,
            body=body,
            allow_missing=allow_missing,
        )
        if evidence:
            snapshot["record"]({**evidence, "acknowledged": True})
        return result
    except ConsoleError as error:
        # An unavailable response after dispatch is not proof that a POST failed.
        if body is not None and error.code == "app_delivery_unavailable":
            raise ConsoleError("workspace_operation_unknown", 409) from None
        raise


def _manifest(snapshot):
    root = Path(snapshot["worktree_path"])
    raw = git.read_worktree_file(
        root, snapshot["app_directory"] + "/app.manifest.json", missing_ok=False
    )
    if len(raw) > 65536:
        raise ConsoleError("app_source_invalid", 422)
    try:
        value = json.loads(raw)
        if (
            value["app_id"] != snapshot["app_id"]
            or value["source"]["directory"] != snapshot["app_directory"]
        ):
            raise ValueError("Source changed")
        return value
    except (KeyError, ValueError, TypeError):
        raise ConsoleError("app_source_invalid", 422) from None


def _result(state, snapshot, context=None, revision=None, *, failure=None):
    installation = (context or {}).get("installation") or {}
    previous = snapshot.get("preview") or {}
    # A failed candidate keeps the previous verified link/revision, visibly stale.
    preview = {
        **previous,
        "state": state,
        "portal_url": (context or {}).get("portal_url") or previous.get("portal_url"),
        "installation_id": installation.get("id") or previous.get("installation_id"),
        "source_revision": revision or snapshot.get("source_revision"),
        "runtime_revision": revision if state == "ready" else previous.get("runtime_revision"),
        "failure_code": failure,
    }
    return {
        "state": state,
        "environment": {"state": "ready"},
        "preview": preview,
        "failure_code": failure,
    }


async def prepare(settings, snapshot):
    result = await asyncio.to_thread(_helper, settings, snapshot, "prepare")
    if result.get("state") != "ready":
        return {
            "state": result.get("state", "error"),
            "failure_code": result.get("failure_code", "workspace_environment_unavailable"),
        }
    await asyncio.to_thread(environment_for, settings, snapshot)
    try:
        context = await _call(settings, snapshot, "/context", allow_missing=True)
        if context is None:
            context = await _call(
                settings,
                snapshot,
                "/prepare",
                {
                    "profile_id": snapshot["profile_id"],
                    "definition": _manifest(snapshot),
                    "source_revision": snapshot["source_revision"],
                },
            )
        result = _result("configured", snapshot, context)
    except ConsoleError as error:
        if error.code == "workspace_operation_unknown":
            result = _result("unknown", snapshot, failure=error.code)
            result["operation_unknown"] = True
        elif error.code in {"app_delivery_unconfigured", "app_delivery_denied"}:
            # Editable source does not require registered preview authority yet.
            result = _result("unconfigured", snapshot, failure=error.code)
        else:
            result = _result("blocked", snapshot, failure=error.code)
    result["state"] = "ready"
    return result


async def _poll(settings, snapshot, path, *, permanent=False):
    for _ in range(POLL_ATTEMPTS):
        result = await _call(settings, snapshot, path, permanent=permanent)
        state = result.get("state")
        if state in {"succeeded", "failed", "unknown"}:
            return result
        if state not in {"queued", "running", "cleanup"}:
            raise ConsoleError("workspace_operation_unknown", 409)
        await asyncio.sleep(POLL_SECONDS)
    raise ConsoleError("workspace_operation_unknown", 409)


def _id(snapshot, operation, stage):
    return str(uuid5(NAMESPACE_URL, f"miy-workspace:{snapshot['id']}:{operation}:{stage}"))


async def _build_deploy(settings, snapshot, context, operation, revision, *, permanent=False):
    build_id = _id(snapshot, operation, "dev-build" if permanent else "build")
    build = await _call(
        settings, snapshot, "/builds/" + build_id, permanent=permanent, allow_missing=True
    )
    if build is None:
        build = await _call(
            settings,
            snapshot,
            "/builds",
            {
                "request_id": build_id,
                "source_revision": revision,
                "definition_digest": context["definition_digest"],
            },
            permanent=permanent,
        )
    if build["state"] not in {"succeeded", "failed", "unknown"}:
        build = await _poll(settings, snapshot, "/builds/" + build_id, permanent=permanent)
    if build["state"] != "succeeded":
        return _result(
            build["state"], snapshot, context, revision, failure=build.get("failure_code")
        )
    installation = context["installation"]
    request_id = _id(snapshot, operation, "dev-deploy" if permanent else "deploy")
    deployed = await _call(
        settings, snapshot, "/deployments/" + request_id, permanent=permanent, allow_missing=True
    )
    if deployed is None:
        deployed = await _call(
            settings,
            snapshot,
            "/deployments",
            {
                "request_id": request_id,
                "installation_id": installation["id"],
                "release_id": build["release_id"],
                "action": "deploy",
                "expected_generation": installation["generation"],
                "expected_release_id": installation.get("release_id"),
            },
            permanent=permanent,
        )
    if deployed["state"] not in {"succeeded", "failed", "unknown"}:
        deployed = await _poll(
            settings, snapshot, "/deployments/" + request_id, permanent=permanent
        )
    result = _result(
        "ready" if deployed["state"] == "succeeded" else deployed["state"],
        snapshot,
        context,
        revision,
        failure=deployed.get("failure_code"),
    )
    if result["state"] == "ready":
        result["deployment_id"] = request_id
    return result


async def refresh(settings, snapshot, operation_id, source_revision):
    context = await _call(settings, snapshot, "/context", allow_missing=True)
    if context is None:
        context = await _call(
            settings,
            snapshot,
            "/prepare",
            {
                "profile_id": snapshot["profile_id"],
                "definition": _manifest(snapshot),
                "source_revision": source_revision,
            },
        )
    context = await _call(
        settings,
        snapshot,
        "/sync",
        {
            "definition": _manifest(snapshot),
            "source_revision": source_revision,
            "expected_version": context["version"],
        },
    )
    return await _build_deploy(settings, snapshot, context, operation_id, source_revision)


async def integrate(settings, snapshot, operation_id, merged_revision):
    context = await _call(settings, snapshot, "/context")
    permanent = await _call(settings, snapshot, "/context", permanent=True)
    context = await _call(
        settings,
        snapshot,
        "/integrate",
        {
            "definition": _manifest(snapshot),
            "source_revision": merged_revision,
            "expected_version": context["version"],
            "expected_digest": permanent["definition_digest"],
            "expected_source_revision": permanent["source_revision"],
        },
    )
    permanent = await _call(settings, snapshot, "/context", permanent=True)
    # Core supplies the verified portal URL; no app-origin-derived link synthesis.
    permanent["portal_url"] = context.get("permanent_portal_url")
    if not permanent.get("portal_url"):
        raise ConsoleError("workspace_environment_unavailable", 503)
    result = await _build_deploy(
        settings, snapshot, permanent, operation_id, merged_revision, permanent=True
    )
    if result["state"] == "ready":
        completed = await _call(
            settings, snapshot, "/complete", {"deployment_id": result["deployment_id"]}
        )
        if (
            completed.get("source_handoff_complete") is not True
            or completed.get("integration_revision") != merged_revision
        ):
            raise ConsoleError("workspace_source_handoff_required", 409)
        result["dev_runtime_revision"] = merged_revision
        result["source_bound"] = True
    return result


async def _transition(settings, snapshot, action):
    # A stopped SDK is safe even before app registration. Core data is not removed
    # without the independent grant and its explicit integration/cleanup proof.
    if action == "stop":
        result = await asyncio.to_thread(_helper, settings, snapshot, action)
        if result.get("state") not in {"stopped", "cleaned"}:
            return {"state": result.get("state", "unknown"), "failure_code": "workspace_busy"}
    context = None
    try:
        context = await _call(settings, snapshot, "/context", allow_missing=True)
    except ConsoleError as error:
        if error.code != "app_delivery_unconfigured":
            raise
    if context is not None:
        wanted = {"stop": "stopped", "cleanup": "cleaned", "resume": "ready"}[action]
        if context["state"] != wanted and not (action == "stop" and context["state"] == "cleaned"):
            context = await _call(
                settings, snapshot, "/" + action, {"expected_version": context["version"]}
            )
        for _ in range(POLL_ATTEMPTS):
            if context["state"] == wanted or (action == "stop" and context["state"] == "cleaned"):
                break
            if context["state"] not in {"stopping", "cleanup_pending"}:
                raise ConsoleError("workspace_operation_unknown", 409)
            await asyncio.sleep(POLL_SECONDS)
            context = await _call(settings, snapshot, "/context")
        else:
            raise ConsoleError("workspace_operation_unknown", 409)
    if action != "stop":
        result = await asyncio.to_thread(_helper, settings, snapshot, action)
    preview = {
        **(snapshot.get("preview") or {}),
        "state": {
            "stop": "stopped",
            "cleanup": "cleaned",
            "resume": "configured" if context else "unconfigured",
        }[action],
    }
    core_unobserved = context is None and bool(
        (snapshot.get("preview") or {}).get("installation_id")
    )
    if core_unobserved:
        preview["state"] = "unknown"
        preview["failure_code"] = "app_delivery_unconfigured"
    return {
        "state": "blocked"
        if core_unobserved and action == "stop"
        else "stopped"
        if action == "stop" and result.get("state") == "cleaned"
        else result.get("state", "unknown"),
        "environment": {"state": result.get("state", "unknown")},
        "preview": preview,
        "failure_code": "app_delivery_unconfigured" if core_unobserved else None,
        "source_handoff_complete": bool(context and context.get("source_handoff_complete") is True),
    }


async def stop(settings, snapshot):
    return await _transition(settings, snapshot, "stop")


async def resume(settings, snapshot):
    return await _transition(settings, snapshot, "resume")


async def cleanup(settings, snapshot):
    return await _transition(settings, snapshot, "cleanup")


async def _observe_sdk(settings, snapshot, wanted):
    sdk = await asyncio.to_thread(_helper, settings, snapshot, "status")
    if wanted == "ready" and sdk.get("state") in {"ready", "unknown"}:
        # Describe verifies an existing execution and can recover an unknown start
        # journal. It never starts units or repeats their preparation.
        await asyncio.to_thread(environment_for, settings, snapshot)
        return {"state": "ready"}
    return sdk


def _completed_before_cleanup(snapshot, context, operation_id, revision):
    receipt = snapshot.get("operation_receipt") or {}
    evidence = receipt.get("core") or {}
    installation = context.get("installation") or {}
    merged = receipt.get("merged_revision")
    if not isinstance(evidence, dict) or not isinstance(installation, dict):
        return False
    return (
        snapshot.get("cleanup_quiescent") is True
        and isinstance(revision, str)
        and re.fullmatch(r"[a-f0-9]{40}", revision) is not None
        and snapshot.get("source_revision") == revision == receipt.get("source_revision")
        and isinstance(merged, str)
        and re.fullmatch(r"[a-f0-9]{40}", merged) is not None
        and receipt.get("state") == "merged"
        and receipt.get("merge_attempted") is True
        and not receipt.get("cleanup_remote_attempted")
        and evidence.get("stage") == "/complete"
        and evidence.get("acknowledged") is True
        and evidence.get("permanent") is False
        and evidence.get("source_revision") == revision
        and context.get("id") == snapshot["id"]
        and context.get("app_id") == snapshot["app_id"]
        and context.get("profile_id") == snapshot["profile_id"]
        and context.get("source_revision") == revision
        and bool(snapshot.get("preview_installation_id"))
        and installation.get("id") == snapshot["preview_installation_id"]
        and context.get("integration_revision") == merged
        and context.get("integration_deployment_id") == _id(snapshot, operation_id, "dev-deploy")
        and context.get("source_handoff_complete") is True
    )


async def observe(settings, snapshot, operation_id, kind, revision):
    """Reconcile exact existing evidence by GET/describe only; never resend writes."""
    try:
        context = await _call(settings, snapshot, "/context", allow_missing=True)
    except ConsoleError as error:
        if error.code != "app_delivery_unconfigured" or kind not in {
            "create",
            "stop",
            "resume",
            "cleanup",
        }:
            raise
        # Once Core prepared an installation, losing its grant does not prove
        # that its runtime/data stopped. SDK-only evidence applies before that.
        if (snapshot.get("preview") or {}).get("installation_id"):
            return None
        context = None
    if context is None:
        if kind not in {"create", "stop", "resume", "cleanup"}:
            return None
        if kind == "create" and (
            not revision
            or snapshot.get("source_revision") != revision
            or (snapshot.get("preview") or {}).get("installation_id")
            or ((snapshot.get("operation_receipt") or {}).get("core") or {}).get("stage")
            == "/prepare"
        ):
            # Missing Core context does not resolve an already dispatched prepare.
            return None
        wanted = {
            "create": "ready",
            "stop": "stopped",
            "resume": "ready",
            "cleanup": "cleaned",
        }[kind]
        sdk = await _observe_sdk(settings, snapshot, wanted)
        if sdk.get("state") != wanted and not (kind == "stop" and sdk.get("state") == "cleaned"):
            return None
        result = _result(
            "unconfigured" if kind in {"create", "resume"} else wanted,
            snapshot,
            revision=revision,
        )
        result["state"] = wanted
        result["environment"] = {"state": sdk["state"]}
        result["source_handoff_complete"] = False
        return result
    if kind == "create":
        if (
            context.get("source_revision") != revision
            or context.get("profile_id") != snapshot["profile_id"]
        ):
            return None
        await asyncio.to_thread(environment_for, settings, snapshot)
        result = _result("configured", snapshot, context, revision)
        result["state"] = "ready"
        return result
    if kind in {"stop", "resume", "cleanup"}:
        wanted = {"stop": "stopped", "resume": "ready", "cleanup": "cleaned"}[kind]
        if context.get("state") != wanted:
            if (
                kind == "cleanup"
                and context.get("state") in {"ready", "stopped"}
                and _completed_before_cleanup(snapshot, context, operation_id, revision)
            ):
                # A completed handoff followed by a rejected local stop has not
                # dispatched cleanup. Observe the existing execution only; the
                # same approved intent still requires an explicit continuation.
                sdk = await asyncio.to_thread(_helper, settings, snapshot, "status")
                if sdk.get("state") == "ready":
                    await asyncio.to_thread(environment_for, settings, snapshot)
                if sdk.get("state") in {"ready", "stopped"}:
                    return {"state": "waiting"}
            return None
        sdk = await _observe_sdk(settings, snapshot, wanted)
        if sdk.get("state") != wanted:
            evidence = (snapshot.get("operation_receipt") or {}).get("core") or {}
            if evidence.get("stage") == "/" + kind and sdk.get("state") in {"ready", "stopped"}:
                return {"state": "waiting"}
            return None
        result = _result("configured" if kind == "resume" else wanted, snapshot, context, revision)
        result["state"] = wanted
        result["environment"] = {"state": wanted}
        result["source_handoff_complete"] = context.get("source_handoff_complete") is True
        return result
    permanent = kind == "integrate"
    selected = await _call(settings, snapshot, "/context", permanent=True) if permanent else context
    if permanent:
        selected["portal_url"] = context.get("permanent_portal_url")
    deployed = await _call(
        settings,
        snapshot,
        "/deployments/" + _id(snapshot, operation_id, "dev-deploy" if permanent else "deploy"),
        permanent=permanent,
        allow_missing=True,
    )
    if deployed and deployed.get("state") in {"succeeded", "failed"}:
        if (
            permanent
            and deployed["state"] == "succeeded"
            and context.get("source_handoff_complete") is not True
        ):
            return {"state": "waiting", "failure_code": "workspace_source_handoff_required"}
        result = _result(
            "ready" if deployed["state"] == "succeeded" else "failed",
            snapshot,
            selected,
            revision,
            failure=deployed.get("failure_code"),
        )
        if permanent and result["state"] == "ready":
            result["dev_runtime_revision"] = revision
        return result
    build = await _call(
        settings,
        snapshot,
        "/builds/" + _id(snapshot, operation_id, "dev-build" if permanent else "build"),
        permanent=permanent,
        allow_missing=True,
    )
    if build and build.get("state") == "failed":
        return _result("failed", snapshot, selected, revision, failure=build.get("failure_code"))
    evidence = (snapshot.get("operation_receipt") or {}).get("core") or {}
    if build and build.get("state") == "succeeded" and evidence.get("stage") == "/builds":
        # The recorded uncertainty was the build acceptance; no deployment attempt
        # was dispatched by this operation. A human may continue the same intent.
        return {"state": "waiting"}
    if context.get("source_revision") == revision and evidence.get("stage") in {
        "/prepare",
        "/sync",
    }:
        return {"state": "waiting"}
    if (
        permanent
        and context.get("integration_revision") == revision
        and evidence.get("stage") == "/integrate"
    ):
        return {"state": "waiting"}
    return None
