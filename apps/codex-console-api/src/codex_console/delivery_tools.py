"""Bounded native tools for a single explicitly selected development installation.

The platform owns permissions, verification and durable execution. This adapter
never runs Docker, the platform operator CLI, or commands supplied by a model.
"""

import asyncio
import copy
import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from jsonschema import Draft7Validator, Draft202012Validator, validators
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import app_sources, git, store
from .errors import ConsoleError
from .models import Task

TOOL_NAME = "miy_app_delivery"
MAX_BYTES = 1024 * 1024
Action = Literal[
    "context",
    "checkpoint",
    "sync",
    "build",
    "build_status",
    "deploy",
    "rollback",
    "deployment_status",
]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    request_id: UUID | None = None
    release_id: UUID | None = None
    retry_request_id: UUID | None = None

    @model_validator(mode="after")
    def exact_inputs(self):
        if (self.action in ("build_status", "deployment_status")) != (self.request_id is not None):
            raise ValueError("Status requires the existing request ID")
        if (self.action in ("deploy", "rollback")) != (self.release_id is not None):
            raise ValueError("Deployment requires an exact verified release ID")
        if self.retry_request_id and self.action not in ("build", "deploy", "rollback"):
            raise ValueError("Only a confirmed failed build or deployment can be retried")
        return self


class Installation(BaseModel):
    id: UUID
    environment: Literal["development"]
    origin: str = Field(max_length=300)
    generation: int = Field(ge=1)
    release_id: UUID | None
    state: str = Field(max_length=32)
    enabled: bool


class VerifiedRelease(BaseModel):
    id: UUID
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    artifact: str = Field(max_length=500)
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    verified_at: datetime
    rollback_allowed: bool


class PendingDeployment(BaseModel):
    id: UUID
    release_id: UUID
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "unknown"]


class DeliveryContext(BaseModel):
    app_id: str
    definition: dict
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    installation: Installation
    releases: list[VerifiedRelease] = Field(max_length=50)
    pending_deployment: PendingDeployment | None = None
    allowed_actions: list[Literal["read", "sync", "build", "deploy", "rollback"]] = Field(
        max_length=5
    )


class BuildRecord(BaseModel):
    id: UUID
    app_id: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    state: Literal["queued", "running", "succeeded", "failed", "unknown"]
    failure_code: str | None = Field(default=None, max_length=80)
    release_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DeploymentRecord(BaseModel):
    id: UUID
    installation_id: UUID
    release_id: UUID
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "succeeded", "failed", "unknown"]
    failure_code: str | None = Field(default=None, max_length=80)
    previous_release_id: UUID | None
    observed_image_id: str | None = Field(default=None, max_length=500)
    created_at: datetime
    updated_at: datetime


def grant_for(settings, context):
    app_id, installation = context.get("app_id"), context.get("installation_id")
    if not app_id or not installation or not settings.miy_api_origin:
        raise ConsoleError("app_delivery_unconfigured", 422)
    grant = next(
        (
            item
            for item in settings.app_delivery_grants
            if item.app_id == app_id and str(item.installation_id) == str(installation)
        ),
        None,
    )
    if grant is None:
        raise ConsoleError("app_delivery_unconfigured", 422)
    return grant


def validate_target(settings, context):
    if not context.get("installation_id"):
        return
    if context.get("purpose") not in ("inspection", "deployment", "recovery"):
        raise ConsoleError("invalid_input", 422)
    if not context.get("source_binding"):
        raise ConsoleError("app_source_unavailable", 422)
    grant_for(settings, context)
    context["environment"] = "development"


def specs(task):
    if not (task.context or {}).get("installation_id"):
        return []
    return [
        {
            "name": TOOL_NAME,
            "description": (
                "Inspect or deliver this task's selected development app installation. "
                "Read context first. checkpoint creates a local app commit with bounded safe "
                "source files; sync registers the bound clean Git HEAD and manifest; "
                "build queues core verification of that exact registered commit. "
                "Deploy/rollback require a verified release ID. Status reads an existing request. "
                "Queued/running/unknown are not success: inspect the same request, never invent "
                "a new request to resolve uncertainty. retry_request_id is only for an explicitly "
                "requested retry of a failed request. Mutations require authorized execution "
                "in a deployment/recovery task. This tool cannot publish or target production."
            ),
            "inputSchema": Arguments.model_json_schema(),
        }
    ]


