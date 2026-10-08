"""Four bounded native actions for an explicit first-registration Task."""

import asyncio
import hashlib
import json
from typing import Literal

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, ValidationError

from . import app_checkpoints, registration, registration_source, store
from .errors import ConsoleError
from .models import now

TOOL_NAME = "miy_app_registration"


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["context", "checkpoint", "register", "status"]


def specs(task):
    if (task.context or {}).get("purpose") != "registration":
        return []
    return [
        {
            "name": TOOL_NAME,
            "description": (
                "First registration for this selected personal app Task. Read context first. "
                "The owner connects short authorization in Workbench. checkpoint safely "
                "commits local app files; register submits the committed manifest under "
                "implementation approval. status reads the same immutable operation. "
                "Unknown means inspect status, never invent an operation or auto retry. "
                "A receipt is historical registration of an inactive development install, "
                "not readiness or deployment. No paths, credentials or commands as inputs. "
                "This tool is only available in newly created registration threads."
            ),
            "inputSchema": Arguments.model_json_schema(),
        }
    ]


def credential(settings, factory, task_id, *, check):
    check()
    registration.configured(settings)
    with factory() as db:
        task, row = registration.require(db, task_id)
        if (row.issuer, row.audience, row.actor_user_id) != registration.configured(settings):
            raise ConsoleError("registration_authorization_required", 403)
        if (
            row.authorization_state != "ready"
            or not row.grant_id
            or not row.expires_at
            or row.expires_at <= now()
        ):
            raise ConsoleError("registration_authorization_required", 403)
        result = (row.request_id, row.grant_id, row.operation_id, row.policy, row.request_body)
    try:
        token = registration.secret(settings, result[0], "token")
    except (ConsoleError, OSError, ValueError):
        raise ConsoleError("registration_authorization_required", 403) from None
    return result, token


