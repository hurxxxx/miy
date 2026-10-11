from __future__ import annotations

import warnings
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from miy_api.domains.rag.contracts import (
    RagDeleteRequest,
    RagProjection,
    RagQueryRequest,
    RagUpsertRequest,
    RagVectorRecord,
    RagVectorSearchRequest,
)
from miy_api.domains.rag.providers import RagProviderConfigurationError
from miy_api.domains.rag.providers.fake import FakeEmbeddingClient
from miy_api.domains.rag.providers.openai_compatible import (
    _clear_inference_gateway_health_cache,
)
from miy_api.domains.rag.providers.qdrant import QdrantVectorIndexClient
from miy_api.domains.rag.query_service import RagQueryService
from miy_api.domains.rag.service import RagService

pytestmark = pytest.mark.filterwarnings(
    "ignore:Payload indexes have no effect in the local Qdrant.*"
)


@pytest.fixture(autouse=True)
def clear_inference_gateway_health_cache():
    _clear_inference_gateway_health_cache()
    yield
    _clear_inference_gateway_health_cache()


@pytest.fixture
def qdrant_client(tmp_path):
    with warnings.catch_warnings():
        return QdrantClient(path=str(tmp_path / "qdrant-local"))


@pytest.mark.slow
def test_qdrant_vector_index_smoke_syncs_queries_and_deletes(qdrant_client) -> None:
    vector_index = QdrantVectorIndexClient(client=qdrant_client)
    embedding_client = FakeEmbeddingClient()
    rag_service = RagService(
        vector_index=vector_index,
        embedding_client=embedding_client,
    )
    query_service = RagQueryService(
        vector_index=vector_index,
        embedding_client=embedding_client,
    )

    projection = RagProjection(
        resource_type="doc",
        resource_id="doc-1",
        source_kind="docs",
        title="Budget Review",
        summary="Qdrant hybrid retrieval smoke",
        text_content="Budget risk increased after service repricing and approval lag.",
        owner_label="Owner A",
        visibility_refs=["company_public", "owner:user-1"],
        metadata={"team_id": "team-1", "origin_ref": "docs:doc-1"},
    )

    sync_result = rag_service.sync_projection(projection, collection="rag-qdrant-smoke")
    collection = qdrant_client.get_collection("rag-qdrant-smoke")

    assert sync_result.chunk_count >= 1
    assert "dense" in collection.config.params.vectors
    assert "sparse" in (collection.config.params.sparse_vectors or {})

    response = query_service.query(
        RagQueryRequest(
            collection="rag-qdrant-smoke",
            query="budget approval risk",
            source_kinds=["docs"],
            filters={
                "visibility_refs_contains": "owner:user-1",
                "team_id": "team-1",
            },
        )
    )

    assert response.hits
    assert response.hits[0].resource_id == "doc-1"
    assert response.hits[0].resource_type == "doc"
    assert not hasattr(response.hits[0], "workspace_id")
    assert response.hits[0].metadata["resource_id"] == "doc-1"

    delete_result = rag_service.delete_projection(
        resource_type="doc",
        resource_id="doc-1",
        collection="rag-qdrant-smoke",
    )
    after_delete = query_service.query(
        RagQueryRequest(
            collection="rag-qdrant-smoke",
            query="budget approval risk",
            source_kinds=["docs"],
        )
    )

    assert delete_result.deleted_count >= 1
    assert after_delete.hits == []
    assert rag_service.delete_collection(collection="rag-qdrant-smoke") is True
    assert qdrant_client.collection_exists("rag-qdrant-smoke") is False


