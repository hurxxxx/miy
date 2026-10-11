"""Live caller authority around Files-owned selection and bounded bytes."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.auth.security import hash_token
from miy_api.domains.files import selected_access, selected_storage
from miy_api.domains.independent_apps import file_signing, service
from miy_api.domains.independent_apps.file_contracts import (
    FileAuthorizeInput,
    FileCandidatesInput,
    FileCandidatesOut,
    FileSelectionContext,
    FileSelectionMetadata,
    FileSelectionRequestOut,
    SelectedFileReadOut,
)
from miy_api.domains.independent_apps.models import AppDefinitionRecord
from miy_api.domains.independent_apps.verification import trusted_release

PERMISSION = "files:read-selected"


def transaction(db: Session) -> None:
    with db.no_autoflush:
        if (
            db.connection().connection.driver_connection.autocommit is True
            or db.scalar(text("SELECT current_setting('transaction_isolation')"))
            != "read committed"
        ):
            service.fail("file_access_invalid")
        db.execute(text("SELECT set_config('lock_timeout', '1000ms', true)"))
        db.execute(text("SELECT set_config('statement_timeout', '1000ms', true)"))


def _context(data: FileSelectionContext) -> dict:
    return {name: getattr(data, name) for name in FileSelectionContext.model_fields}


def _current(db: Session, *, session_key: str, installation_id: str, audience: str):
    current = service.verified_app_session(
        db,
        token_hash=session_key,
        installation_id=installation_id,
        audience=audience,
    )
    installation = current.installation
    if installation.release_id:
        release = trusted_release(db, installation, installation.release_id)
        manifest = release.definition_snapshot if release else {}
    elif installation.environment == "development":
        definition = db.get(AppDefinitionRecord, installation.app_id, populate_existing=True)
        manifest = definition.manifest if definition else {}
    else:
        manifest = {}
    if (
        manifest.get("runtime_profile") not in {"web-api-v1", "web-api-postgres-v1"}
        or not {"identity:read", PERMISSION}.issubset(current.permissions)
        or not {"identity:read", PERMISSION}.issubset(manifest.get("requested_permissions", []))
        or not can_use_app(db, app_id="files", user_id=current.user.id)
    ):
        service.fail("file_access_invalid")
    return current


def _claim_current(db: Session, claims, *, session_key: str | None = None):
    if session_key is not None and claims.session_key != session_key:
        service.fail("file_access_invalid")
    current = _current(
        db,
        session_key=claims.session_key,
        installation_id=str(claims.installation_id),
        audience=claims.audience,
    )
    if current.installation.generation != claims.generation:
        service.fail("file_access_invalid")
    return current


def _host(db: Session, data, context: AuthContext):
    claims = file_signing.verify(data.selection_request)
    if _context(claims) != _context(data):
        service.fail("file_access_invalid")
    current = _claim_current(db, claims)
    live = resolve_auth_context_from_session_id(db, context.session.id)
    if (
        live.impersonator_user_id is not None
        or context.impersonator_user_id is not None
        or live.user.id != current.user.id
        or live.session.id != current.source_session.id
    ):
        service.fail("file_access_invalid")
    return current, claims, live


def _expiry(current, ttl: int) -> tuple[int, int]:
    now = int(time.time())
    expires = min(
        now + ttl,
        int(current.session.expires_at.replace(tzinfo=UTC).timestamp()),
        int(current.source_session.expires_at.replace(tzinfo=UTC).timestamp()),
    )
    if expires <= now:
        service.fail("file_access_invalid")
    return now, expires


def _date(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _metadata(descriptor) -> FileSelectionMetadata:
    return FileSelectionMetadata(
        **{name: getattr(descriptor, name) for name in FileSelectionMetadata.model_fields}
    )


def _source(db, *, user_id: str, file_id: str):
    try:
        descriptor = selected_access.selected_file(db, user_id=user_id, file_id=file_id)
    except selected_access.SelectedFileDenied:
        service.fail("file_access_invalid")
    if not 0 <= descriptor.size_bytes <= selected_storage.MAX_BYTES:
        service.fail("file_size_exceeded", 413)
    return descriptor


def selection_request(db: Session, data: FileSelectionContext, *, token: str):
    transaction(db)
    current = _current(
        db,
        session_key=hash_token(token),
        installation_id=str(data.installation_id),
        audience=data.audience,
    )
    issued, expires = _expiry(current, file_signing.REQUEST_TTL)
    claims = file_signing.FileRequestClaims(
        **_context(data),
        session_key=current.session.token_hash,
        generation=current.installation.generation,
        issued_at=issued,
        expires=expires,
    )
    return FileSelectionRequestOut(
        **_context(data),
        selection_request=file_signing.sign(claims),
        expires_at=_date(expires),
    )


def _cursor(query: str, selection_id: UUID, last: str | None) -> str | None:
    if last is None:
        return None
    raw = json.dumps(
        {
            "after": last,
            "selection_id": str(selection_id),
            "query": hashlib.sha256(query.encode()).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(data: FileCandidatesInput) -> str | None:
    if data.cursor is None:
        return None
    try:
        cursor = json.loads(
            base64.b64decode(
                data.cursor + "=" * (-len(data.cursor) % 4),
                altchars=b"-_",
                validate=True,
            )
        )
        if set(cursor) != {"after", "query", "selection_id"}:
            raise ValueError("cursor")
        last = str(UUID(cursor["after"]))
        if _cursor(data.query, data.selection_id, last) != data.cursor:
            raise ValueError("cursor")
        return last
    except (ValueError, TypeError, KeyError, AttributeError):
        service.fail("file_request_invalid", 422)


def candidates(db: Session, data: FileCandidatesInput, context: AuthContext):
    transaction(db)
    current, _, _ = _host(db, data, context)
    try:
        page = selected_access.selection_candidates(
            db,
            user_id=current.user.id,
            query=data.query,
            after=_after(data),
            limit=data.limit,
        )
    except selected_access.SelectedFileDenied:
        service.fail("file_access_invalid")
    _host(db, data, context)
    return FileCandidatesOut(
        **_context(data),
        items=[_metadata(item) for item in page.items],
        next_cursor=_cursor(data.query, data.selection_id, page.after),
        incomplete=page.incomplete,
    )


def authorize(db: Session, data: FileAuthorizeInput, context: AuthContext):
    transaction(db)
    current, _, live = _host(db, data, context)
    descriptor = _source(db, user_id=current.user.id, file_id=str(data.file_id))
    if descriptor.version != data.expected_version:
        service.fail("file_access_invalid")
    grant_id = uuid4()
    record_audit_log(
        db,
        actor_user_id=live.user.id,
        action="independent_app.file.selected",
        entity_kind="independent_app",
        entity_id=None,
        summary="A file was selected for an independent app",
        payload={
            "app_id": current.installation.app_id,
            "installation_id": current.installation.id,
            "selection_id": str(data.selection_id),
            "grant_id": str(grant_id),
            "file_id": str(data.file_id),
        },
    )
    db.flush()
    # Audit insertion may wait. Revalidate all authority and selected version
    # before publishing the claim; a denied operation rolls its audit back too.
    current, _, _ = _host(db, data, context)
    descriptor = _source(db, user_id=current.user.id, file_id=str(data.file_id))
    if descriptor.version != data.expected_version:
        service.fail("file_access_invalid")
    issued, expires = _expiry(current, file_signing.READ_TTL)
    claims = file_signing.FileReadClaims(
        **_context(data),
        session_key=current.session.token_hash,
        generation=current.installation.generation,
        issued_at=issued,
        expires=expires,
        file_id=data.file_id,
        version=descriptor.version,
        grant_id=grant_id,
    )
    result = SelectedFileReadOut(
        **_context(data),
        file=_metadata(descriptor),
        read_grant=file_signing.sign(claims),
        expires_at=_date(expires),
    )
    db.commit()
    return result


async def content(
    db: Session, *, token: str, grant: str, installation_id: str, audience: str
) -> tuple[bytes, selected_access.SelectedFileDescriptor]:
    transaction(db)
    session_key = hash_token(token)
    # An app bearer remains mandatory even when the signed read handle is valid.
    _current(db, session_key=session_key, installation_id=installation_id, audience=audience)
    claims = file_signing.verify(grant, read=True)
    if str(claims.installation_id) != installation_id or claims.audience != audience:
        service.fail("file_access_invalid")
    current = _claim_current(db, claims, session_key=session_key)
    descriptor = _source(db, user_id=current.user.id, file_id=str(claims.file_id))
    if descriptor.version != claims.version:
        service.fail("file_access_invalid")
    settings = get_settings()
    config = selected_storage.SelectedStorageConfig(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        region=settings.independent_app_file_selection_storage_region,
    )
    try:
        body = await selected_storage.read_selected_object(
            config,
            storage_key=descriptor.storage_key,
            expected_size=descriptor.size_bytes,
        )
    except selected_storage.SelectedFileTooLarge:
        service.fail("file_size_exceeded", 413)
    except selected_storage.SelectedStorageUnavailable:
        service.fail("file_read_unavailable", 503)
    # Socket and upstream response are closed before the final live checks.
    claims = file_signing.verify(grant, read=True)
    current = _claim_current(db, claims, session_key=session_key)
    fresh = _source(db, user_id=current.user.id, file_id=str(claims.file_id))
    if fresh != descriptor:
        service.fail("file_access_invalid")
    return body, fresh


def database_error(db: Session, error: DBAPIError, *, reading: bool = False) -> None:
    db.rollback()
    if getattr(error.orig, "sqlstate", None) in {"55P03", "57014"}:
        service.fail("file_read_unavailable" if reading else "file_query_unavailable", 503)
