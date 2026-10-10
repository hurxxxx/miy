"""Preflight for the explicit first-party shared-database compatibility runtime.

This does not prepare roles, discover/adopt a generation, or activate the
delegated Source-only artifact. Existing source transactions and server ACL
remain authoritative. The deployed migration/seed job has one owner.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from miy_api.api_composition import ApiComposition, require_composition
from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import AuthSession, User
from miy_api.domains.docs.collab import DOCS_WRITER_IDENTITY
from miy_api.domains.official_apps.writer import require_active_writer
from miy_api.domains.official_apps.writer_roles import WriterControlError, _source_guard


def require_first_party_database(*, composition: ApiComposition) -> None:
    selected = require_composition(composition)
    if selected == "legacy":
        raise ValueError("First-party database preflight requires one service owner")
    try:
        with get_session_factory()() as db:
            if db.get_bind().dialect.name != "postgresql":
                raise RuntimeError("first_party_postgresql_required")
            if db.connection().connection.driver_connection.autocommit:
                raise RuntimeError("first_party_transaction_required")
            db.execute(select(1))
            db.execute(select(User.id).limit(0))
            db.execute(select(AuthSession.id).limit(0))
            if selected == "official":
                # Existing Docs persistence and every source trigger retain this
                # fixed legacy identity. A different/draining owner cannot be
                # adopted at startup or recovered through a role fallback.
                require_active_writer(db, DOCS_WRITER_IDENTITY)
                _source_guard(db)
    except (HTTPException, SQLAlchemyError, WriterControlError):
        raise RuntimeError("first_party_database_not_compatible") from None
