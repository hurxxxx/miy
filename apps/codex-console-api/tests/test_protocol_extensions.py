import json

import pytest

from codex_console.protocol_contract import (
    COMPATIBILITY_SCHEMA_NAMES,
    build_contract,
    schemas_are_compatible,
)


@pytest.mark.parametrize(
    ("change", "accepted"),
    [
        ("documentation", True),
        ("optional-field", True),
        ("required-field", False),
        ("title-type", False),
        ("removed-field", False),
        ("permissions-field", False),
        ("sandbox-policy", False),
        ("approval-extension", False),
        ("new-authority-field", False),
    ],
)
def test_extensions_preserve_request_and_authority_boundaries(tmp_path, change, accepted):
    schema = {
        "type": "object",
        "description": "Original documentation",
        "properties": {
            "title": {"type": "string"},
            "permissions": {"$ref": "#/definitions/Permissions"},
            "sandboxPolicy": {"type": "string", "enum": ["readOnly"]},
        },
        "definitions": {
            "Permissions": {
                "type": "object",
                "properties": {"network": {"type": "boolean"}},
                "additionalProperties": False,
            }
        },
    }
    for name in COMPATIBILITY_SCHEMA_NAMES:
        (tmp_path / (name + ".json")).write_text(json.dumps(schema))
    contract = build_contract("0.162.1", tmp_path, include_compatibility_schemas=True)
    name = "TurnStartParams"
    changed = json.loads(json.dumps(schema))
    if change == "documentation":
        changed["description"] = "Updated documentation"
        changed["properties"]["title"]["description"] = "New explanatory text"
    elif change in ("optional-field", "required-field", "approval-extension"):
        changed["properties"]["newField"] = {"type": "string"}
        if change == "required-field":
            changed["required"] = ["newField"]
        if change == "approval-extension":
            name = "PermissionsRequestApprovalResponse"
    elif change == "new-authority-field":
        changed["properties"]["sandboxOverride"] = {"type": "boolean"}
    elif change == "title-type":
        changed["properties"]["title"]["type"] = "number"
    elif change == "removed-field":
        del changed["properties"]["title"]
    elif change == "permissions-field":
        changed["definitions"]["Permissions"]["properties"]["write"] = {"type": "boolean"}
    elif change == "sandbox-policy":
        changed["properties"]["sandboxPolicy"]["enum"].append("dangerFullAccess")
    (tmp_path / (name + ".json")).write_text(json.dumps(changed))
    assert schemas_are_compatible(contract, tmp_path) is accepted