async def api_request(settings, grant, suffix, *, body=None, allow_missing=False):
    base = (
        settings.miy_api_origin
        + "/api/v1/independent-apps/delegated/"
        + grant.app_id
        + "/installations/"
        + str(grant.installation_id)
    )
    try:
        async with (
            asyncio.timeout(15),
            httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client,
        ):
            async with client.stream(
                "GET" if body is None else "POST",
                base + suffix,
                headers={"Authorization": "Bearer " + grant.token.get_secret_value()},
                json=body,
            ) as response:
                if response.status_code in (401, 403):
                    raise ConsoleError("app_delivery_denied", 403)
                if allow_missing and response.status_code == 404:
                    return None
                if response.status_code in (409, 422):
                    raise ConsoleError("app_delivery_conflict", 409)
                if response.status_code not in (200, 201, 202):
                    raise ConsoleError("app_delivery_unavailable", 503)
                if response.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise ConsoleError("app_delivery_unavailable", 503)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ConsoleError("app_delivery_unavailable", 503)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Object response required")
        return value
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        raise ConsoleError("app_delivery_unavailable", 503) from None


async def read_context(settings, grant):
    context = DeliveryContext.model_validate(await api_request(settings, grant, "/context"))
    if context.app_id != grant.app_id or context.installation.id != grant.installation_id:
        raise ConsoleError("app_delivery_unavailable", 503)
    # Validate the definition as data. Repository prompts never change tool authority.
    app_sources.validator().validate(context.definition)
    if context.definition.get("app_id") != grant.app_id:
        raise ConsoleError("app_delivery_unavailable", 503)
    return context


def request_identity(task, kind, payload):
    # Stable across process loss and native turns. PostgreSQL owns execution and
    # payload conflict detection; no second workflow or retry engine lives here.
    target = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(target.encode()).hexdigest()
    return str(uuid5(NAMESPACE_URL, f"miy-app-delivery:v1:{task.id}:{kind}:{digest}"))


def local_source(settings, task):
    app_sources.require_task_source(settings, task)
    root = app_sources.task_workspace(settings, task)
    status = git.status(root)
    if status["changed"] or not status["head"]:
        raise ConsoleError("app_delivery_source_uncommitted", 409)
    manifest, _ = app_sources.read_manifest(settings, root, task.context["app_id"])
    return status["head"], normalize_manifest(manifest)


def normalize_manifest(manifest):
    result = copy.deepcopy(manifest)

    def properties(validator, properties, instance, schema):
        if isinstance(instance, dict):
            for name, definition in properties.items():
                if "default" in definition:
                    instance.setdefault(name, copy.deepcopy(definition["default"]))
        yield from Draft202012Validator.VALIDATORS["properties"](
            validator, properties, instance, schema
        )
        # JSON Schema accepts 1.0 as an integer; Pydantic's Literal[1] emits 1.
        # Only canonicalize already-validated integer constants declared by the
        # generated contract, without widening accepted input or coercing strings.
        if isinstance(instance, dict):
            for name, definition in properties.items():
                if (
                    name in instance
                    and definition.get("type") == "integer"
                    and type(definition.get("const")) is int
                ):
                    instance[name] = definition["const"]

    validator = validators.extend(Draft202012Validator, {"properties": properties})
    validator(app_sources.validator().schema).validate(result)
    return result


def checked_record(value, schema, grant, request_id):
    result = schema.model_validate(value)
    if str(result.id) != str(request_id):
        raise ConsoleError("app_delivery_unavailable", 503)
    if isinstance(result, BuildRecord) and result.app_id != grant.app_id:
        raise ConsoleError("app_delivery_unavailable", 503)
    if isinstance(result, DeploymentRecord) and result.installation_id != grant.installation_id:
        raise ConsoleError("app_delivery_unavailable", 503)
    return result.model_dump(mode="json")


