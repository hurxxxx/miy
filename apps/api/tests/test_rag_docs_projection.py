from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from dev_accounts import create_company_user_session, dev_login

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.auth.models import User
from miy_api.domains.docs import service as docs_service
from miy_api.domains.docs.access_grants import grant_doc_access
from miy_api.domains.rag.contracts import RagQueryRequest
from miy_api.domains.rag.access_filter import build_user_rag_post_filter
from miy_api.domains.rag.docs_projection import (
    load_native_doc_projection,
)
from miy_api.domains.rag.providers.fake import FakeEmbeddingClient, FakeVectorIndexClient
from miy_api.domains.rag.query_service import RagQueryService
from miy_api.domains.rag.service import RagService


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def test_native_doc_query_post_filter_rejects_expired_grant_hits(client: TestClient) -> None:
    session = _dev_login(client, "delivery-hub-admin")
    expired_session = create_company_user_session(
        client,
        login_id="docsragexpiredquery",
        email="docs-rag-expired-query@miy.local",
        full_name="Docs RAG Expired Query",
    )
    vector_index = FakeVectorIndexClient()
    embedding_client = FakeEmbeddingClient()
    query_service = RagQueryService(
        vector_index=vector_index,
        embedding_client=embedding_client,
    )
    rag_service = RagService(
        vector_index=vector_index,
        embedding_client=embedding_client,
        default_collection="docs-expired-grant-smoke",
    )

    with get_session_factory()() as db:
        owner = load_user_graph(db, session["user"]["id"])
        expired_user = db.get(User, expired_session["user"]["id"])
        assert owner is not None
        assert expired_user is not None

        doc, _page = docs_service.create_native_doc_for_user(
            db,
            owner_id=owner.id,
            title="Expired Grant Doc",
            content_blocks=[
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Grant expiry must be rechecked at query time."}
                    ],
                },
            ],
        )
        grant_doc_access(
            db,
            doc_id=doc.id,
            user_id=expired_user.id,
            granted_by_user_id=owner.id,
            granted_by_meeting_id=None,
            reason="meeting_attendee",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db.commit()
        projection = load_native_doc_projection(db, doc_id=doc.id)
        post_filter = build_user_rag_post_filter(db, user=expired_user)
        assert projection is not None

        rag_service.sync_projection(projection)
        response = query_service.query(
            RagQueryRequest(
                collection="docs-expired-grant-smoke",
                query="grant expiry query time",
                filters={"visibility_refs_contains": f"meeting_grant:{expired_user.id}"},
            ),
            post_filter=post_filter,
        )

        assert response.hits == []
