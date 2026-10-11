from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


_API_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_model_registration_excludes_retired_knowledge_tables() -> None:
    script = """
import json
import sys

sys.path.insert(0, "src")

from miy_api.core.db import Base
from miy_api.core.model_registry import import_all_models

import_all_models()
retired = {
    "knowledge_connectors",
    "knowledge_document_artifacts",
    "knowledge_ingest_jobs",
    "knowledge_source_documents",
}
print(json.dumps({
    "tables": sorted(retired.intersection(Base.metadata.tables)),
    "knowledge_model_modules": sorted(
        name
        for name in sys.modules
        if name == "miy_api.domains.knowledge.models"
        or name.startswith("miy_api.domains.knowledge.models.")
    ),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        cwd=_API_ROOT,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "knowledge_model_modules": [],
        "tables": [],
    }
