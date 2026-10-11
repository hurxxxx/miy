from __future__ import annotations

from fastapi.testclient import TestClient
from dev_accounts import dev_login, create_company_user_session, auth_headers

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.ai.registry import reset_ai_capability_registry
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.docs import service as docs_service
from miy_api.domains.rag import application as rag_application
from miy_api.domains.rag.docs_projection import load_native_doc_projection
from miy_api.domains.rag.providers.fake import (
    FakeEmbeddingClient,
    FakeRerankClient,
    FakeVectorIndexClient,
)
from miy_api.domains.rag.query_service import RagQueryService
from miy_api.domains.rag.runtime import (
    reset_rag_runtime_caches,
    resolve_default_collection_name,
)
from miy_api.domains.rag.service import RagService


def _create_user_session(client, admin_token, *, login_id, email, full_name, role="member"):
    return create_company_user_session(client, login_id=login_id, email=email, full_name=full_name)


def _auth_headers(token: str) -> dict[str, str]:
    return auth_headers(token)


def _disable_app(client, *, admin_token, app_id):
    response = client.patch(
        "/api/v1/admin/apps/company-controls",
        headers=auth_headers(admin_token),
        json={"items": [{"app_id": app_id, "enabled": False}]},
    )
    assert response.status_code == 200, response.text


def _reset_settings_and_registry() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    reset_rag_runtime_caches()
    reset_ai_capability_registry()


def test_rag_query_hides_other_users_personal_docs_even_from_platform_admin(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MIY_RAG_ENABLED", "1")
    _reset_settings_and_registry()
    delivery_session = dev_login(client, "administrator")
    other_session = create_company_user_session(
        client, login_id="other-owner", email="other-owner@example.test", full_name="Other Owner"
    )
    vector_index = FakeVectorIndexClient()
    embedding_client = FakeEmbeddingClient()
    rerank_client = FakeRerankClient()

    with get_session_factory()() as db:
        delivery_owner = load_user_graph(db, delivery_session["user"]["id"])
        hq_owner = load_user_graph(db, other_session["user"]["id"])
        assert delivery_owner is not None and hq_owner is not None

        delivery_doc, _ = docs_service.create_native_doc_for_user(
            db,
            owner_id=delivery_owner.id,
            title="Delivery Hub Phase 5 Note",
            content_blocks=[
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Phase 5 rollout note for delivery hub."}],
                }
            ],
        )
        hq_doc, _ = docs_service.create_native_doc_for_user(
            db,
            owner_id=hq_owner.id,
            title="HQ Phase 5 Note",
            content_blocks=[
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Phase 5 rollout note for HQ only."}],
                }
            ],
        )
        db.commit()

        rag_service = RagService(
            vector_index=vector_index,
            embedding_client=embedding_client,
            rerank_client=rerank_client,
            default_collection=resolve_default_collection_name(get_settings()),
        )
        for doc_id in (delivery_doc.id, hq_doc.id):
            projection = load_native_doc_projection(db, doc_id=doc_id)
            assert projection is not None
            rag_service.sync_projection(projection)

    query_service = RagQueryService(
        vector_index=vector_index,
        embedding_client=embedding_client,
        rerank_client=rerank_client,
    )
    monkeypatch.setattr(rag_application, "get_rag_query_service", lambda: query_service)

    response = client.post(
        "/api/v1/rag/query",
        headers=_auth_headers(delivery_session["token"]),
        json={"query": "phase 5 rollout", "answer_mode": "search-only"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert {hit["title"] for hit in payload["hits"]} == {"Delivery Hub Phase 5 Note"}
    assert all("workspace_id" not in hit for hit in payload["hits"])
