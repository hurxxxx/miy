from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from miy_api.domains.rag.runtime import (
    PARTITIONED_RAG_GENERATION_SCHEMA_VERSION,
    resolve_default_collection_name,
    resolve_partitioned_rag_collection_alias,
    resolve_partitioned_rag_collection_name,
)
from miy_api.domains.retrieval.models import RetrievalProjectionGeneration
from miy_api.domains.retrieval.runtime_binding import (
    PartitionedRetrievalRuntimeUnavailable,
    resolve_active_partitioned_generation_pair,
    resolve_partitioned_files_query_runtime,
)
from miy_api.domains.search.index_gateway import (
    RETRIEVAL_PARTITIONED_INDEX_SCHEMA_VERSION,
    keyword_search_index_alias,
    keyword_search_partitioned_index_alias,
    keyword_search_partitioned_index_name,
)


_COHORT = "release_20260723"


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "keyword_search_backend": "opensearch",
        "opensearch_url": "http://search.internal:9200/",
        "opensearch_index_prefix": "miy-test",
        "rag_vector_index_provider": "qdrant",
        "rag_qdrant_collection_prefix": "miy-test-rag",
        "rag_embedding_provider": "fake",
        "rag_local_embedding_model": "unused-for-fake",
        "rag_query_timeout_ms": 5_000,
        "rag_rerank_candidate_k": 80,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _generation(
    *,
    backend: str,
    settings: SimpleNamespace,
    cohort: str = _COHORT,
    schema_version: int | None = None,
    validation_state: str = "passed",
    alias_name: str | None = None,
    physical_name: str | None = None,
) -> RetrievalProjectionGeneration:
    if backend == "opensearch":
        resolved_schema_version = (
            RETRIEVAL_PARTITIONED_INDEX_SCHEMA_VERSION if schema_version is None else schema_version
        )
        resolved_alias_name = alias_name or keyword_search_partitioned_index_alias(
            settings.opensearch_index_prefix
        )
        resolved_physical_name = physical_name or keyword_search_partitioned_index_name(
            settings.opensearch_index_prefix,
            generation=cohort,
        )
    else:
        resolved_schema_version = (
            PARTITIONED_RAG_GENERATION_SCHEMA_VERSION if schema_version is None else schema_version
        )
        resolved_alias_name = alias_name or resolve_partitioned_rag_collection_alias(settings)
        resolved_physical_name = physical_name or resolve_partitioned_rag_collection_name(
            settings,
            generation=cohort,
        )
    return RetrievalProjectionGeneration(
        id=f"{backend}-{cohort}-{resolved_schema_version}",
        backend=backend,
        generation_key=cohort,
        physical_name=resolved_physical_name,
        alias_name=resolved_alias_name,
        schema_version=resolved_schema_version,
        state="active",
        baseline_event_sequence=7,
        replay_event_sequence=7,
        validation_state=validation_state,
        validation_details={
            "release_cohort": cohort,
            "included_resource_types": ["file_manager_file"],
        },
        validated_at=datetime(2026, 7, 23, 1, 0, 0),
    )


class _ScalarRows:
    def __init__(self, rows: list[RetrievalProjectionGeneration]) -> None:
        self._rows = rows

    def all(self) -> list[RetrievalProjectionGeneration]:
        return list(self._rows)


class _GenerationSession:
    def __init__(self, rows: list[RetrievalProjectionGeneration]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    def scalars(self, statement: object) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self._rows)


def test_partitioned_runtime_rejects_legacy_shared_aliases() -> None:
    settings = _settings()
    rows = [
        _generation(
            backend="opensearch",
            settings=settings,
            alias_name=keyword_search_index_alias(settings.opensearch_index_prefix),
        ),
        _generation(
            backend="qdrant",
            settings=settings,
            alias_name=resolve_default_collection_name(settings),
        ),
    ]

    with pytest.raises(PartitionedRetrievalRuntimeUnavailable) as caught:
        resolve_active_partitioned_generation_pair(
            _GenerationSession(rows),  # type: ignore[arg-type]
            settings=settings,
        )

    assert caught.value.reason == "alias_identity_mismatch"


@pytest.mark.parametrize(
    ("opensearch_overrides", "qdrant_overrides", "reason"),
    [
        ({"schema_version": 2}, {}, "schema_version_mismatch"),
        ({}, {"cohort": "release_other"}, "release_cohort_mismatch"),
    ],
)
def test_partitioned_runtime_fails_closed_on_validation_schema_or_identity_drift(
    opensearch_overrides: dict[str, object],
    qdrant_overrides: dict[str, object],
    reason: str,
) -> None:
    settings = _settings()
    rows = [
        _generation(backend="opensearch", settings=settings, **opensearch_overrides),
        _generation(backend="qdrant", settings=settings, **qdrant_overrides),
    ]

    with pytest.raises(PartitionedRetrievalRuntimeUnavailable) as caught:
        resolve_partitioned_files_query_runtime(
            _GenerationSession(rows),  # type: ignore[arg-type]
            settings=settings,
            rag_providers=object(),  # type: ignore[arg-type]
        )

    assert caught.value.reason == reason
