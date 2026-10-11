"""Acquire the actual source trigger fence before a source-owned external effect."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.core.db import official_writer_unavailable
from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES


def lock_source_writer(db: Session, source_table: str) -> None:
    """Hold the same source writer SHARE lock until caller commit/rollback.

    No row is modified and no identity is discovered or adopted. Both legacy
    and hardened role modes use their existing trigger and exact generation.
    This does not cover an effect performed after this transaction ends.
    Call only after the original source ACL; this grants no user authority.
    """
    if source_table not in COVERED_SOURCE_TABLES:
        raise ValueError("Official source must be explicitly catalogued")
    with db.no_autoflush:
        if (
            db.connection().connection.driver_connection.autocommit
            or db.scalar(text("SELECT current_setting('transaction_isolation')"))
            != "read committed"
        ):
            raise official_writer_unavailable()
        # source_table is a core-owned fixed identifier, never caller SQL.
        # BEFORE STATEMENT executes even for zero rows; the trigger retains its
        # actual ownership/role SHARE locks through the caller's transaction.
        db.execute(text(f"UPDATE public.{source_table} SET writer_scope=writer_scope WHERE false"))
