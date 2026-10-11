"""Explicit, short-lived registration authority; SSO and metadata keys stay read-only."""

import base64
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from miy_api.core.registration_audience import CALLBACK_PATH
from miy_api.core.settings import get_settings
from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps import bootstrap, service
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput, BootstrapReceipt
from miy_api.domains.independent_apps.bootstrap_models import AppBootstrapOperation
from miy_api.domains.independent_apps.registration_contracts import (
    RegistrationAuthorizationInput,
    RegistrationAuthorizationOut,
    RegistrationCodeOut,
    RegistrationExchangeInput,
    RegistrationTokenOut,
)
from miy_api.domains.independent_apps.registration_models import AppRegistrationAuthorization

CODE_TTL_SECONDS = 120
GRANT_TTL_SECONDS = 300
CODE_PREFIX = "miyrc_"
TOKEN_PREFIX = "miyrg_"
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


@contextmanager
def _transaction(db: Session):
    try:
        bootstrap._authority_transaction(db)
        yield
    except IntegrityError:
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


def _audience(value: str) -> None:
    if value not in get_settings().codex_console_registration_audiences:
        service.fail("forbidden")


def _owner(db: Session, context: AuthContext) -> AuthContext:
    current = bootstrap._current_owner(db, context)
    if not can_use_app(db, user_id=current.user.id, app_id="codex-console"):
        service.fail("forbidden")
    return current


def _current(db: Session, row: AppRegistrationAuthorization) -> AuthContext:
    _audience(row.audience)
    if row.revoked_at is not None or row.expires_at <= utcnow_naive():
        service.fail("session_invalid", 401)
    with db.no_autoflush:
        current = resolve_auth_context_from_session_id(db, row.source_session_id)
    if current.user.id != row.actor_user_id:
        service.fail("forbidden")
    owner = _owner(db, current)
    if row.expires_at <= utcnow_naive():
        service.fail("session_invalid", 401)
    return owner


def _public(row: AppRegistrationAuthorization) -> dict:
    return RegistrationAuthorizationOut.model_validate(
        {
            "schema_version": 1,
            "id": row.id,
            "request_id": row.request_id,
            "operation_id": row.operation_id,
            "actor_user_id": row.actor_user_id,
            "audience": row.audience,
            "policy": row.policy,
            "expires_at": row.expires_at,
        }
    ).model_dump()


def issue(db: Session, data: RegistrationAuthorizationInput, context: AuthContext):
    with _transaction(db):
        owner = _owner(db, context)
        _audience(data.audience)
        code = CODE_PREFIX + secrets.token_urlsafe(32)
        now = utcnow_naive()
        row = AppRegistrationAuthorization(
            id=str(uuid4()),
            request_id=str(data.request_id),
            operation_id=str(data.operation_id),
            actor_user_id=owner.user.id,
            source_session_id=owner.session.id,
            audience=data.audience,
            policy=data.policy.model_dump(mode="json"),
            code_challenge=data.code_challenge,
            code_hash=hash_token(code),
            code_expires_at=min(
                owner.session.expires_at, now + timedelta(seconds=CODE_TTL_SECONDS)
            ),
            expires_at=min(owner.session.expires_at, now + timedelta(seconds=GRANT_TTL_SECONDS)),
        )
        db.add(row)
        service._audit(db, owner, "registration.authorize", data.policy.app_id)
        db.flush()
        _current(db, row)
        result = RegistrationCodeOut.model_validate(
            _public(row)
            | {
                "callback_url": row.audience + CALLBACK_PATH,
                "code": code,
                "code_expires_at": row.code_expires_at,
            }
        )
        db.commit()
        return result


