"""Pure cross-product contract checks; Workbench itself does not import Core."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    "app_id": "normalization-test",
    "display": {"name": "메모 📋"},
    "source": {"repository": "https://example.test/normalization.git"},
}


@pytest.fixture
def contracts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps/api/src"))
    monkeypatch.syspath_prepend(str(ROOT / "apps/codex-console-api/src"))
    from codex_console.delivery_tools import normalize_manifest
    from jsonschema import Draft202012Validator
    from miy_api.domains.independent_apps.contracts import AppDefinition

    published = ROOT / "packages/contracts/independent-app.schema.json"
    packaged = ROOT / "apps/codex-console-api/src/codex_console/independent_app_schema.generated.json"
    assert published.read_bytes() == packaged.read_bytes()
    return AppDefinition, Draft202012Validator(json.loads(published.read_bytes())), normalize_manifest


@pytest.mark.parametrize("changes", [
    {},
    {"schema_version": 1},
    {"schema_version": 1.0},
    {"sdk_version": 1.0},
    {"schema_version": 1.0, "sdk_version": 1.0},
    {"entrypoints": {"ui": "/notes"}},
    {"runtime_profile": "web-api-postgres-v1",
     "requested_permissions": ["data:write", "identity:read", "data:read"]},
    {"runtime_profile": "web-api-postgres-v1",
     "requested_permissions": ["files:read-selected", "data:write", "identity:read", "data:read"]},
])
def test_core_schema_and_workbench_canonical_digests_agree(contracts, changes):
    core_type, schema, normalize = contracts
    manifest = {**copy.deepcopy(BASE), **changes}
    original = copy.deepcopy(manifest)
    schema.validate(manifest)
    normalized = normalize(manifest)
    core = core_type.model_validate(manifest)
    assert normalized == core.model_dump(mode="json")
    assert type(normalized["schema_version"]) is int
    assert type(normalized["sdk_version"]) is int
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    assert "sha256:" + hashlib.sha256(canonical.encode()).hexdigest() == core.content_digest()
    assert manifest == original


@pytest.mark.parametrize("field", ["schema_version", "sdk_version"])
@pytest.mark.parametrize("value", [True, False, "1", 1.5, 2])
def test_normalization_retains_published_schema_input_boundary(contracts, field, value):
    from jsonschema import ValidationError as SchemaError
    from pydantic import ValidationError as ModelError

    core_type, schema, normalize = contracts
    manifest = {**BASE, field: value}
    with pytest.raises(SchemaError):
        schema.validate(manifest)
    with pytest.raises(SchemaError):
        normalize(manifest)
    with pytest.raises(ModelError):
        core_type.model_validate(manifest)


@pytest.mark.parametrize("kind", ["register", "bootstrap"])
@pytest.mark.parametrize("field", ["schema_version", "sdk_version"])
@pytest.mark.parametrize("value", [1, 1.0, True, False, "1", 1.5, 2])
def test_registration_inputs_apply_the_same_version_contract(contracts, kind, field, value):
    from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput
    from miy_api.domains.independent_apps.contracts import RegisterDefinition
    from pydantic import ValidationError

    body = {"definition": {**BASE, field: value}, "source_revision": "a" * 40}
    model = RegisterDefinition
    if kind == "bootstrap":
        body.update(operation_id="bd064d73-27ed-4db2-a964-e634254d2d3b", origin="https://app.test")
        model = BootstrapInput
    if type(value) in (int, float) and value == 1:
        parsed = model.model_validate(body)
        assert type(getattr(parsed.definition, field)) is int
        assert parsed.definition.content_digest() == contracts[0].model_validate(BASE).content_digest()
    else:
        with pytest.raises(ValidationError):
            model.model_validate(body)
