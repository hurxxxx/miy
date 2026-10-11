"""Actual Source rows at final serving boundaries with synthetic backend/ACL."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, update

from test_files_current_retrieval import _EXTRACTED_AT, _candidate

from miy_api.domains.files import chat_retrieval
from miy_api.domains.files import search as files_search
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.search import service as search_service
from miy_api.domains.search.backend_contracts import KeywordSearchHit, KeywordSearchResult
from miy_api.domains.search.schemas import KeywordSearchRequest

pytest_plugins = ("test_files_current_retrieval",)


def _stub_ranked_candidates(monkeypatch, module, hits):
    monkeypatch.setattr(
        module,
        "query_retrieval",
        lambda *_args, **_kwargs: SimpleNamespace(
            hits=hits,
            trace_id="synthetic-current-content",
            latency_ms=0,
            profile=SimpleNamespace(
                backend_profiles={
                    "rerank": {
                        "applied": True,
                        "degraded": False,
                        "score_semantics": "normalized_relevance",
                    }
                }
            ),
        ),
    )


def _insert_backup(db, partition_id):
    second_id = str(uuid4())
    db.execute(
        insert(FileManagerFile.__table__).values(
            id=second_id,
            owner_id="synthetic-owner",
            filename="Backup.txt",
            content_type="text/plain",
            storage_key="synthetic-backup",
            size_bytes=16,
            visibility="company",
            retrieval_partition_id=partition_id,
            extraction_status="ready",
            extraction_content_checksum="a" * 64,
            extracted_at=_EXTRACTED_AT,
        )
    )
    db.commit()
    return second_id


def test_chat_drops_same_bytes_reextracted_during_source_hydration(current_file, monkeypatch):
    db, file_id, partition_id = current_file
    hit = _candidate(file_id, partition_id)
    hit.score = 0.8
    hit.methods = ["semantic", "cross_encoder"]
    _stub_ranked_candidates(monkeypatch, chat_retrieval, [hit])
    monkeypatch.setattr(
        chat_retrieval,
        "resolve_file_search_runtime",
        lambda _db: SimpleNamespace(
            keyword_client=None, rag_query_service=None, rag_collection=None
        ),
    )
    original = chat_retrieval._load_file_chat_sources

    def load_then_reextract(db, file_ids):
        result = original(db, file_ids)
        db.execute(
            update(FileManagerFile)
            .where(FileManagerFile.id == file_id)
            .values(
                extracted_at=datetime(2026, 10, 7, 10, 1, tzinfo=UTC),
                extraction_text="SYNTHETIC-NEW-OUTPUT-SAME-INPUT",
            )
        )
        db.commit()
        return result

    monkeypatch.setattr(chat_retrieval, "_load_file_chat_sources", load_then_reextract)
    result = chat_retrieval.query_file_chat_evidence(
        db, user=SimpleNamespace(id="synthetic-owner"), query="original"
    )
    assert result.items == ()


@pytest.mark.parametrize("changed_candidate", ["page", "off_page"])
def test_files_search_refills_and_counts_only_current_content(
    current_file, monkeypatch, changed_candidate
):
    db, file_id, partition_id = current_file
    second_id = _insert_backup(db, partition_id)
    hits = [_candidate(file_id, partition_id), _candidate(second_id, partition_id)]
    for index, hit in enumerate(hits):
        hit.score = 0.8 - index * 0.1
        hit.methods = ["semantic", "cross_encoder"]
    _stub_ranked_candidates(monkeypatch, files_search, hits)
    original = files_search._load_file_search_sources
    loads = 0

    def load_then_invalidate_page(db, file_ids, *, request):
        nonlocal loads
        result = original(db, file_ids, request=request)
        loads += 1
        if loads == 2:
            changed_id = file_id if changed_candidate == "page" else second_id
            db.execute(
                update(FileManagerFile)
                .where(FileManagerFile.id == changed_id)
                .values(extraction_status="pending", extraction_content_checksum=None)
            )
            db.commit()
        return result

    monkeypatch.setattr(files_search, "_load_file_search_sources", load_then_invalidate_page)
    result = files_search.query_files(
        db,
        user=SimpleNamespace(id="synthetic-owner"),
        request=files_search.FileSearchRequest(query="original", strategy="semantic", page_size=1),
        runtime=files_search.FileSearchRuntime(
            keyword_client=None, rag_query_service=None, rag_collection=None
        ),
    )
    expected_id = second_id if changed_candidate == "page" else file_id
    assert [hit.file_id for hit in result.hits] == [expected_id]
    assert result.has_more is False
    assert loads >= 2


def test_keyword_refills_past_stale_content_before_counting_candidates(current_file):
    db, file_id, partition_id = current_file
    second_id = _insert_backup(db, partition_id)
    current_row = {
        "entity_type": "file",
        "entity_id": second_id,
        "title": "Synthetic",
        "body": "original",
        "retrieval_partition_id": partition_id,
        "metadata": dict(_candidate(second_id, partition_id).metadata),
    }
    stale_row = {
        **current_row,
        "entity_id": file_id,
        "metadata": {**current_row["metadata"], "content_checksum": "b" * 64},
    }

    class CandidateIndex:
        def __init__(self):
            self.queries = []
            self.closed = []

        def open_point_in_time(self, *, keep_alive):
            return "synthetic-pit"

        def close_point_in_time(self, pit):
            self.closed.append(pit)

        def search(self, query):
            self.queries.append(query)
            row = stale_row if not query.search_after else current_row
            return KeywordSearchResult(
                hits=(KeywordSearchHit(document=row, score=1.0, sort_values=(len(self.queries),)),)
            )

    class AllowSource:
        def authorize_many_resources(self, resources):
            return set(resources)

    client = CandidateIndex()
    rows = search_service._load_authorized_ranked_candidates(
        db,
        acl_filter=None,
        policy=AllowSource(),
        allowed_entity_types=frozenset({"file"}),
        request=KeywordSearchRequest(query="original", limit=1),
        backend_timeout_seconds=None,
        client=client,
        text_operator="and",
        text_minimum_should_match=None,
        size=1,
    )
    assert [row["entity_id"] for row in rows] == [second_id]
    assert rows[0]["metadata"]["content_checksum"] == "a" * 64
    assert len(client.queries) == 2
    assert client.queries[1].search_after == (1,)
    assert client.closed == ["synthetic-pit"]
