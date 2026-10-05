"""Local SQLite transactions and process ownership for the standalone console.

SQLAlchemy's documented connect/begin hooks opt out of sqlite3 legacy transaction
control. Read sessions use snapshot transactions; factory.begin() reserves the
single writer before reading, so admission and approvals cannot race.
"""

import fcntl
import os
import sqlite3
import stat
from contextlib import ExitStack, contextmanager
from datetime import UTC
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator

SCHEMA = "console_sqlite_0003"


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Console timestamps must include a timezone")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def database_path(url):
    parsed = make_url(url)
    path = Path(parsed.database or "")
    if (
        parsed.drivername != "sqlite+pysqlite"
        or parsed.host
        or parsed.username
        or parsed.password
        or parsed.query
        or not path.is_absolute()
        or path.resolve() != path
    ):
        raise ValueError("Use an absolute local sqlite+pysqlite database path without symlinks")
    return path


def private_file(path, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags | (os.O_EXCL if exclusive else 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("Console storage must be a private regular file owned by the service user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise ValueError("Console storage files require mode 0600")
    return fd


@contextmanager
def process_guard(url, role="combined"):
    """OS locks survive UI restarts and are released by the kernel after a crash."""
    path = database_path(url)
    roles = ("session", "management", "templates") if role == "combined" else (role,)
    if any(r not in ("session", "management", "templates") for r in roles):
        raise ValueError("Unknown console service role")
    with ExitStack() as stack:
        for name in roles:
            fd = private_file(path.with_name(path.name + "." + name + ".lock"))
            stack.callback(os.close, fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(
                    "Run exactly one console process per role and database"
                ) from None
        yield


class ConsoleSessions(sessionmaker):
    @contextmanager
    def begin(self):
        with self() as session, session.begin():
            session.connection(execution_options={"console_write": True})
            yield session


def database(url):
    path = database_path(url)
    # Multiple processes share WAL. Require the upstream WAL-reset fix rather than
    # introducing a second write/checkpoint scheduler around an affected library.
    version = sqlite3.sqlite_version_info
    if not (
        version >= (3, 51, 3)
        or (3, 50, 7) <= version < (3, 51, 0)
        or (3, 44, 6) <= version < (3, 45, 0)
    ):
        raise RuntimeError("SQLite with the WAL-reset fix is required (3.51.3+ recommended)")
    os.close(private_file(path))
    engine = create_engine(url, hide_parameters=True, connect_args={"timeout": 5})

    @event.listens_for(engine, "connect")
    def connect(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA busy_timeout=5000")
        if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            raise RuntimeError("SQLite WAL mode is required")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql(
            "BEGIN IMMEDIATE"
            if connection.get_execution_options().get("console_write")
            else "BEGIN"
        )

    return engine, ConsoleSessions(engine, expire_on_commit=False)