def test_partitioned_generation_rejects_operations_outside_bound_collection() -> None:
    bound_collection = "rag-partitioned-generation-v2"
    wrong_collection = "rag-default-generation"
    partition_id = "11111111-1111-1111-1111-111111111111"
    projection = RagProjection(
        retrieval_partition_id=partition_id,
        projection_version=1,
        resource_type="doc",
        resource_id="doc-1",
        source_kind="docs",
    )
    record = RagVectorRecord(
        chunk_id="chunk-0",
        text="partitioned content",
        embedding=[0.1, 0.2],
        projection=projection,
    )
    upsert_request = RagUpsertRequest(
        collection=wrong_collection,
        projection=projection,
        chunks=[],
    )
    delete_request = RagDeleteRequest(
        collection=wrong_collection,
        retrieval_partition_id=partition_id,
        resource_type="doc",
        resource_id="doc-1",
    )
    query_request = RagVectorSearchRequest(
        collection=wrong_collection,
        query="partitioned query",
        query_embedding=[0.1, 0.2],
        retrieval_partition_ids=[partition_id],
    )
    vector_index = QdrantVectorIndexClient(
        client=object(),
        partitioned_generation=True,
        generation_collection=bound_collection,
    )

    operations = (
        lambda: vector_index.ensure_collection(
            collection=wrong_collection,
            dense_dimensions=2,
        ),
        lambda: vector_index.upsert_chunks(request=upsert_request, records=[record]),
        lambda: vector_index.query(request=query_request),
        lambda: vector_index.delete_resource(request=delete_request),
        lambda: vector_index.delete_chunks_at_or_after(
            request=delete_request,
            chunk_index=1,
        ),
        lambda: vector_index.delete_collection(collection=wrong_collection),
    )

    for operation in operations:
        with pytest.raises(RagProviderConfigurationError, match="bound to collection"):
            operation()


def test_partitioned_query_and_deletes_require_partition_ids() -> None:
    collection = "rag-partitioned-generation-v2"
    vector_index = QdrantVectorIndexClient(
        client=object(),
        partitioned_generation=True,
        generation_collection=collection,
    )

    with pytest.raises(RagProviderConfigurationError, match="retrieval_partition_ids"):
        vector_index.query(
            request=RagVectorSearchRequest(
                collection=collection,
                query="missing partition filter",
                query_embedding=[],
            )
        )

    delete_request = RagDeleteRequest(
        collection=collection,
        resource_type="doc",
        resource_id="doc-1",
    )
    for delete_operation in (
        lambda: vector_index.delete_resource(request=delete_request),
        lambda: vector_index.delete_chunks_at_or_after(
            request=delete_request,
            chunk_index=1,
        ),
    ):
        with pytest.raises(RagProviderConfigurationError, match="retrieval_partition_id"):
            delete_operation()


def test_qdrant_vector_index_detects_existing_dense_dimension_mismatch(qdrant_client) -> None:
    vector_index = QdrantVectorIndexClient(client=qdrant_client)

    vector_index.ensure_collection(
        collection="rag-qdrant-mismatch",
        dense_dimensions=8,
        sparse_enabled=True,
    )

    with pytest.raises(RagProviderConfigurationError, match="dense vector size mismatch"):
        vector_index.ensure_collection(
            collection="rag-qdrant-mismatch",
            dense_dimensions=16,
            sparse_enabled=True,
        )


def _partitioned_v1_payload_schema() -> dict[str, dict[str, str]]:
    return {
        "retrieval_partition_id": {"data_type": "keyword"},
        "projection_version": {"data_type": "integer"},
        "scope_kind": {"data_type": "keyword"},
        "resource_type": {"data_type": "keyword"},
        "resource_id": {"data_type": "keyword"},
        "source_kind": {"data_type": "keyword"},
        "visibility_refs": {"data_type": "keyword"},
    }


class _ExistingPartitionedCollectionClient:
    def __init__(self, payload_schema: dict[str, dict[str, str]]) -> None:
        self.payload_schema = payload_schema
        self.index_calls: list[str] = []

    def collection_exists(self, *, collection_name: str) -> bool:
        del collection_name
        return True

    def get_collection(self, *, collection_name: str) -> object:
        del collection_name
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={"dense": SimpleNamespace(size=8)},
                    sparse_vectors={"sparse": object()},
                )
            ),
            payload_schema=self.payload_schema,
        )

    def create_payload_index(self, *, field_name: str, **_kwargs: object) -> None:
        self.index_calls.append(field_name)
