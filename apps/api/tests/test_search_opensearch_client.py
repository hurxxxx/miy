from __future__ import annotations

from typing import Any

import pytest

from miy_api.domains.search.backend_contracts import KeywordSearchQuery
from miy_api.domains.search.opensearch import (
    OpenSearchError,
    OpenSearchKeywordClient,
)
from miy_api.domains.search.index_gateway import (
    keyword_search_versioned_index_name,
)


class _Response:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> None:
        self._payload = payload or {}
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class RecordingKeywordClient(OpenSearchKeywordClient):
    def __init__(self) -> None:
        super().__init__(base_url="http://opensearch", index_prefix="test")
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> _Response:
        self.calls.append((method, path, kwargs))
        if method == "HEAD":
            return _Response({})
        return _Response({"errors": False})

    def _bulk_index_documents(self, documents: list[dict[str, Any]]) -> None:
        self.calls.append(("BULK", self.index_name, {"documents": documents}))


class ScriptedKeywordClient(OpenSearchKeywordClient):
    def __init__(
        self,
        *,
        existing_indices: set[str],
        target_index_name: str | None = None,
        alias_payload: dict[str, Any] | None = None,
        document_count: int = 0,
        schema_version: int = 2,
    ) -> None:
        super().__init__(
            base_url="http://opensearch",
            index_prefix="test",
            target_index_name=target_index_name,
        )
        self.existing_indices = existing_indices
        self.alias_payload = alias_payload or {}
        self.document_count = document_count
        self.schema_version = schema_version
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> _Response:
        self.calls.append((method, path, kwargs))
        if method == "HEAD":
            index_name = path.removeprefix("/")
            return _Response(status_code=200 if index_name in self.existing_indices else 404)
        if method == "GET" and path.startswith("/_alias/"):
            return _Response(
                self.alias_payload,
                status_code=200 if self.alias_payload else 404,
            )
        if method == "GET" and path.endswith("/_mapping"):
            return _Response(
                {self.index_name: {"mappings": {"_meta": {"schema_version": self.schema_version}}}}
            )
        if method == "GET" and path.endswith("/_count"):
            return _Response({"count": self.document_count})
        if method == "GET" and path == f"/{self.index_name}":
            return _Response(
                {
                    self.index_name: {
                        "settings": {
                            "index": {
                                "uuid": "uuid-1",
                                "creation_date": "1",
                                "provided_name": self.index_name,
                                "number_of_shards": "1",
                            }
                        },
                        "mappings": {"_meta": {"schema_version": self.schema_version}},
                    }
                }
            )
        return _Response({"errors": False})


def _document(entity_id: str, body: str) -> dict:
    return {
        "entity_type": "plugin_chunk",
        "entity_id": entity_id,
        "title": entity_id,
        "summary": "",
        "body": body,
    }


def _partitioned_document(
    entity_id: str,
    *,
    partition_id: str = "a3b6638a-7547-45f8-81f2-973bfa6080d6",
    projection_version: int = 7,
) -> dict[str, Any]:
    return {
        **_document(entity_id, "heater"),
        "resource_type": "file_manager_file",
        "retrieval_partition_id": partition_id,
        "projection_version": projection_version,
    }


def test_versioned_index_activation_rejects_recreated_physical_index() -> None:
    target = keyword_search_versioned_index_name("test", generation="release_20260721")
    client = ScriptedKeywordClient(existing_indices={target}, target_index_name=target)

    with pytest.raises(OpenSearchError, match="identity changed"):
        client.activate_versioned_index(
            writes_quiesced=True,
            expected_index_uuid="previous-uuid",
        )

    assert not any(path == "/_aliases" for _, path, _ in client.calls)


def test_partitioned_v3_operations_reject_a_changed_live_index_target() -> None:
    client = RecordingKeywordClient().for_partitioned_rebuild(generation="partition_20260722")
    document = _partitioned_document("file-1")
    client.index_name = client.index_alias
    client._request = lambda *args, **kwargs: pytest.fail(  # type: ignore[method-assign]
        "index binding validation must happen before an OpenSearch request"
    )

    operations = (
        client.ensure_index,
        lambda: client.upsert_partitioned_document(document),
        lambda: client.delete_partitioned_document(
            resource_type="file_manager_file",
            resource_id="file-1",
            projection_version=8,
        ),
        lambda: client.bulk_index_partitioned_documents([document]),
        lambda: client.search(
            KeywordSearchQuery(
                retrieval_partition_ids=("a3b6638a-7547-45f8-81f2-973bfa6080d6",),
            )
        ),
        client.index_exists,
        client.open_point_in_time,
    )

    for operation in operations:
        with pytest.raises(OpenSearchError, match="bound to physical index"):
            operation()


def test_partitioned_upsert_after_newer_tombstone_is_superseded() -> None:
    client = RecordingKeywordClient().for_partitioned_rebuild(generation="partition_20260722")
    client.ensure_index = lambda: None  # type: ignore[method-assign]

    def request(method: str, path: str, **kwargs: Any) -> _Response:
        del path, kwargs
        if method == "PUT":
            return _Response({}, status_code=409)
        assert method == "GET"
        # OpenSearch retains the higher external version in its delete
        # tombstone, but a realtime GET only reports that the document is gone.
        return _Response({"found": False}, status_code=404)

    client._request = request  # type: ignore[method-assign]

    assert client.upsert_partitioned_document(_partitioned_document("file-1")) == "superseded"
