import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import new_task, send_message
from sqlalchemy import select, text

from codex_console import auth, store
from codex_console.errors import ConsoleError
from codex_console.models import Agent, Attachment, ResourceLease, Task, database
from codex_console.storage import database_path, process_guard
from codex_console.transfer import backup, import_postgres


def _claim(url, task_id, start, result, *, limit=1, stage="implement"):
    engine, factory = database(url)
    start.wait(10)
    try:
        with factory.begin() as db:
            store.lease(db, task_id, workspace=db.get(Task, task_id).root, limit=limit, stage=stage)
        result.put("accepted")
    except ConsoleError as exc:
        result.put(exc.code)
    finally:
        engine.dispose()


def test_separate_processes_cannot_exceed_shared_resource_capacity(client):
    tasks = [new_task(client, str(i)) for i in range(2)]
    ctx = multiprocessing.get_context("spawn")
    start, result = ctx.Event(), ctx.Queue()
    processes = [
        ctx.Process(
            target=_claim, args=(client.app.state.settings.database_url, t["id"], start, result)
        )
        for t in tasks
    ]
    for process in processes:
        process.start()
    try:
        start.set()
        assert sorted([result.get(timeout=15), result.get(timeout=15)]) == [
            "accepted",
            "capacity_busy",
        ]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def test_read_snapshot_does_not_block_a_writer_and_is_consistent(client):
    task = new_task(client)
    factory = client.app.state.factory
    with factory() as reader:
        assert reader.scalar(select(Task.title).where(Task.id == task["id"])) == task["title"]

        def update():
            with factory.begin() as writer:
                writer.get(Task, task["id"]).title = "Updated"

        with ThreadPoolExecutor() as executor:
            executor.submit(update).result(timeout=3)
        assert reader.scalar(select(Task.title).where(Task.id == task["id"])) == task["title"]
    assert client.get(f"/api/tasks/{task['id']}").json()["title"] == "Updated"


def test_eight_processes_cannot_overbook_parallel_readers(client):
    tasks = [new_task(client, str(i)) for i in range(8)]
    ctx = multiprocessing.get_context("spawn")
    start, result = ctx.Event(), ctx.Queue()
    processes = [
        ctx.Process(
            target=_claim,
            args=(client.app.state.settings.database_url, task["id"], start, result),
            kwargs={"limit": 3, "stage": "plan"},
        )
        for task in tasks
    ]
    for process in processes:
        process.start()
    try:
        start.set()
        responses = [result.get(timeout=30) for _ in tasks]
        assert responses.count("accepted") == 3
        assert responses.count("capacity_busy") == 5
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        with client.app.state.factory() as db:
            leases = list(db.scalars(select(ResourceLease)))
            assert len(leases) == 3 and not any(row.exclusive for row in leases)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def _crash_writer(url, task_id):
    _, factory = database(url)
    with process_guard(url, "session"), factory.begin() as db:
        db.get(Task, task_id).title = "Uncommitted change"
        db.flush()
        os._exit(17)


def test_killed_writer_rolls_back_and_releases_its_service_guard(client):
    task = new_task(client)
    url = client.app.state.settings.database_url
    # Crash against an independently backed-up DB; the fixture owns the original's roles.
    path = database_path(url).with_name("crash.sqlite3")
    backup(url, path)
    crash_url = "sqlite+pysqlite:///" + str(path)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_writer, args=(crash_url, task["id"])
    )
    process.start()
    try:
        process.join(timeout=15)
        assert process.exitcode == 17
        with process_guard(crash_url, "session"):
            engine, factory = database(crash_url)
            try:
                with factory() as db:
                    assert db.get(Task, task["id"]).title == task["title"]
                    assert db.scalar(text("PRAGMA integrity_check")) == "ok"
                with factory.begin() as db:
                    db.get(Task, task["id"]).title = "Recovered writer"
                with factory() as db:
                    assert db.get(Task, task["id"]).title == "Recovered writer"
            finally:
                engine.dispose()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_backup_restores_owner_session_task_and_binary_attachment(client, tmp_path):
    task = new_task(client)
    from uuid import uuid4

    attachment_id = str(uuid4())
    content = b"binary\x00attachment"
    response = client.put(
        f"/api/tasks/{task['id']}/attachments/{attachment_id}",
        content=content,
        headers={"content-type": "application/octet-stream", "x-file-name": "evidence.bin"},
    )
    assert response.status_code == 200
    path = backup(client.app.state.settings.database_url, tmp_path / "backup.sqlite3")
    assert path.stat().st_mode & 0o077 == 0
    engine, factory = database("sqlite+pysqlite:///" + str(path))
    try:
        assert auth.authenticate(
            factory, client.cookies[auth.COOKIE], client.cookies[auth.CSRF_COOKIE]
        )
        with factory() as db:
            assert db.get(Task, task["id"]).title == task["title"]
            assert db.get(Attachment, attachment_id).content == content
        with pytest.raises(FileExistsError):
            backup(client.app.state.settings.database_url, path)
    finally:
        engine.dispose()


