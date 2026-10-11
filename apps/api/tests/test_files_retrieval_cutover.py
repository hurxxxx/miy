from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from miy_api.domains.retrieval.files_cutover import (
    FilesRetrievalCutoverError,
    check_files_retrieval_cutover,
)
from miy_api.domains.retrieval.models import RetrievalProjectionGeneration


_CHECKER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_files_retrieval_cutover.py"
)


def _load_checker_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "test_check_files_retrieval_cutover_script",
        _CHECKER_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ScalarRows:
    def __init__(self, rows: list[RetrievalProjectionGeneration]) -> None:
        self._rows = rows

    def all(self) -> list[RetrievalProjectionGeneration]:
        return list(self._rows)


class _GenerationSession:
    def __init__(self, rows: list[RetrievalProjectionGeneration]) -> None:
        self._rows = rows

    def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self._rows)


def test_files_retrieval_cutover_does_not_fallback_from_partial_active_pair() -> None:
    opensearch = RetrievalProjectionGeneration(
        id="opensearch-release_20260723",
        backend="opensearch",
        generation_key="release_20260723",
        physical_name="miy-test_keyword_search_documents_v3_release_20260723",
        alias_name="miy-test_keyword_search_documents",
        schema_version=3,
        state="active",
        validation_state="passed",
        validation_details={"release_cohort": "release_20260723"},
        validated_at=datetime(2026, 7, 23, 1, 0, 0),
    )

    with pytest.raises(FilesRetrievalCutoverError) as caught:
        check_files_retrieval_cutover(
            _GenerationSession([opensearch]),  # type: ignore[arg-type]
            settings=SimpleNamespace(files_retrieval_enabled=True),  # type: ignore[arg-type]
            qdrant_collection_exists=lambda *_args: pytest.fail(
                "partial active pair must not fall back to legacy backends"
            ),
        )

    assert caught.value.code == "runtime_missing_active_generation"
