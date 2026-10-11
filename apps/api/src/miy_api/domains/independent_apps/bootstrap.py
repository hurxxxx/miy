"""Atomic first registration, separate from app admission and trusted delivery evidence."""

import hashlib
import json
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput, BootstrapReceipt
from miy_api.domains.independent_apps.bootstrap_models import AppBootstrapOperation
from miy_api.domains.independent_apps.contracts import InstallationInput, RegisterDefinition

LOCK_TIMEOUT_MS = 5000


def _authority_transaction(db: Session) -> None:
    if (
        db.connection().connection.driver_connection.autocommit is True
        or db.scalar(text("SELECT current_setting('transaction_isolation')")) != "read committed"
    ):
        service.fail("forbidden")
    db.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": f"{LOCK_TIMEOUT_MS}ms"},
    )


def _current_owner(db: Session, context: AuthContext) -> AuthContext:
    with db.no_autoflush:
        current = resolve_auth_context_from_session_id(db, context.session.id)
    if (
        current.user.id != context.user.id
        or current.session.id != context.session.id
        or context.impersonator_user_id is not None
        or current.impersonator_user_id is not None
    ):
        service.fail("forbidden")
    return current


def _lock_keys(data: BootstrapInput) -> list[int]:
    # Namespace and deterministic order prevent opposite-order acquisitions.
    # Hash collisions only serialize unrelated work; DB identities stay authoritative.
    return sorted(
        {
            int.from_bytes(
                hashlib.sha256(("independent-bootstrap:v1:" + name).encode()).digest()[:8],
                "big",
                signed=True,
            )
            for name in (
                "operation:" + str(data.operation_id),
                "app:" + data.definition.app_id,
                "origin:" + data.origin,
            )
        }
    )


def _receipt(row: AppBootstrapOperation) -> BootstrapReceipt:
    return BootstrapReceipt.model_validate(row, from_attributes=True)


def _installation(data: BootstrapInput, owner_id: str) -> InstallationInput:
    return InstallationInput(
        environment="development",
        origin=data.origin,
        enabled=False,
        audience="selected",
        user_ids=[owner_id],
        group_ids=[],
        granted_permissions=data.granted_permissions,
    )


def _digest(data: BootstrapInput, installation: InstallationInput, owner_id: str) -> str:
    canonical = {
        "schema_version": 1,
        "owner_user_id": owner_id,
        "definition": data.definition.model_dump(mode="json"),
        "source_revision": data.source_revision,
        "installation": installation.model_dump(mode="json"),
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def create(
    db: Session,
    data: BootstrapInput,
    context: AuthContext,
    *,
    platform_origin: str,
    registration_check: Callable[[str | None], None] | None = None,
) -> BootstrapReceipt:
    """Commit one completed receipt and both resources, or roll back everything.

    A replay returns the initial receipt, never writes historical configuration
    over the current installation and never treats source metadata as a build.
    """
    try:
        _authority_transaction(db)
        _current_owner(db, context)
        if registration_check is not None:
            registration_check(None)
        for key in _lock_keys(data):
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        owner = _current_owner(db, context)
        installation_data = _installation(data, owner.user.id)
        payload_digest = _digest(data, installation_data, owner.user.id)
        if registration_check is not None:
            registration_check(payload_digest)
        row = db.get(AppBootstrapOperation, str(data.operation_id), populate_existing=True)
        if row is not None:
            if row.owner_user_id != owner.user.id or row.payload_digest != payload_digest:
                service.fail("conflict", 409)
            result = _receipt(row)
            db.rollback()  # Read-only replay releases its transaction locks.
            return result
        definition = service.stage_definition(
            db,
            RegisterDefinition(definition=data.definition, source_revision=data.source_revision),
            owner,
            create_only=True,
        )
        installation = service.stage_installation(
            db,
            definition.app_id,
            installation_data,
            owner,
            platform_origin=platform_origin,
        )
        row = AppBootstrapOperation(
            operation_id=str(data.operation_id),
            owner_user_id=owner.user.id,
            app_id=definition.app_id,
            installation_id=installation.id,
            payload_digest=payload_digest,
            definition_digest=definition.definition_digest,
            source_revision=data.source_revision,
        )
        db.add(row)
        db.flush()
        # A constraint/foreign-key wait cannot retain stale source-session authority.
        _current_owner(db, context)
        if registration_check is not None:
            registration_check(payload_digest)
        result = _receipt(row)
        db.commit()
        return result
    except IntegrityError:
        # Legacy owner endpoints do not use these advisory locks. Their unique
        # constraints still reject concurrent app/origin adoption atomically.
        db.rollback()
        service.fail("conflict", 409)
    except DBAPIError as error:
        db.rollback()
        if getattr(error.orig, "sqlstate", None) == "55P03":
            service.fail("bootstrap_busy", 503)
        raise
    except BaseException:
        db.rollback()
        raise


def read(db: Session, operation_id: str, context: AuthContext) -> BootstrapReceipt:
    try:
        _authority_transaction(db)
        owner = _current_owner(db, context)
        row = db.get(AppBootstrapOperation, operation_id, populate_existing=True)
        if row is None or row.owner_user_id != owner.user.id:
            service.fail("not_found", 404)
        return _receipt(row)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            service.fail("bootstrap_busy", 503)
        raise
    finally:
        db.rollback()
