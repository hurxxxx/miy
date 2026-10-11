from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from dev_accounts import dev_login

from miy_api.core.db import get_engine
from miy_api.domains.auth.models import CompanyAppControl
from miy_api.domains.retrieval import application as retrieval_application
from miy_api.domains.retrieval.contracts import (
    RetrievalHit,
    RetrievalQueryRequest,
)
from miy_api.domains.retrieval.tools import retrieval_discoverable_app_ids
from miy_api.domains.search.backend_contracts import (
    KeywordSearchQuery,
    KeywordSearchResult,
)


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _retrieval_path(suffix: str) -> str:
    return f"/api/v1/retrieval{suffix}"


def _allow_final_retrieval_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        retrieval_application,
        "_filter_current_retrieval_hits",
        lambda _db, *, user, hits: list(hits),
    )


def _ai_path(suffix: str) -> str:
    return f"/api/v1/chatbot{suffix}"


def _tool_path(tool_name: str) -> str:
    return _ai_path(f"/tools/{tool_name}/invoke")


def _install_in_process_keyword_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> list[KeywordSearchQuery]:
    captured_queries: list[KeywordSearchQuery] = []

    class _KeywordSearchClient:
        def index_exists(self) -> bool:
            return True

        def search(self, query: KeywordSearchQuery) -> KeywordSearchResult:
            captured_queries.append(query)
            return KeywordSearchResult(hits=())

    client = _KeywordSearchClient()
    monkeypatch.setattr(
        retrieval_application.search_service,
        "_search_client",
        lambda: client,
    )
    return captured_queries


def _disable_retrieval_discoverability_apps() -> None:
    with Session(get_engine()) as session:
        for app_id in retrieval_discoverable_app_ids():
            row = session.get(CompanyAppControl, app_id)
            assert row is not None
            row.enabled = False
        session.commit()


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pnpm-workspace.yaml").exists():
            return parent
    return current.parents[3]


def _read_source_matrix() -> dict[str, dict[str, object]]:
    matrix_path = _repo_root() / "docs" / "domains" / "rag" / "source-matrix.md"
    rows: dict[str, dict[str, object]] = {}
    for line in matrix_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        source = cells[0].strip("`")
        rows[source] = {
            "scope": cells[1],
            "backend": cells[2],
            "active": cells[3].lower() == "true",
        }
    return rows


def test_final_retrieval_filter_rechecks_owner_app_and_source_acl(monkeypatch) -> None:
    user = SimpleNamespace(id="user-1", status="active", login_blocked=False)
    db = SimpleNamespace(scalar=lambda _statement: user)
    enabled = {"value": True}

    class Policy:
        def authorize_many_resources(self, resources):
            return {
                resource
                for resource in resources
                if enabled["value"] and resource == ("docs_native_doc", "allowed")
            }

        def authorize_many_rag_resources(self, resources):
            return self.authorize_many_resources(resources)

    monkeypatch.setattr(
        retrieval_application.SourceAclPolicy,
        "for_user",
        lambda *_args, **_kwargs: Policy(),
    )
    hits = [
        RetrievalHit(
            source="generic_rag",
            resource_type="docs_native_doc",
            resource_id=resource_id,
            metadata={"scope_kind": "company"},
        )
        for resource_id in ("allowed", "denied")
    ]
    hits.append(
        RetrievalHit(
            source="generic_rag",
            resource_type="unknown",
            resource_id="unknown",
            metadata={"scope_kind": "company"},
        )
    )

    assert [
        hit.resource_id
        for hit in retrieval_application._filter_current_retrieval_hits(
            db,
            user=user,
            hits=hits,
        )
    ] == ["allowed"]

    enabled["value"] = False
    assert (
        retrieval_application._filter_current_retrieval_hits(
            db,
            user=user,
            hits=hits,
        )
        == []
    )


def test_explicit_source_selection_fails_closed() -> None:
    with pytest.raises(HTTPException) as invalid:
        retrieval_application._resolve_request_sources(
            RetrievalQueryRequest(query="x", sources=["missing"]),
            enabled_app_ids=set(),
        )
    assert invalid.value.status_code == 422

    with pytest.raises(HTTPException) as unavailable:
        retrieval_application._resolve_request_sources(
            RetrievalQueryRequest(query="x", sources=["generic_rag"]),
            enabled_app_ids=set(),
        )
    assert unavailable.value.status_code == 403
