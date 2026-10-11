from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from dev_accounts import auth_headers, dev_login

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import User
from miy_api.domains.files import chat_retrieval
from miy_api.domains.files import service as files_service
from miy_api.domains.files.current_content import file_extraction_result_marker
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.files.search import FileSearchRuntime
from miy_api.domains.retrieval.contracts import RetrievalHit
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE


def test_file_chat_evidence_rechecks_acl_after_hydration(
    client: TestClient,
    in_memory_object_storage: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _upload_company_file(
        client,
        corpus_name="Concurrent chat evidence revoke",
        filename="revoked-evidence.txt",
    )
    _stub_retrieval(
        monkeypatch,
        hits=[
            _retrieval_hit(
                file_id=uploaded["id"],
                content_witness=uploaded["content_witness"],
                filename="revoked-evidence.txt",
                excerpt="CONCURRENT-REVOKE-SECRET",
            )
        ],
    )
    original_loader = chat_retrieval._load_file_chat_sources
    revoke_triggered = False

    def _load_then_revoke(db, file_ids):
        nonlocal revoke_triggered
        sources = original_loader(db, file_ids)
        with get_session_factory().begin() as revoke_db:
            user = revoke_db.scalar(select(User).where(User.login_id == "administrator"))
            assert user is not None
            files_service.delete_file(
                revoke_db,
                user=user,
                file_id=uploaded["id"],
            )
        revoke_triggered = True
        return sources

    monkeypatch.setattr(
        chat_retrieval,
        "_load_file_chat_sources",
        _load_then_revoke,
    )

    with get_session_factory()() as db:
        user = db.scalar(select(User).where(User.login_id == "administrator"))
        assert user is not None
        result = chat_retrieval.query_file_chat_evidence(
            db,
            user=user,
            query="revoked evidence",
        )

    assert revoke_triggered is True
    assert result.items == ()


def _upload_company_file(
    client: TestClient,
    *,
    corpus_name: str,
    filename: str,
) -> dict[str, object]:
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    corpus_response = client.post(
        "/api/v1/files/corpora",
        headers=headers,
        json={"name": corpus_name},
    )
    assert corpus_response.status_code == 201, corpus_response.text
    corpus = corpus_response.json()
    upload_response = client.post(
        "/api/v1/files/upload",
        headers=headers,
        data={
            "visibility": "company",
            "company_admin_read_acknowledged": True,
            "corpus_id": corpus["id"],
        },
        files={"file": (filename, b"source", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    uploaded = upload_response.json()
    # This retrieval fixture represents a previously indexed ready Source
    # result; retain its content envelope at candidate creation, not response.
    with get_session_factory().begin() as db:
        file = db.get(FileManagerFile, uploaded["id"])
        assert file is not None
        file.extraction_status = "ready"
        file.extraction_content_checksum = "a" * 64
        file.extracted_at = datetime(2026, 10, 7, 10, tzinfo=UTC)
        uploaded["content_witness"] = {
            "content_checksum": file.extraction_content_checksum,
            "retrieval_partition_id": str(file.retrieval_partition_id),
            "extracted_at": file_extraction_result_marker(file.extracted_at),
        }
    return uploaded


def _stub_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hits: list[RetrievalHit],
) -> None:
    monkeypatch.setattr(
        chat_retrieval,
        "resolve_file_search_runtime",
        lambda _db: FileSearchRuntime(
            keyword_client=object(),  # type: ignore[arg-type]
            rag_query_service=object(),  # type: ignore[arg-type]
            rag_collection="files-v1-active",
        ),
    )
    monkeypatch.setattr(
        chat_retrieval,
        "query_retrieval",
        lambda _db, **_kwargs: SimpleNamespace(
            hits=hits,
            trace_id="trace-files-chat",
            latency_ms=3,
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


def _retrieval_hit(
    *,
    file_id: str,
    filename: str,
    excerpt: str,
    locator: str | None = None,
    methods: list[str] | None = None,
    score: float = 0.8,
    content_witness: dict[str, object] | None = None,
) -> RetrievalHit:
    return RetrievalHit(
        source="generic_rag",
        source_kind="files",
        resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
        resource_id=file_id,
        title=filename,
        excerpt=excerpt,
        citation=f"{file_id}:text:0",
        methods=methods or ["semantic", "dense_vector", "cross_encoder"],
        score=score,
        metadata={
            **(content_witness or {}),
            **({"locator_label": locator} if locator else {}),
        },
    )
