"""Owner-scoped data gateway. Only this core service can use its DML credentials."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, ValidationError
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.contracts import AppIdentityOut, Contract
from miy_api.domains.independent_apps.data_store import (
    PROFILE,
    DataStoreError,
    PostgresAppData,
    configured_store,
)
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord

router = APIRouter(prefix="/_data", tags=["independent-app-data"])
Collection = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class RecordBody(Contract):
    payload: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


class RecordOut(Contract):
    id: UUID
    payload: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class RecordList(Contract):
    items: list[RecordOut]
    next_cursor: UUID | None


_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": RecordBody.model_json_schema()}},
    }
}


def get_store() -> PostgresAppData:
    try:
        return configured_store(get_settings())
    except DataStoreError:
        service.fail("data_unavailable", 503)


def identity(
    installation_id: UUID,
    audience: str = Query(max_length=300),
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
) -> AppIdentityOut:
    if not authorization or not authorization.startswith("Bearer "):
        service.fail("session_invalid", 401)
    actor = service.app_identity(
        db,
        token=authorization.removeprefix("Bearer "),
        installation_id=str(installation_id),
        audience=audience,
    )
    installation = db.get(AppInstallationRecord, str(installation_id))
    release = db.get(AppReleaseRecord, installation.release_id) if installation.release_id else None
    # A definition declaring storage is not a provisioned, active data release.
    if release is None or release.definition_snapshot.get("runtime_profile") != PROFILE:
        service.fail("forbidden")
    return actor


async def bounded_body(request: Request) -> RecordBody:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024:
            service.fail("data_payload_invalid", 413)
    try:
        return RecordBody.model_validate(json.loads(raw))
    except (ValueError, ValidationError, RecursionError):
        service.fail("data_payload_invalid", 422)


def _call(actor: AppIdentityOut, permission: str, callback):
    if permission not in actor.permissions:
        service.fail("forbidden")
    try:
        return callback()
    except DataStoreError as exc:
        if exc.code == "data_record_not_found":
            service.fail("not_found", 404)
        if exc.code == "data_record_conflict":
            service.fail("conflict", 409)
        if exc.code in {"data_payload_invalid", "data_version_required"}:
            service.fail("data_payload_invalid", 422)
        service.fail("data_unavailable", 503)


@router.get("/{collection}", response_model=RecordList)
def list_records(
    collection: Collection,
    after: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    actor: AppIdentityOut = Depends(identity),
    store: PostgresAppData = Depends(get_store),
):
    rows = _call(
        actor,
        "data:read",
        lambda: store.list_records(
            actor, collection, after=str(after) if after else None, limit=limit
        ),
    )
    return RecordList(items=rows, next_cursor=rows[-1]["id"] if len(rows) == limit else None)


@router.get("/{collection}/{record_id}", response_model=RecordOut)
def read_record(
    collection: Collection,
    record_id: UUID,
    actor: AppIdentityOut = Depends(identity),
    store: PostgresAppData = Depends(get_store),
):
    return _call(actor, "data:read", lambda: store.read(actor, collection, str(record_id)))


@router.post("/{collection}", response_model=RecordOut, status_code=201, openapi_extra=_BODY)
def create_record(
    collection: Collection,
    body: RecordBody = Depends(bounded_body),
    actor: AppIdentityOut = Depends(identity),
    store: PostgresAppData = Depends(get_store),
):
    if body.expected_version is not None:
        service.fail("data_payload_invalid", 422)
    return _call(actor, "data:write", lambda: store.write(actor, collection, body.payload))


@router.put("/{collection}/{record_id}", response_model=RecordOut, openapi_extra=_BODY)
def update_record(
    collection: Collection,
    record_id: UUID,
    body: RecordBody = Depends(bounded_body),
    actor: AppIdentityOut = Depends(identity),
    store: PostgresAppData = Depends(get_store),
):
    return _call(
        actor,
        "data:write",
        lambda: store.write(
            actor,
            collection,
            body.payload,
            record_id=str(record_id),
            expected_version=body.expected_version,
        ),
    )


@router.delete("/{collection}/{record_id}", status_code=204)
def delete_record(
    collection: Collection,
    record_id: UUID,
    expected_version: int = Query(ge=1),
    actor: AppIdentityOut = Depends(identity),
    store: PostgresAppData = Depends(get_store),
):
    _call(
        actor,
        "data:write",
        lambda: store.delete(actor, collection, str(record_id), expected_version),
    )
