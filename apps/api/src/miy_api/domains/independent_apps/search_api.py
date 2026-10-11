"""Bounded independent app search: actor/scope/configuration stay server-owned."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.contracts import AppIdentityOut, Contract
from miy_api.domains.independent_apps.data_api import (
    Collection,
    RecordOut,
    _bounded_body,
    get_store,
    identity,
)
from miy_api.domains.independent_apps.data_store import DataStoreError
from miy_api.domains.independent_apps.search_backends import CoreSearchBackends, SearchFailure
from miy_api.domains.independent_apps.search_service import pending, search_context
from miy_api.domains.independent_apps.search_store import SearchSourceStore

router = APIRouter(prefix="/_search", tags=["independent-app-search"])


class SearchQuery(Contract):
    query: str = Field(min_length=1, max_length=2000, strict=True)
    mode: Literal["keyword", "semantic"] = "keyword"
    limit: int = Field(default=20, ge=1, le=20, strict=True)

    @field_validator("query")
    @classmethod
    def bounded_query(cls, value):
        if not value.strip() or len(value.encode("utf-8")) > 8000:
            raise ValueError("Invalid bounded query")
        return value


class IndependentAppSearchHit(Contract):
    record: RecordOut
    score: float


class SearchResponse(Contract):
    items: list[IndependentAppSearchHit]
    indexing_pending: bool


async def query_body(request: Request):
    return await _bounded_body(request, SearchQuery)


@router.post(
    "/{collection}",
    response_model=SearchResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": SearchQuery.model_json_schema()}},
        }
    },
)
def query_search(
    collection: Collection,
    payload: SearchQuery = Depends(query_body),
    actor: AppIdentityOut = Depends(identity),
    db: Session = Depends(get_db_session),
    data=Depends(get_store),
):
    _, binding = search_context(db, actor, collection, payload.mode)
    backend = None
    try:
        backend = CoreSearchBackends(get_settings())
        source = SearchSourceStore(data)
        candidates = backend.query(
            binding,
            owner_id=actor.user_id,
            collection=collection,
            mode=payload.mode,
            query=payload.query,
            limit=payload.limit,
        )
        return SearchResponse(
            items=source.current_records(actor, collection, candidates),
            indexing_pending=pending(source, actor, collection, binding),
        )
    except (SearchFailure, DataStoreError):
        service.fail("data_unavailable", 503)
    finally:
        if backend is not None:
            backend.close()
