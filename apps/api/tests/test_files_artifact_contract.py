"""Public raw artifact and cold-import boundaries shared by Source and Core."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from miy_api.domains.files import artifact_contract


def raw_artifact():
    return {
        "file_id": "contract-file",
        "content_checksum": "a" * 64,
        "text": "Canonical local extraction evidence.",
        "blocks": [
            {
                "document_id": "contract-file",
                "block_id": "contract-file:text:1",
                "locator_kind": "document",
                "locator_label": "Document",
                "section_path": "Body",
                "block_kind": "text",
                "text": "Canonical local extraction evidence.",
                "rows": [],
            }
        ],
        "metadata": {"parser": "plain_text", "parser_version": "files-retrieval-v2"},
    }


def test_raw_source_fields_validate_without_file_model():
    raw = raw_artifact()
    actual = artifact_contract.validate_file_extraction_artifact(**raw)
    assert type(actual) is artifact_contract.FileExtractionArtifact
    assert actual.content_checksum == raw["content_checksum"]
    assert actual.text == raw["text"]
    assert [block.to_dict() for block in actual.blocks] == raw["blocks"]
    assert actual.metadata == raw["metadata"]


@pytest.mark.parametrize("key", ["content_checksum", "author"])
def test_raw_metadata_cannot_override_source_or_external_authority(key):
    raw = raw_artifact()
    raw["metadata"][key] = "untrusted override"
    with pytest.raises(artifact_contract.FileArtifactInvalid) as caught:
        artifact_contract.validate_file_extraction_artifact(**raw)
    assert caught.value.reason == "metadata_reserved_key"
    assert str(caught.value) == "file_artifact_invalid"


@pytest.mark.parametrize("bad_value", [float("nan"), object(), "\ud800"])
def test_public_raw_metadata_rejects_nonfinite_nonjson_and_invalid_utf8(bad_value):
    raw = raw_artifact()
    raw["metadata"]["format_value"] = bad_value
    with pytest.raises(artifact_contract.FileArtifactInvalid):
        artifact_contract.validate_file_extraction_artifact(**raw)


def test_raw_block_identity_cannot_cross_source_file():
    raw = raw_artifact()
    raw["blocks"][0]["document_id"] = "another-file"
    with pytest.raises(artifact_contract.FileArtifactInvalid) as caught:
        artifact_contract.validate_file_extraction_artifact(**raw)
    assert caught.value.reason == "artifact_block_identity_invalid"


def test_whole_serialized_artifact_is_bounded_even_when_each_field_is_valid():
    raw = raw_artifact()
    original = raw["blocks"][0]
    raw["blocks"] = [
        {
            **original,
            "block_id": f"contract-file:text:{index}",
            "text": "Evidence",
            "locator_label": "x" * artifact_contract.MAX_FILE_ARTIFACT_FIELD_CHARS,
            "section_path": "y" * artifact_contract.MAX_FILE_ARTIFACT_FIELD_CHARS,
        }
        for index in range(600)
    ]
    with pytest.raises(artifact_contract.FileArtifactInvalid) as caught:
        artifact_contract.validate_file_extraction_artifact(**raw)
    assert caught.value.reason == "artifact_budget_exceeded"


def test_legacy_and_core_names_reexport_the_same_contract_objects():
    from miy_api.domains.files import core_projection, external_projection, rag_projection

    assert rag_projection.FileExtractionArtifact is artifact_contract.FileExtractionArtifact
    assert core_projection.FileExtractionArtifact is artifact_contract.FileExtractionArtifact
    assert (
        rag_projection.MAX_FILES_RAG_EXTRACTED_CHARS
        == artifact_contract.MAX_FILES_RAG_EXTRACTED_CHARS
    )
    assert (
        external_projection.EXTERNAL_SOURCE_SAFE_METADATA_KEYS
        is artifact_contract.EXTERNAL_SOURCE_SAFE_METADATA_KEYS
    )
    for name in (
        "FileArtifactControlError",
        "FileArtifactNotReady",
        "FileArtifactInvalid",
        "FileArtifactChecksumMismatch",
    ):
        assert getattr(core_projection, name) is getattr(artifact_contract, name)


def test_actual_cold_import_and_validation_cannot_reach_runtime_or_environment(tmp_path):
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = r"""
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
forbidden = (
    "sqlalchemy", "pydantic_settings", "dotenv", "miy_api.core",
    "miy_api.domains.auth", "miy_api.domains.retrieval", "miy_api.domains.rag",
    "miy_api.domains.files.core_projection", "miy_api.domains.files.rag_projection",
    "miy_api.domains.files.external_projection", "miy_api.domains.files.models",
    "miy_api.domains.files.storage", "miy_api.domains.files.retrieval_contract",
)
def deny_runtime(event, args):
    if event == "import" and any(args[0].startswith(prefix) for prefix in forbidden):
        raise AssertionError("cold artifact contract reached a runtime dependency")
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        name = pathlib.Path(os.fsdecode(args[0])).name
        if name == ".env" or name.startswith(".env."):
            raise AssertionError("cold artifact contract opened an environment file")
sys.addaudithook(deny_runtime)
from miy_api.domains.files.artifact_contract import validate_file_extraction_artifact
raw = json.loads(sys.argv[2])
artifact = validate_file_extraction_artifact(**raw)
assert artifact.text == raw["text"]
assert not any(name.startswith(forbidden) for name in sys.modules)
print(json.dumps({"cold_pure_import": True, "actual_validation": True}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source_root), json.dumps(raw_artifact())],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"cold_pure_import": True, "actual_validation": True}
