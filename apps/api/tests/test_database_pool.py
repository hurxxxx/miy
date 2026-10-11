from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from miy_api.core import db


def test_request_cleanup_returns_connection_on_success_and_error(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'request.db'}")
    monkeypatch.setattr(db, "_configured_engine", None)
    db.configure_database_engine(engine)
    request = db.get_db_session()
    try:
        session = next(request)
        assert session.scalar(text("SELECT 1")) == 1
        assert engine.pool.checkedout() == 1
        with pytest.raises(StopIteration):
            next(request)
        assert engine.pool.checkedout() == 0
        request = db.get_db_session()
        session = next(request)
        assert session.scalar(text("SELECT 1")) == 1
        assert engine.pool.checkedout() == 1
        with pytest.raises(ValueError, match="request failed"):
            request.throw(ValueError("request failed"))
        assert engine.pool.checkedout() == 0
    finally:
        request.close()
        engine.dispose()
        db.get_engine.cache_clear()
        db.get_session_factory.cache_clear()
