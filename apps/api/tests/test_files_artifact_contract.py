"""Public raw artifact and cold-import boundaries shared by Source and Core."""

import json
import subprocess
import sys
from pathlib import Path


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
