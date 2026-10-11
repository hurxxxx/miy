from types import SimpleNamespace
from unittest.mock import Mock, call

from fastapi import HTTPException
import pytest
from sqlalchemy.exc import DBAPIError

from miy_api.core import db as db_module
from miy_api.core.i18n import LocalizedApiMessage


def driver_error(state, message, *, legacy_code=False):
    original = Exception("private driver details that must never reach the response")
    original.diag = SimpleNamespace(message_primary=message)
    setattr(original, "pgcode" if legacy_code else "sqlstate", state)
    return DBAPIError("private SQL", {"private": "parameters"}, original)


@pytest.mark.parametrize("message", ["official_writer_fenced", "official_writer_control_missing"])
@pytest.mark.parametrize("legacy_code", [False, True])
def test_exact_guard_error_rolls_back_before_closing_and_uses_existing_localized_envelope(
    monkeypatch, message, legacy_code
):
    session = Mock()
    monkeypatch.setattr(db_module, "get_session_factory", lambda: lambda: session)
    dependency = db_module.get_db_session()
    assert next(dependency) is session
    with pytest.raises(HTTPException) as denied:
        dependency.throw(driver_error("55000", message, legacy_code=legacy_code))
    assert session.method_calls == [call.rollback(), call.close()]
    assert denied.value.status_code == 503
    assert denied.value.detail == LocalizedApiMessage(code="official_apps.writer_unavailable")
    assert denied.value.headers == {
        "X-MIY-Error-Code": "official_apps.writer_unavailable",
        "Retry-After": "5",
    }
    assert denied.value.__suppress_context__


@pytest.mark.parametrize(
    "error",
    [
        driver_error("23505", "official_writer_fenced"),
        driver_error("55000", "unrelated prerequisite error"),
        driver_error("55000", "official_writer_fenced: private details"),
        driver_error(None, "official_writer_fenced"),
        DBAPIError("private SQL", {}, Exception("official_writer_fenced")),
        RuntimeError("unrelated application failure"),
    ],
)
def test_other_database_and_application_errors_propagate_unchanged(monkeypatch, error):
    session = Mock()
    monkeypatch.setattr(db_module, "get_session_factory", lambda: lambda: session)
    dependency = db_module.get_db_session()
    next(dependency)
    with pytest.raises(type(error)) as actual:
        dependency.throw(error)
    assert actual.value is error
    # Preserve the existing cleanup contract for unrecognized failures.
    assert session.method_calls == [call.close()]