def exchange(db: Session, data: RegistrationExchangeInput):
    with _transaction(db):
        _audience(data.audience)
        if not data.code.startswith(CODE_PREFIX) or not _VERIFIER.fullmatch(data.code_verifier):
            service.fail("session_invalid", 401)
        row = db.scalar(
            select(AppRegistrationAuthorization)
            .where(AppRegistrationAuthorization.code_hash == hash_token(data.code))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(data.code_verifier.encode("ascii")).digest())
            .decode()
            .rstrip("=")
        )
        if (
            row is None
            or row.request_id != str(data.request_id)
            or row.audience != data.audience
            or row.exchanged_at is not None
            or row.code_expires_at <= utcnow_naive()
            or not hmac.compare_digest(row.code_challenge, challenge)
        ):
            service.fail("session_invalid", 401)
        owner = _current(db, row)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        row.token_hash = hash_token(token)
        row.exchanged_at = utcnow_naive()
        service._audit(db, owner, "registration.exchange", row.policy["app_id"])
        db.flush()
        _current(db, row)
        if row.code_expires_at <= utcnow_naive():
            service.fail("session_invalid", 401)
        result = RegistrationTokenOut.model_validate(_public(row) | {"token": token})
        db.commit()
        return result


def revoke(db: Session, authorization_id: str, context: AuthContext) -> None:
    with _transaction(db):
        owner = bootstrap._current_owner(db, context)
        row = db.scalar(
            select(AppRegistrationAuthorization)
            .where(AppRegistrationAuthorization.id == authorization_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.actor_user_id != owner.user.id:
            service.fail("not_found", 404)
        owner = bootstrap._current_owner(db, context)
        if row.revoked_at is None:
            row.revoked_at = utcnow_naive()
            service._audit(db, owner, "registration.revoke", row.policy["app_id"])
        db.flush()
        bootstrap._current_owner(db, context)
        db.commit()


def _resolve(db: Session, authorization_id: str, authorization: str | None):
    if (
        not authorization
        or not authorization.startswith("Bearer " + TOKEN_PREFIX)
        or len(authorization) > 200
    ):
        service.fail("session_invalid", 401)
    row = db.scalar(
        select(AppRegistrationAuthorization)
        .where(
            AppRegistrationAuthorization.id == authorization_id,
            AppRegistrationAuthorization.token_hash
            == hash_token(authorization.removeprefix("Bearer ")),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.exchanged_at is None:
        service.fail("session_invalid", 401)
    return row, _current(db, row)


def create(
    db: Session,
    authorization_id: str,
    authorization: str | None,
    data: BootstrapInput,
    *,
    platform_origin: str,
):
    with _transaction(db):
        row, context = _resolve(db, authorization_id, authorization)

        def check(payload_digest: str | None) -> None:
            _current(db, row)
            policy = row.policy
            if (
                row.operation_id != str(data.operation_id)
                or data.granted_permissions
                or data.definition.ownership != "personal"
                or policy
                != {
                    "app_id": data.definition.app_id,
                    "origin": data.origin,
                    "runtime_profile": data.definition.runtime_profile,
                    "requested_permissions": sorted(data.definition.requested_permissions),
                }
            ):
                service.fail("forbidden")
            if payload_digest is not None:
                if row.payload_digest is not None and row.payload_digest != payload_digest:
                    service.fail("conflict", 409)
                if row.payload_digest is None:
                    row.payload_digest = payload_digest
                    row.consumed_at = utcnow_naive()

        return bootstrap.create(
            db, data, context, platform_origin=platform_origin, registration_check=check
        )


def receipt(db: Session, authorization_id: str, authorization: str | None):
    try:
        with _transaction(db):
            row, _ = _resolve(db, authorization_id, authorization)
            operation = db.get(AppBootstrapOperation, row.operation_id, populate_existing=True)
            if operation is None or (operation.owner_user_id, operation.app_id) != (
                row.actor_user_id,
                row.policy["app_id"],
            ):
                service.fail("not_found", 404)
            _current(db, row)
            return BootstrapReceipt.model_validate(operation, from_attributes=True)
    finally:
        db.rollback()
