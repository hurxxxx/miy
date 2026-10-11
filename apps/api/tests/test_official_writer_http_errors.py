from types import SimpleNamespace

from sqlalchemy.exc import DBAPIError


def driver_error(state, message, *, legacy_code=False):
    original = Exception("private driver details that must never reach the response")
    original.diag = SimpleNamespace(message_primary=message)
    setattr(original, "pgcode" if legacy_code else "sqlstate", state)
    return DBAPIError("private SQL", {"private": "parameters"}, original)