def test_service_role_locks_exclude_duplicates_and_combined_mode(database_url):
    with process_guard(database_url, "templates"), process_guard(database_url, "management"):
        with pytest.raises(RuntimeError):
            with process_guard(database_url, "templates"):
                pass
        with pytest.raises(RuntimeError):
            with process_guard(database_url):
                pass
    with process_guard(database_url):
        pass


@pytest.mark.parametrize("revision", ["console_0009", "console_0010", "console_0011"])
def test_postgres_import_preserves_data_and_refuses_overwrite(
    client, legacy_database, tmp_path, revision
):
    from sqlalchemy import text

    task = send_message(client, new_task(client)).json()
    engine = legacy_database()
    if revision == "console_0009":
        with engine.begin() as db:
            db.execute(text("DROP TABLE console_templates, console_host_observations"))
            db.execute(
                text(
                    "ALTER TABLE console_tasks DROP COLUMN executor, "
                    "DROP COLUMN template_snapshot, DROP COLUMN launch_id"
                )
            )
            db.execute(text("UPDATE console_alembic_version SET version_num='console_0009'"))
    path = tmp_path / "imported.sqlite3"
    url = "sqlite+pysqlite:///" + str(path)
    source = engine.url.render_as_string(hide_password=False)
    if revision == "console_0010":
        from alembic import command
        from alembic.config import Config

        from codex_console.cli import ROOT

        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["database_url"] = source
        command.downgrade(config, revision)
    try:
        counts = import_postgres(source, url)
        assert counts["console_tasks"] == 1
        imported, factory = database(url)
        try:
            assert auth.authenticate(
                factory, client.cookies[auth.COOKIE], client.cookies[auth.CSRF_COOKIE]
            )
            with factory() as db:
                saved = db.get(Task, task["id"])
                assert saved.thread_id == task["thread_id"] and saved.executor == "session"
                assert db.get(Agent, task["thread_id"]).observation is None
            with pytest.raises(ValueError, match="new SQLite"):
                import_postgres(source, url)
        finally:
            imported.dispose()
    finally:
        if revision != "console_0011":
            from codex_console.cli import migrate

            migrate(source)


def test_postgres_import_requires_stopped_services(client, legacy_database, tmp_path):
    from sqlalchemy import text

    engine = legacy_database()
    path = tmp_path / "blocked.sqlite3"
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(18701, 2)"))
        with pytest.raises(ValueError, match="Stop the old"):
            import_postgres(
                engine.url.render_as_string(hide_password=False), "sqlite+pysqlite:///" + str(path)
            )
    assert not path.exists()


def test_storage_rejects_symlinks_and_public_files(tmp_path):
    original = tmp_path / "original.sqlite3"
    original.touch(mode=0o600)
    linked = tmp_path / "linked.sqlite3"
    linked.symlink_to(original)
    with pytest.raises(ValueError):
        database_path("sqlite+pysqlite:///" + str(linked))
    os.chmod(original, 0o644)
    with pytest.raises(ValueError, match="0600"):
        database("sqlite+pysqlite:///" + str(original))


