from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, select

from dev_accounts import auth_headers, dev_login

from miy_api.core.db import get_engine, get_session_factory
from miy_api.domains.auth.models import User
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant
from miy_api.domains.files import service as files_service
from miy_api.domains.files.models import (
    FileManagerFile,
)
from miy_api.domains.files.current_content import file_extraction_result_marker
from miy_api.domains.files.router import require_file_search_runtime
from miy_api.domains.files.search import FileSearchRuntime
from miy_api.domains.files.search_projection import build_file_search_document
from miy_api.domains.rag.contracts import RagChunk, RagProjection, RagScopeKind
from miy_api.domains.rag.providers.fake import FakeEmbeddingClient, FakeVectorIndexClient
from miy_api.domains.rag.query_service import RagQueryService
from miy_api.domains.rag.service import RagService
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE
from miy_api.domains.search.backend_contracts import (
    KeywordSearchHit,
    KeywordSearchQuery,
    KeywordSearchResult,
)


_FILES_SEARCH_PATH = "/api/v1/files/search"


class _KeywordBackend:
    def __init__(
        self,
        document: dict[str, object] | list[tuple[dict[str, object], float]],
    ) -> None:
        self.documents = [(document, 17.25)] if isinstance(document, dict) else list(document)
        self.last_query: KeywordSearchQuery | None = None

    def index_exists(self) -> bool:
        return True

    def open_point_in_time(self, *, keep_alive: str = "1m") -> str:
        assert keep_alive == "1m"
        return "files-search-pit"

    def close_point_in_time(self, point_in_time_id: str) -> None:
        assert point_in_time_id == "files-search-pit"

    def search(self, query: KeywordSearchQuery) -> KeywordSearchResult:
        self.last_query = query
        return KeywordSearchResult(
            hits=tuple(
                KeywordSearchHit(
                    document=document,
                    score=score,
                    sort_values=(score, str(document["entity_id"])),
                )
                for document, score in self.documents
            )
        )


class _RecordingVectorBackend(FakeVectorIndexClient):
    def __init__(self) -> None:
        super().__init__()
        self.last_query = None
        self.result_counts: list[int] = []

    def query(self, *, request, timeout_seconds=None):
        self.last_query = request
        result = super().query(request=request, timeout_seconds=timeout_seconds)
        self.result_counts.append(len(result))
        return result


