"""Conservative PostgreSQL commit rejection proof for object compensation."""

import psycopg
from sqlalchemy.exc import DBAPIError


def commit_was_rejected(exc: Exception) -> bool:
    """Unknown results never authorize deleting an object a commit may reference."""
    return (
        isinstance(exc, DBAPIError)
        and not exc.connection_invalidated
        and isinstance(exc.orig, psycopg.Error)
        # Never classify whole class 40: it includes completion_unknown 40003.
        and exc.orig.sqlstate in {"23502", "23503", "23505", "23514", "23P01", "40001", "40P01"}
    )