def checked_receipt(value, operation_id, app_id, body):
    receipt = registration.Receipt.model_validate(value)
    if str(receipt.operation_id) != operation_id or receipt.app_id != app_id:
        raise ValueError("Receipt identity mismatch")
    if body:
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(body["definition"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        if (
            receipt.definition_digest != digest
            or receipt.source_revision != body["source_revision"]
        ):
            raise ValueError("Receipt source mismatch")
    return receipt.model_dump(mode="json")


async def execute(settings, factory, task_id, action, *, check):
    check()
    if action == "context":
        with factory() as db:
            task, row = registration.require(db, task_id)
            result = {
                "operation_id": row.operation_id,
                "authorization_state": row.authorization_state,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "policy": row.policy,
                "state": row.state,
                "receipt": row.receipt,
                "submitted_source_revision": (row.request_body or {}).get("source_revision"),
                "checkpoint_available": not task.worktree_owned and row.request_body is None,
                "checkpoint_scope": "bound ordinary checkout on a named branch",
            }
        try:
            draft = await asyncio.to_thread(
                registration_source.snapshot, settings, factory, task_id
            )
            result.update(
                source_revision=draft.source_revision, definition_digest=draft.definition_digest
            )
        except ConsoleError as error:
            result["source_error"] = error.code
        check()
        return result
    identity, token = credential(settings, factory, task_id, check=check)
    request_id, grant_id, operation_id, policy, frozen = identity

    def current():
        check()
        with factory() as db:
            task, row = registration.require(db, task_id)
            if action in ("checkpoint", "register"):
                registration_source.require_binding(db, task)
            if (
                row.request_id != request_id
                or row.grant_id != grant_id
                or row.authorization_state != "ready"
                or not row.expires_at
                or row.expires_at <= now()
            ):
                raise ConsoleError("registration_authorization_required", 403)

    if action == "checkpoint":
        if frozen:
            raise ConsoleError("registration_request_frozen", 409)
        # Core checks current grant/source-session authority even if no receipt exists.
        # A missing receipt is not an assertion that the app ID is free.
        observed = await registration.api(
            settings, "/" + grant_id + "/receipt", token=token, missing=True
        )
        current()
        if observed is not None:
            raise ConsoleError("registration_request_frozen", 409)
        with factory() as db:
            task, _ = registration.require(db, task_id)
            if task.worktree_owned:
                raise ConsoleError("app_checkpoint_worktree_unsupported", 422)
            db.expunge(task)
        current()
        result = await asyncio.to_thread(app_checkpoints.checkpoint, settings, task)
        current()
        return result
    # Both reads and writes use the fixed operation. A missing receipt is not permission
    # to replay: only an explicit register action may submit the exact frozen body.
    observed = await registration.api(
        settings, "/" + grant_id + "/receipt", token=token, missing=True
    )
    current()
    if observed is not None:
        try:
            receipt = checked_receipt(observed, operation_id, policy["app_id"], frozen)
        except (ValueError, ValidationError):
            raise ConsoleError("registration_invalid_response", 503) from None
        with factory.begin() as db:
            _, row = registration.require(db, task_id)
            if row.request_id != request_id:
                raise ConsoleError("registration_authorization_required", 403)
            row.receipt, row.state, row.failure_code = receipt, "registered", None
        return {"state": "registered", "receipt": receipt, "historical": True}
    if action == "status":
        return {
            "state": "not_observed",
            "operation_id": operation_id,
            "submitted": frozen is not None,
        }
    draft = await asyncio.to_thread(registration_source.snapshot, settings, factory, task_id)
    current()
    if registration.policy_for(draft, policy["origin"]).model_dump(mode="json") != policy:
        raise ConsoleError("registration_policy_changed", 409)
    body = {
        "operation_id": operation_id,
        "definition": draft.definition,
        "source_revision": draft.source_revision,
        "origin": policy["origin"],
        "granted_permissions": [],
    }
    if frozen is not None and frozen != body:
        raise ConsoleError("registration_request_frozen", 409)
    # Intent is durable before transport. No timeout/error path clears or replaces it.
    with factory.begin() as db:
        _, row = registration.require(db, task_id)
        if row.request_id != request_id or (
            row.request_body is not None and row.request_body != body
        ):
            raise ConsoleError("registration_request_conflict", 409)
        row.request_body, row.state, row.failure_code = body, "unknown", None
        row.updated_at = now()
    current()
    try:
        result = await registration.api(
            settings, "/" + grant_id + "/bootstrap", token=token, body=body
        )
        current()
        receipt = checked_receipt(result, operation_id, policy["app_id"], body)
        with factory.begin() as db:
            _, row = registration.require(db, task_id)
            if row.request_id != request_id:
                raise ConsoleError("registration_authorization_required", 403)
            row.receipt, row.state = receipt, "registered"
        return {"state": "registered", "receipt": receipt, "historical": True}
    except (ConsoleError, ValueError, ValidationError):
        return {"state": "unknown", "operation_id": operation_id, "next_action": "status"}


async def handle(runtime, message, *, generation=None):
    if (
        message.get("method") != "item/tool/call"
        or message.get("params", {}).get("tool") != TOOL_NAME
    ):
        return False
    params = message.get("params", {})
    rpc = runtime.rpc
    if not rpc or (generation and generation != rpc.generation):
        return True
    result, success = {"error": "registration_denied"}, False
    try:
        from .rpc import REMOTE_CONTRACT

        Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallParams"]).validate(params)
        args = Arguments.model_validate(params.get("arguments"))
        if not runtime.remote_task_id:
            raise ConsoleError("registration_denied", 403)

        def check():
            if runtime.rpc is not rpc or (generation and generation != rpc.generation):
                raise ConsoleError("registration_denied", 403)
            with runtime.factory() as db:
                task, _ = registration.require(db, runtime.remote_task_id)
                if (
                    task.thread_id != params.get("threadId")
                    or task.turn_id != params.get("turnId")
                    or task.runtime_generation != rpc.generation
                    or task.executor != runtime.executor
                    or task.status not in store.ACTIVE
                ):
                    raise ConsoleError("registration_denied", 403)
                runtime.require_allowed_task(task)
                if args.action in (
                    "checkpoint",
                    "register",
                ) and not store.implementation_authorized(db, task):
                    raise ConsoleError("registration_denied", 403)

        async with runtime.task_gate(runtime.remote_task_id):
            result = await execute(
                runtime.settings, runtime.factory, runtime.remote_task_id, args.action, check=check
            )
        success = True
    except ConsoleError as error:
        result = {"error": error.code}
    except (ValidationError, SchemaError, ValueError, KeyError):
        result = {"error": "registration_invalid_response"}
    if runtime.rpc is rpc and (not generation or generation == rpc.generation):
        await rpc.respond(
            message["id"],
            {
                "contentItems": [{"type": "inputText", "text": json.dumps(result)}],
                "success": success,
            },
        )
    return True