def test_keyword_file_search_refills_page_after_concurrent_revoke_and_recomputes_has_more(
    client: TestClient,
    in_memory_object_storage: None,
) -> None:
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    corpus_response = client.post(
        "/api/v1/files/corpora",
        headers=headers,
        json={"name": "Concurrent revoke refill corpus"},
    )
    assert corpus_response.status_code == 201, corpus_response.text
    corpus = corpus_response.json()

    documents: list[tuple[dict[str, object], float]] = []
    uploaded_ids: list[str] = []
    for index, score in enumerate((30.0, 20.0, 10.0)):
        upload_response = client.post(
            "/api/v1/files/upload",
            headers=headers,
            data={
                "visibility": "company",
                "company_admin_read_acknowledged": True,
                "corpus_id": corpus["id"],
            },
            files={
                "file": (
                    f"concurrent-refill-{index}.txt",
                    f"access control evidence {index}".encode(),
                    "text/plain",
                )
            },
        )
        assert upload_response.status_code == 201, upload_response.text
        uploaded = upload_response.json()
        uploaded_ids.append(uploaded["id"])
        with get_session_factory()() as db:
            file = db.get(FileManagerFile, uploaded["id"])
            assert file is not None
            file.extraction_status = "ready"
            file.extracted_at = datetime(2026, 10, 7, 10, tzinfo=UTC)
            file.extraction_content_checksum = str(index + 1) * 64
            file.extraction_text = f"access control evidence {index}"
            file.extraction_blocks = [{"text": file.extraction_text}]
            file.extraction_metadata = {"parser": "plain_text"}
            db.commit()
            db.refresh(file)
            document = build_file_search_document(file=file)
            document["retrieval_partition_id"] = str(file.retrieval_partition_id)
            document["projection_version"] = 1
        documents.append((document, score))

    keyword_backend = _KeywordBackend(documents)
    client.app.dependency_overrides[require_file_search_runtime] = lambda: FileSearchRuntime(
        keyword_client=keyword_backend,
        rag_query_service=None,
        rag_collection=None,
    )
    delete_triggered = False

    def delete_top_hit_before_extraction_query(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal delete_triggered
        if delete_triggered or "file_manager_files.extraction_text" not in statement:
            return
        delete_triggered = True
        with get_session_factory().begin() as revoke_db:
            user = revoke_db.scalar(select(User).where(User.login_id == "administrator"))
            assert user is not None
            files_service.delete_file(
                revoke_db,
                user=user,
                file_id=uploaded_ids[0],
            )

    event.listen(get_engine(), "before_cursor_execute", delete_top_hit_before_extraction_query)
    try:
        response = client.post(
            _FILES_SEARCH_PATH,
            headers=headers,
            json={
                "query": "access control",
                "strategy": "keyword",
                "page": 1,
                "page_size": 2,
            },
        )
    finally:
        event.remove(get_engine(), "before_cursor_execute", delete_top_hit_before_extraction_query)
        client.app.dependency_overrides.pop(require_file_search_runtime, None)

    assert delete_triggered is True
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [hit["file_id"] for hit in payload["hits"]] == uploaded_ids[1:]
    assert [hit["rank"] for hit in payload["hits"]] == [1, 2]
    assert payload["has_more"] is False


@pytest.mark.parametrize("strategy", ["keyword"])
def test_file_search_has_more_matches_final_authorized_window_for_each_strategy(
    client: TestClient,
    in_memory_object_storage: None,
    strategy: str,
) -> None:
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    corpus_response = client.post(
        "/api/v1/files/corpora",
        headers=headers,
        json={"name": f"Paged {strategy} search corpus"},
    )
    assert corpus_response.status_code == 201, corpus_response.text
    corpus = corpus_response.json()

    documents: list[tuple[dict[str, object], float]] = []
    projections: list[RagProjection] = []
    uploaded_ids: set[str] = set()
    for index, score in enumerate((30.0, 20.0, 10.0)):
        content = f"common semantic access evidence {index}"
        upload_response = client.post(
            "/api/v1/files/upload",
            headers=headers,
            data={
                "visibility": "company",
                "company_admin_read_acknowledged": True,
                "corpus_id": corpus["id"],
            },
            files={
                "file": (
                    f"paged-{strategy}-{index}.txt",
                    content.encode(),
                    "text/plain",
                )
            },
        )
        assert upload_response.status_code == 201, upload_response.text
        uploaded = upload_response.json()
        uploaded_ids.add(uploaded["id"])
        with get_session_factory()() as db:
            file = db.get(FileManagerFile, uploaded["id"])
            assert file is not None
            file.extraction_status = "ready"
            file.extracted_at = datetime(2026, 10, 7, 10, tzinfo=UTC)
            file.extraction_content_checksum = str(index + 4) * 64
            file.extraction_text = content
            file.extraction_blocks = [{"text": content}]
            file.extraction_metadata = {"parser": "plain_text"}
            db.commit()
            db.refresh(file)
            document = build_file_search_document(file=file)
            document["retrieval_partition_id"] = str(file.retrieval_partition_id)
            document["projection_version"] = 1
            projections.append(
                RagProjection(
                    retrieval_partition_id=str(file.retrieval_partition_id),
                    projection_version=1,
                    scope_kind=RagScopeKind.COMPANY,
                    resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
                    resource_id=file.id,
                    source_kind="files",
                    title=file.filename,
                    summary=content,
                    text_content=content,
                    visibility_refs=["company_public"],
                    metadata={
                        "filename": file.filename,
                        "content_modality": "text",
                        "content_checksum": file.extraction_content_checksum,
                        "extracted_at": file_extraction_result_marker(file.extracted_at),
                    },
                    chunks=[
                        RagChunk(
                            chunk_id=f"{file.id}:text:0",
                            text=content,
                            summary=content,
                            index_text=content,
                        )
                    ],
                )
            )
        documents.append((document, score))

    vector_backend = _RecordingVectorBackend()
    embedding_backend = FakeEmbeddingClient(dimensions=32)
    rag_collection = f"files-page-contract-{strategy}"
    rag_service = RagService(
        vector_index=vector_backend,
        embedding_client=embedding_backend,
        default_collection=rag_collection,
    )
    for projection in projections:
        rag_service.sync_projection(projection, collection=rag_collection)
    rag_query_service = RagQueryService(
        vector_index=vector_backend,
        embedding_client=embedding_backend,
        rerank_client=None,
        query_timeout_ms=5_000,
    )
    keyword_backend = _KeywordBackend(documents)
    client.app.dependency_overrides[require_file_search_runtime] = lambda: FileSearchRuntime(
        keyword_client=keyword_backend,
        rag_query_service=rag_query_service,
        rag_collection=rag_collection,
    )
    try:
        first_response = client.post(
            _FILES_SEARCH_PATH,
            headers=headers,
            json={
                "query": "common semantic access",
                "strategy": strategy,
                "page": 1,
                "page_size": 2,
            },
        )
        second_response = client.post(
            _FILES_SEARCH_PATH,
            headers=headers,
            json={
                "query": "common semantic access",
                "strategy": strategy,
                "page": 2,
                "page_size": 2,
            },
        )
    finally:
        client.app.dependency_overrides.pop(require_file_search_runtime, None)

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    first = first_response.json()
    second = second_response.json()
    assert len(first["hits"]) == 2
    assert first["has_more"] is True
    assert [hit["rank"] for hit in first["hits"]] == [1, 2]
    assert len(second["hits"]) == 1
    assert second["has_more"] is False
    assert [hit["rank"] for hit in second["hits"]] == [3]
    assert {hit["file_id"] for hit in [*first["hits"], *second["hits"]]} == uploaded_ids


def _set_files_user_admission(user_ids: list[str]) -> None:
    with get_session_factory().begin() as db:
        policy = db.get(AppAccessPolicy, "files")
        assert policy is not None
        policy.audience = "selected"
        db.execute(delete(AppUserGrant).where(AppUserGrant.app_id == "files"))
        db.add_all(AppUserGrant(app_id="files", user_id=user_id) for user_id in user_ids)