def test_failed_import_never_publishes_partial_data_and_can_retry(
    client, legacy_database, tmp_path, monkeypatch
):
    from codex_console import transfer

    new_task(client)
    engine = legacy_database()
    source = engine.url.render_as_string(hide_password=False)
    path = tmp_path / "retry.sqlite3"
    url = "sqlite+pysqlite:///" + str(path)
    original = transfer.verify_references

    def fail_after_copy(_):
        raise ValueError("Injected final verification failure")

    monkeypatch.setattr(transfer, "verify_references", fail_after_copy)
    with pytest.raises(ValueError, match="Injected"):
        import_postgres(source, url)
    assert not list(tmp_path.glob("retry.sqlite3*"))
    monkeypatch.setattr(transfer, "verify_references", original)
    assert import_postgres(source, url)["console_tasks"] == 1


def test_import_snapshot_includes_commits_before_last_service_lock(
    client, legacy_database, tmp_path, monkeypatch
):
    from sqlalchemy import event, text

    from codex_console import transfer

    task = new_task(client)
    engine = legacy_database()
    changed = False

    def stopping_service(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal changed
        if "pg_try_advisory_lock" in statement and not changed:
            changed = True
            with engine.begin() as writer:
                writer.execute(
                    text("UPDATE console_tasks SET title='Final service write' WHERE id=:id"),
                    {"id": task["id"]},
                )

    event.listen(engine, "after_cursor_execute", stopping_service)
    monkeypatch.setattr(transfer, "create_engine", lambda *_args, **_kwargs: engine)
    url = "sqlite+pysqlite:///" + str(tmp_path / "snapshot.sqlite3")
    try:
        import_postgres(engine.url.render_as_string(hide_password=False), url)
        imported, factory = database(url)
        try:
            with factory() as db:
                assert db.get(Task, task["id"]).title == "Final service write"
        finally:
            imported.dispose()
    finally:
        event.remove(engine, "after_cursor_execute", stopping_service)


def test_import_preserves_sql_null_json_null_and_binary(client, legacy_database, tmp_path):
    from uuid import uuid4

    from sqlalchemy import text

    first, second = new_task(client), new_task(client)
    attachment_id = str(uuid4())
    client.put(
        f"/api/tasks/{first['id']}/attachments/{attachment_id}",
        content=b"\x00\xffbinary",
        headers={"content-type": "application/octet-stream", "x-file-name": "evidence.bin"},
    ).raise_for_status()
    engine = legacy_database()
    with engine.begin() as db:
        db.execute(text("UPDATE console_tasks SET context=NULL WHERE id=:id"), {"id": first["id"]})
        db.execute(
            text("UPDATE console_tasks SET context='null'::json WHERE id=:id"), {"id": second["id"]}
        )
    url = "sqlite+pysqlite:///" + str(tmp_path / "nulls.sqlite3")
    import_postgres(engine.url.render_as_string(hide_password=False), url)
    imported, factory = database(url)
    try:
        with factory() as db:
            assert db.scalar(select(Task.context.is_(None)).where(Task.id == first["id"]))
            assert not db.scalar(select(Task.context.is_(None)).where(Task.id == second["id"]))
            assert db.get(Attachment, attachment_id).content == b"\x00\xffbinary"
    finally:
        imported.dispose()


@pytest.mark.parametrize("damage", ["missing_column", "missing_lease", "foreign_operation"])
def test_import_refuses_incomplete_schema_or_invalid_owned_references(
    client, legacy_database, tmp_path, damage
):
    from sqlalchemy import text

    first = send_message(client, new_task(client)).json()
    second = new_task(client)
    engine = legacy_database()
    with engine.begin() as db:
        if damage == "missing_column":
            db.execute(text("ALTER TABLE console_tasks RENAME COLUMN pinned TO unknown_column"))
        elif damage == "missing_lease":
            db.execute(text("DELETE FROM console_workspace_lease"))
        else:
            db.execute(
                text(
                    "UPDATE console_tasks SET current_operation_id="
                    "(SELECT current_operation_id FROM console_tasks WHERE id=:first) "
                    "WHERE id=:second"
                ),
                {"first": first["id"], "second": second["id"]},
            )
    path = tmp_path / "invalid.sqlite3"
    try:
        with pytest.raises(ValueError):
            import_postgres(
                engine.url.render_as_string(hide_password=False), "sqlite+pysqlite:///" + str(path)
            )
    finally:
        if damage == "missing_column":
            with engine.begin() as db:
                db.execute(text("ALTER TABLE console_tasks RENAME COLUMN unknown_column TO pinned"))
    assert not list(tmp_path.glob("invalid.sqlite3*"))
