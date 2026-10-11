"""Actual Source rows at final serving boundaries with synthetic backend/ACL."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, update

from test_files_current_retrieval import _EXTRACTED_AT as _EXTRACTED_AT, _candidate as _candidate

from miy_api.domains.files import search as files_search
from miy_api.domains.files.models import FileManagerFile

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


@pytest.mark.parametrize("changed_candidate", ["page"])
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
