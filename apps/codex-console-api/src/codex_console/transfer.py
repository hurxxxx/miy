"""Explicit, verified storage transfer. Never changes the PostgreSQL source."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, MetaData, create_engine, delete, func, inspect, null, select, text
from sqlalchemy.engine import make_url

from .models import Base, database
from .storage import database_path, private_file, process_guard


def canonical(value):
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=UTC).isoformat()
            if value.tzinfo is None
            else value.astimezone(UTC).isoformat()
        )
    if isinstance(value, (bytes, memoryview)):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    raise TypeError("Unsupported database value")


def digest(rows):
    checksum, count = hashlib.sha256(), 0
    for row in rows:
        payload = json.dumps(dict(row), default=canonical, sort_keys=True, separators=(",", ":"))
        checksum.update(payload.encode())
        checksum.update(b"\n")
        count += 1
    return count, checksum.digest()


def backup(url, destination: Path):
    source = database_path(url)
    destination = destination.expanduser().absolute()
    if destination.resolve() != destination or destination == source:
        raise ValueError("Select a new backup file without symlinks")
    os.close(private_file(destination, exclusive=True))
    try:
        # sqlite3's online backup API includes committed WAL content in a consistent image.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(destination)) as writer:
                reader.backup(writer, pages=256)
                if writer.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Backup integrity verification failed")
    except BaseException:
        destination.unlink()
        raise
    return destination


@contextmanager
def stopped_source(source):
    # Session locks must precede the snapshot. Taking transaction locks in a
    # repeatable-read transaction could hide the final writes of a stopping role.
    with source.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        held = []
        try:
            for role in (1, 2, 3):
                if not guard.scalar(
                    text("SELECT pg_try_advisory_lock(18701, :role)"), {"role": role}
                ):
                    raise ValueError(
                        "Stop the old console services before importing their database"
                    )
                held.append(role)
            with (
                source.connect().execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True
                ) as reader,
                reader.begin(),
            ):
                yield reader
        finally:
            for role in reversed(held):
                guard.execute(text("SELECT pg_advisory_unlock(18701, :role)"), {"role": role})


def copy_table(reader, writer, original, table):
    columns = [c.name for c in original.columns]
    json_columns = [name for name in columns if isinstance(table.c[name].type, JSON)]

    def projection(t):
        return select(
            *(t.c[name] for name in columns),
            *(t.c[name].is_(None).label("sql_null_" + name) for name in json_columns),
        )

    count = 0
    # One attachment at a time; event/history tables use a bounded server cursor.
    batch = 1 if table.name == "console_attachments" else 100
    with reader.execution_options(yield_per=batch).execute(projection(original)) as rows:
        for row in rows.mappings():
            values = {name: row[name] for name in columns}
            for name in json_columns:
                if values[name] is None:
                    values[name] = null() if row["sql_null_" + name] else JSON.NULL
            writer.execute(table.insert().values(**values))
            # Match by primary key, independently of PostgreSQL/SQLite collation.
            actual = (
                writer.execute(
                    projection(table).where(
                        *(column == row[column.name] for column in table.primary_key.columns)
                    )
                )
                .mappings()
                .one()
            )
            if digest([actual]) != digest([row]):
                raise ValueError("Imported content differs from its source")
            count += 1
    if writer.scalar(select(func.count()).select_from(table)) != count:
        raise ValueError("Imported row count differs from its source")
    return count


def verify_references(writer):
    tables = Base.metadata.tables
    tasks = tables["console_tasks"]
    for name, table_name in (
        ("approved_revision", "console_revisions"),
        ("current_operation_id", "console_operations"),
    ):
        referenced = tables[table_name]
        owned = (
            select(referenced.c.id)
            .where(referenced.c.id == tasks.c[name], referenced.c.task_id == tasks.c.id)
            .exists()
        )
        if writer.scalar(select(tasks.c.id).where(tasks.c[name].is_not(None), ~owned).limit(1)):
            raise ValueError("Imported task has an invalid owned reference")
    if writer.execute(select(tables["console_workspace_lease"].c.id)).scalars().all() != [1]:
        raise ValueError("Imported database requires its singleton workspace lease")
    if writer.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise ValueError("Imported database has invalid references")
    if writer.exec_driver_sql("PRAGMA integrity_check").all() != [("ok",)]:
        raise ValueError("Imported database integrity verification failed")


def import_postgres(source_url, destination_url):
    from .cli import migrate

    if make_url(source_url).drivername != "postgresql+psycopg":
        raise ValueError("The source must be the existing dedicated PostgreSQL console database")
    path = database_path(destination_url)
    if path.exists():
        raise ValueError("Import requires a new SQLite file; existing data is never overwritten")
    source = create_engine(source_url, hide_parameters=True)
    staging = path.with_name(path.name + ".import-" + uuid4().hex)
    staging_url = make_url(destination_url).set(database=str(staging)).render_as_string()
    target = None
    try:
        with stopped_source(source) as reader:
            versions = (
                reader.execute(text("SELECT version_num FROM console_alembic_version"))
                .scalars()
                .all()
            )
            if len(versions) != 1 or versions[0] not in (
                "console_0009",
                "console_0010",
                "console_0011",
            ):
                raise ValueError("Import supports PostgreSQL console_0009 through console_0011")
            revision = versions[0]
            names = set(inspect(reader).get_table_names()) - {"console_alembic_version"}
            expected = set(Base.metadata.tables) - {
                "console_projects",
                "console_maintenance",
                "console_app_budgets",
                "console_app_sources",
                "console_app_source_setups",
                "console_registration_intents",
                "console_development_usage",
                "console_development_usage_months",
                "console_workbench_observations",
            }
            if revision == "console_0009":
                expected -= {"console_templates", "console_host_observations"}
            if names != expected:
                raise ValueError(
                    "Unexpected source schema; import stopped without changing the source"
                )
            legacy = MetaData()
            legacy.reflect(bind=reader, only=sorted(names))
            for name in names:
                expected_columns = set(Base.metadata.tables[name].c.keys())
                if name == "console_agents":
                    expected_columns -= {"observation"}
                if name == "console_tasks" and revision == "console_0009":
                    expected_columns -= {"executor", "template_snapshot", "launch_id"}
                if set(legacy.tables[name].c.keys()) != expected_columns:
                    raise ValueError("Unexpected source columns")
            # Verify an unchanged copy first, then apply local data migrations.
            migrate(staging_url, revision="console_sqlite_0001")
            target, _ = database(staging_url)
            counts = {}
            with (
                process_guard(staging_url),
                target.connect().execution_options(console_write=True) as writer,
                writer.begin(),
            ):
                writer.execute(delete(Base.metadata.tables["console_workspace_lease"]))
                for table in Base.metadata.sorted_tables:
                    if table.name in names:
                        counts[table.name] = copy_table(
                            reader, writer, legacy.tables[table.name], table
                        )
                verify_references(writer)
            target.dispose()
            target = None
            migrate(staging_url)
            target, _ = database(staging_url)
            # Explicit checkpoint before publishing the main file without its WAL.
            with target.connect() as checkpointer:
                busy, remaining, copied = checkpointer.exec_driver_sql(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).one()
                if busy or remaining != copied:
                    raise ValueError("Imported database checkpoint did not complete")
            target.dispose()
            target = None
            # Same filesystem, exclusive atomic publication. Failed imports never
            # become usable databases and an existing destination is never replaced.
            os.link(staging, path)
            staging.unlink()
            return counts
    finally:
        if target is not None:
            target.dispose()
        source.dispose()
        for suffix in ("", "-wal", "-shm", ".session.lock", ".management.lock", ".templates.lock"):
            staging.with_name(staging.name + suffix).unlink(missing_ok=True)