async def execute(settings, task, args):
    grant = grant_for(settings, task.context)
    if args.action in ("build_status", "deployment_status"):
        kind = "builds" if args.action == "build_status" else "deployments"
        schema = BuildRecord if kind == "builds" else DeploymentRecord
        data = await api_request(settings, grant, f"/{kind}/{args.request_id}", allow_missing=True)
        if data is None:
            return {"state": "not_found", "request_id": str(args.request_id)}
        return checked_record(data, schema, grant, args.request_id)
    context = await read_context(settings, grant)
    if args.action == "context":
        return context.model_dump(mode="json")
    if (
        args.action in ("checkpoint", "sync", "build", "deploy")
        and task.context.get("purpose") != "deployment"
    ):
        raise ConsoleError("app_delivery_denied", 403)
    if args.action == "rollback" and task.context.get("purpose") != "recovery":
        raise ConsoleError("app_delivery_denied", 403)
    if args.action == "checkpoint":
        if not {"sync", "build"}.issubset(context.allowed_actions):
            raise ConsoleError("app_delivery_denied", 403)
        from .app_checkpoints import checkpoint

        return await asyncio.to_thread(checkpoint, settings, task)
    if args.action not in context.allowed_actions:
        raise ConsoleError("app_delivery_denied", 403)
    if args.action in ("sync", "build"):
        revision, manifest = await asyncio.to_thread(local_source, settings, task)
        if args.action == "sync":
            if context.source_revision != revision or context.definition != manifest:
                await api_request(
                    settings,
                    grant,
                    "/sync",
                    body={
                        "definition": manifest,
                        "source_revision": revision,
                        "expected_digest": context.definition_digest,
                        "expected_source_revision": context.source_revision,
                    },
                )
            # Read the authoritative state again; no model-authored success evidence.
            return (await read_context(settings, grant)).model_dump(mode="json")
        if context.source_revision != revision or context.definition != manifest:
            raise ConsoleError("app_delivery_conflict", 409)
        kind, schema = "builds", BuildRecord
        payload = {"source_revision": revision, "definition_digest": context.definition_digest}
    else:
        if context.pending_deployment:
            # Cutover may already have changed installation.release_id while
            # cleanup is incomplete or its result is unknown. Keep following the
            # authoritative request instead of projecting an installed success.
            return {
                **context.pending_deployment.model_dump(mode="json"),
                "next_action": "deployment_status",
            }
        if context.installation.release_id == args.release_id:
            return {
                "state": "already_installed",
                "installation": context.installation.model_dump(mode="json"),
            }
        selected = next((item for item in context.releases if item.id == args.release_id), None)
        if not selected or (args.action == "rollback" and not selected.rollback_allowed):
            raise ConsoleError("app_delivery_conflict", 409)
        kind, schema = "deployments", DeploymentRecord
        payload = {
            "installation_id": str(grant.installation_id),
            "release_id": str(args.release_id),
            "action": args.action,
            "expected_generation": context.installation.generation,
            "expected_release_id": str(context.installation.release_id)
            if context.installation.release_id
            else None,
        }
    identity_payload = {"installation_id": str(grant.installation_id), **payload}
    if args.retry_request_id:
        old = await api_request(settings, grant, f"/{kind}/{args.retry_request_id}")
        failed = checked_record(old, schema, grant, args.retry_request_id)
        if (
            failed["state"] != "failed"
            or (kind == "builds" and failed["source_revision"] != payload["source_revision"])
            or (
                kind == "deployments"
                and (failed["release_id"], failed["action"])
                != (payload["release_id"], payload["action"])
            )
        ):
            raise ConsoleError("app_delivery_conflict", 409)
        identity_payload["retry_of"] = str(args.retry_request_id)
    request_id = request_identity(task, kind, identity_payload)
    existing = await api_request(settings, grant, f"/{kind}/{request_id}", allow_missing=True)
    if existing is not None:
        return checked_record(existing, schema, grant, request_id)
    try:
        created = await api_request(
            settings, grant, f"/{kind}", body={"request_id": request_id, **payload}
        )
        return checked_record(created, schema, grant, request_id)
    except ConsoleError as error:
        if error.status != 503:
            raise
    except ValidationError:
        # A malformed successful response does not prove the request was rejected.
        # Retain its stable identity just as for a response lost in transport.
        pass
    return {
        "state": "unknown",
        "request_id": request_id,
        "next_action": "build_status" if kind == "builds" else "deployment_status",
    }


async def handle(runtime, message, *, generation=None):
    """Return whether this is our request; deny unknown/native child invocations."""
    if message.get("method") != "item/tool/call":
        return False
    params = message.get("params", {})
    result, success = {"error": "app_delivery_denied"}, False
    rpc = runtime.rpc
    if not rpc or (generation and generation != rpc.generation):
        return True
    try:
        from .rpc import REMOTE_CONTRACT

        Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallParams"]).validate(params)
        args = Arguments.model_validate(params.get("arguments"))
        if not runtime.remote_task_id:
            raise ConsoleError("app_delivery_denied", 403)
        async with runtime.task_gate(runtime.remote_task_id):
            with runtime.factory() as db:
                task = db.get(Task, runtime.remote_task_id)
                if (
                    params.get("tool") != TOOL_NAME
                    or not task
                    or task.thread_id != params.get("threadId")
                    or task.executor != runtime.executor
                    or task.runtime_generation != rpc.generation
                    or task.turn_id != params.get("turnId")
                    or task.status not in store.ACTIVE
                    or not (task.context or {}).get("installation_id")
                ):
                    raise ConsoleError("app_delivery_denied", 403)
                runtime.require_allowed_task(task)
                if args.action not in ("context", "build_status", "deployment_status") and (
                    not store.implementation_authorized(db, task)
                    or task.context.get("purpose") not in ("deployment", "recovery")
                ):
                    raise ConsoleError("app_delivery_denied", 403)
                db.expunge(task)
            result = await execute(runtime.settings, task, args)
        success = True
    except ConsoleError as error:
        result = {"error": error.code}
    except (ValidationError, SchemaError, ValueError, KeyError):
        result = {"error": "app_delivery_invalid_response"}
    if runtime.rpc is rpc and (not generation or generation == rpc.generation):
        response = {
            "contentItems": [{"type": "inputText", "text": json.dumps(result)}],
            "success": success,
        }
        Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallResponse"]).validate(response)
        await rpc.respond(message["id"], response)
    return True
