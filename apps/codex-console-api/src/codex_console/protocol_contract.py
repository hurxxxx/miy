import json
import re
from hashlib import sha256
from pathlib import Path

VALIDATED_SCHEMA_NAMES = (
    "ThreadListParams",
    "ThreadReadParams",
    "SkillsListParams",
    "ThreadStartParams",
    "ThreadResumeParams",
    "TurnStartParams",
    "TurnSteerParams",
    "TurnInterruptParams",
    "ModelListParams",
    "CommandExecutionRequestApprovalResponse",
    "FileChangeRequestApprovalResponse",
    "ToolRequestUserInputResponse",
    "PermissionsRequestApprovalResponse",
)
COMPATIBILITY_SCHEMA_NAMES = (
    "ThreadListParams",
    "ThreadListResponse",
    "ThreadStartedNotification",
    "ThreadStatusChangedNotification",
    "TurnStartedNotification",
    "SkillsListParams",
    "SkillsListResponse",
    "InitializeParams",
    "InitializeResponse",
    "GetAccountParams",
    "GetAccountResponse",
    "NullableGetAccountRateLimitsParams",
    "GetAccountRateLimitsResponse",
    "ConfigReadParams",
    "ConfigReadResponse",
    "ModelListParams",
    "ModelListResponse",
    "ThreadStartParams",
    "ThreadStartResponse",
    "ThreadResumeParams",
    "ThreadResumeResponse",
    "ThreadReadParams",
    "ThreadReadResponse",
    "TurnStartParams",
    "TurnStartResponse",
    "TurnSteerParams",
    "TurnSteerResponse",
    "TurnInterruptParams",
    "TurnInterruptResponse",
    "ItemStartedNotification",
    "ItemCompletedNotification",
    "AgentMessageDeltaNotification",
    "PlanDeltaNotification",
    "CommandExecutionOutputDeltaNotification",
    "TurnPlanUpdatedNotification",
    "TurnCompletedNotification",
    "ServerRequestResolvedNotification",
    "CommandExecutionRequestApprovalParams",
    "CommandExecutionRequestApprovalResponse",
    "FileChangeRequestApprovalParams",
    "FileChangeRequestApprovalResponse",
    "ToolRequestUserInputParams",
    "ToolRequestUserInputResponse",
    "PermissionsRequestApprovalParams",
    "PermissionsRequestApprovalResponse",
    "McpServerElicitationRequestParams",
    "McpServerElicitationRequestResponse",
)
_STABLE_VERSION = re.compile(r"codex-cli (0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
REMOTE_SCHEMA_NAMES = (
    "EnvironmentAddParams",
    "EnvironmentAddResponse",
    "EnvironmentInfoParams",
    "EnvironmentInfoResponse",
    "EnvironmentStatusParams",
    "EnvironmentStatusResponse",
    "DynamicToolCallParams",
    "DynamicToolCallResponse",
)
HISTORY_SCHEMA_NAMES = (
    "ThreadTurnsListParams",
    "ThreadTurnsListResponse",
    "ThreadItemsListParams",
    "ThreadItemsListResponse",
)


def supports_contract_version(output: str, minimum: str) -> bool:
    installed = _STABLE_VERSION.fullmatch(output.strip())
    required = _STABLE_VERSION.fullmatch(f"codex-cli {minimum}")
    if not installed or not required:
        return False
    return tuple(map(int, installed.groups())) >= tuple(map(int, required.groups()))


def _read_schema(source: Path, name: str) -> dict:
    schema = json.loads(next(source.rglob(name + ".json")).read_text())
    definitions = schema.pop("definitions", {})
    used = {}

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref" and item.startswith("#/definitions/"):
                    reference = item.split("/")[-1]
                    if reference not in used:
                        used[reference] = definitions[reference]
                        visit(used[reference])
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    schema["definitions"] = used
    return schema


def _fingerprint(schema: dict) -> str:
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def build_contract(version: str, source: Path, *, include_compatibility_schemas=False) -> dict:
    schemas = {name: _read_schema(source, name) for name in COMPATIBILITY_SCHEMA_NAMES}
    result = {
        "codexVersion": version,
        "compatibilityHashes": {name: _fingerprint(schema) for name, schema in schemas.items()},
        "schemas": {name: schemas[name] for name in VALIDATED_SCHEMA_NAMES},
    }
    if include_compatibility_schemas:
        result["compatibilitySchemas"] = schemas
    return result


def render_contract(version: str, source: Path) -> str:
    rendered = json.dumps(
        build_contract(version, source), ensure_ascii=False, sort_keys=True, indent=2
    )
    return rendered + "\n"


_DOCUMENTATION_KEYS = frozenset({"description", "title", "$schema"})
_AUTHORITY_WORDS = ("approval", "permission", "sandbox")


def _wire_shape(value):
    """Documentation changes do not change the accepted wire values."""
    if isinstance(value, dict):
        return {
            k: _wire_shape(v)
            for k, v in value.items()
            if k not in _DOCUMENTATION_KEYS or not isinstance(v, str)
        }
    if isinstance(value, list):
        return [_wire_shape(v) for v in value]
    return value


def _compatible_extension(expected, actual, *, authority=False) -> bool:
    if authority:
        return _wire_shape(expected) == _wire_shape(actual)
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        expected, actual = _wire_shape(expected), _wire_shape(actual)
        if expected.keys() != actual.keys():
            return False
        for key, value in expected.items():
            candidate = actual[key]
            if key in ("properties", "definitions"):
                if not isinstance(candidate, dict) or not value.keys() <= candidate.keys():
                    return False
                if any(
                    any(word in name.lower() for word in _AUTHORITY_WORDS)
                    for name in candidate.keys() - value.keys()
                ):
                    return False
                for name, item in value.items():
                    locked = any(word in name.lower() for word in _AUTHORITY_WORDS)
                    if not _compatible_extension(item, candidate[name], authority=locked):
                        return False
            elif not _compatible_extension(value, candidate):
                return False
        return True
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(
            _compatible_extension(a, b) for a, b in zip(expected, actual, strict=True)
        )
    return expected == actual


def schemas_are_compatible(contract: dict, source: Path) -> bool:
    try:
        current = build_contract(
            contract["codexVersion"],
            source,
            include_compatibility_schemas="compatibilitySchemas" in contract,
        )
    except (json.JSONDecodeError, KeyError, OSError, StopIteration, TypeError):
        return False
    baseline = contract.get("compatibilitySchemas")
    if baseline is None:
        return current["compatibilityHashes"] == contract.get("compatibilityHashes")
    return all(
        name in baseline
        and _compatible_extension(
            baseline[name],
            current["compatibilitySchemas"][name],
            authority=any(word in name.lower() for word in _AUTHORITY_WORDS),
        )
        for name in COMPATIBILITY_SCHEMA_NAMES
    )


def build_remote_contract(version: str, source: Path) -> dict:
    schemas = {name: _read_schema(source, name) for name in REMOTE_SCHEMA_NAMES}
    return {
        "codexVersion": version,
        "compatibilityHashes": {name: _fingerprint(schema) for name, schema in schemas.items()},
        "schemas": schemas,
    }


def remote_schemas_are_compatible(contract: dict, source: Path) -> bool:
    try:
        current = build_remote_contract(contract["codexVersion"], source)
    except (json.JSONDecodeError, KeyError, OSError, StopIteration, TypeError):
        return False
    return current["compatibilityHashes"] == contract.get("compatibilityHashes")


def build_history_contract(version: str, source: Path) -> dict:
    schemas = {name: _read_schema(source, name) for name in HISTORY_SCHEMA_NAMES}
    return {
        "codexVersion": version,
        "compatibilityHashes": {name: _fingerprint(schema) for name, schema in schemas.items()},
        "schemas": schemas,
    }


def history_schemas_are_compatible(contract: dict, source: Path) -> bool:
    try:
        current = build_history_contract(contract["codexVersion"], source)
    except (json.JSONDecodeError, KeyError, OSError, StopIteration, TypeError):
        return False
    baseline = contract.get("schemas")
    if baseline is None:
        return current["compatibilityHashes"] == contract.get("compatibilityHashes")
    return all(
        name in baseline and _compatible_extension(baseline[name], current["schemas"][name])
        for name in HISTORY_SCHEMA_NAMES
    )
