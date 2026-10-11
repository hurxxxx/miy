from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.domains.search import service as search_service
from miy_api.domains.search.backend_contracts import (
    KeywordSearchHit,
    KeywordSearchQuery,
    KeywordSearchResult,
)
from miy_api.domains.search.schemas import KeywordSearchRequest


def _request(*, entity_types: list[str] | None = None) -> KeywordSearchRequest:
    return KeywordSearchRequest(query="budget", entity_types=entity_types or [])


def _user():
    return SimpleNamespace(id="user-1")


def test_partitioned_keyword_query_uses_partition_then_source_acl_and_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition_id = "11111111-1111-1111-1111-111111111111"
    stale_row = {
        "retrieval_partition_id": partition_id,
        "entity_type": "file",
        "entity_id": "file-1",
        "title": "Company handbook",
        "summary": "Published handbook",
        "body": "company handbook",
        "keywords": "handbook",
        "source_updated_at": "2026-07-20T00:00:00Z",
        "created_at": "2026-07-20T00:00:00Z",
        "deep_link": "/apps/files?file=stale-id",
        "visibility": "private",
        "metadata": {},
    }

    class StagingClient:
        def index_exists(self) -> bool:
            return True

        def search(self, query: KeywordSearchQuery) -> KeywordSearchResult:
            assert query.retrieval_partition_ids == (partition_id,)
            assert query.acl_filter is None
            return KeywordSearchResult(hits=(KeywordSearchHit(document=stale_row, score=1.0),))

    class FakePolicy:
        def build_keyword_acl_filter(self):
            raise AssertionError("legacy backend ACL must not run for a partitioned generation")

        def authorize_many_resources(self, resources):
            return set(resources)

    monkeypatch.setattr(
        search_service,
        "resolve_company_enabled_app_ids",
        lambda db: ["files"],
    )
    monkeypatch.setattr(
        search_service.SourceAclPolicy,
        "for_user",
        staticmethod(lambda db, *, user: FakePolicy()),
    )
    monkeypatch.setattr(
        search_service,
        "_resolve_keyword_partition_ids",
        lambda *args, **kwargs: (partition_id,),
    )
    monkeypatch.setattr(
        search_service,
        "hydrate_file_search_rows_from_source",
        lambda db, *, rows: [
            {
                **rows[0],
                "deep_link": ("/apps/files?file=file-1"),
                "visibility": "company",
                "metadata": {
                    "access_scope_kind": "company",
                },
            }
        ],
    )

    response = search_service.query_keyword_search(
        SimpleNamespace(),
        user=_user(),
        request=_request(entity_types=["file"]),
        client=StagingClient(),
        evaluation_entity_types=("file",),
        partitioned_generation=True,
    )

    assert response.total == 1
    assert not hasattr(response.hits[0], "workspace_id")
    assert response.hits[0].visibility == "company"
    assert response.hits[0].deep_link == "/apps/files?file=file-1"
    assert response.hits[0].metadata["access_scope_kind"] == "company"
