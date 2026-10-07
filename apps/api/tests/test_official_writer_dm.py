"""DM's four source tables and accepted attachment transaction share one writer."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import psycopg
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import select, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from miy_api.domains.auth.models import AuthSession, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.dm import attachment_persistence, attachment_storage, router as dm_router
from miy_api.domains.official_apps import writer_roles
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
from miy_api.domains.dm.models import (
    DmConversation,
    DmConversationParticipant,
    DmMessage,
    DmMessageAttachment,
)
from test_official_writer_fence import change, writer as writer
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    ACTIVE,
    BASE,
    activate,
    denied,
    move,
    prepare,
    sa_dsn,
    wait_for_blocker,
    role_template as role_template,
    world as world,
)

MODELS = (DmConversation, DmConversationParticipant, DmMessage, DmMessageAttachment)
SOURCES = tuple(model.__tablename__ for model in MODELS)
REVISION = "official_dm_writer_20261007"
PREVIOUS = "registration_auth_20261007"
OLD_SOURCES = tuple(
    ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module._EXISTING_SOURCES
)


class Objects:
    def __init__(self):
        self.values = {}
        self.puts = []
        self.removes = []

    def put(self, *, storage_key, content, size_bytes, content_type):
        self.values[storage_key] = content.read()
        self.puts.append(storage_key)

    def remove(self, *, storage_key):
        self.removes.append(storage_key)
        self.values.pop(storage_key, None)


def snapshot(factory):
    with factory() as db:
        return {
            model.__tablename__: sorted(
                [tuple(row) for row in db.execute(select(model.__table__))], key=repr
            )
            for model in MODELS
        }


@pytest.fixture
def dm(client, writer, monkeypatch):
    factory, admin, _ = writer
    peers = []
    with factory.begin() as db:
        for index in range(3):
            user_id, token = str(uuid4()), "dm-fixture-" + uuid4().hex
            db.add(
                User(
                    id=user_id,
                    login_id=user_id,
                    email=f"{user_id}@example.test",
                    full_name=f"Peer {index}",
                    password_hash="synthetic",
                )
            )
            db.flush()
            db.add(
                AuthSession(
                    id=str(uuid4()),
                    user_id=user_id,
                    token_hash=hash_token(token),
                    expires_at=utcnow_naive() + timedelta(hours=1),
                )
            )
            peers.append({"id": user_id, "headers": {"Authorization": "Bearer " + token}})
    headers = {"Authorization": "Bearer " + admin["token"]}
    events, objects = Mock(), Objects()
    monkeypatch.setattr(dm_router, "_dm_events", lambda *args: events)
    monkeypatch.setattr(attachment_storage, "dm_attachment_storage", lambda: objects)
    response = client.post(
        "/api/v1/dm/conversations",
        headers=headers,
        json={"participant_user_ids": [p["id"] for p in peers[:2]], "title": "Original"},
    )
    assert response.status_code == 201, response.text
    base = "/api/v1/dm/conversations/" + response.json()["id"]
    message = client.post(
        base + "/messages", headers=peers[0]["headers"], json={"body": "Original message"}
    )
    assert message.status_code == 200, message.text
    attachment = client.post(
        base + "/attachments",
        headers=headers,
        files={"file": ("synthetic.txt", b"synthetic", "text/plain")},
    )
    assert attachment.status_code == 201, attachment.text
    events.reset_mock()
    return SimpleNamespace(
        factory=factory,
        admin=admin,
        headers=headers,
        peers=peers,
        base=base,
        attachment=attachment.json(),
        events=events,
        objects=objects,
    )


@pytest.mark.parametrize(
    "operation",
    ["direct", "group", "rename", "add", "remove", "leave", "rejoin", "send", "read", "upload"],
)
def test_dm_drain_rejects_mutation_without_partial_rows_or_external_effects(client, dm, operation):
    if operation == "rejoin":
        response = client.delete(dm.base + "/participants/me", headers=dm.peers[0]["headers"])
        assert response.status_code == 204
    before = snapshot(dm.factory)
    original_objects = dict(dm.objects.values)
    puts = len(dm.objects.puts)
    dm.events.reset_mock()
    with dm.factory.begin() as db:
        change(db, dm.admin)
    method, path, body, headers = "POST", dm.base, {}, dm.headers
    if operation == "direct":
        path, body = "/api/v1/dm/conversations", {"recipient_user_id": dm.peers[2]["id"]}
    elif operation == "group":
        path, body = (
            "/api/v1/dm/conversations",
            {"participant_user_ids": [p["id"] for p in dm.peers[1:]], "title": "Blocked"},
        )
    elif operation == "rename":
        method, body = "PATCH", {"title": "Blocked"}
    elif operation in {"add", "rejoin"}:
        path, body = (
            dm.base + "/participants",
            {"user_ids": [dm.peers[0 if operation == "rejoin" else 2]["id"]]},
        )
    elif operation == "remove":
        method, path = "DELETE", dm.base + "/participants/" + dm.peers[0]["id"]
    elif operation == "leave":
        method, path, headers = "DELETE", dm.base + "/participants/me", dm.peers[0]["headers"]
    elif operation == "send":
        path, body = (
            dm.base + "/messages",
            {"body": "Blocked", "attachment_ids": [dm.attachment["id"]]},
        )
    elif operation == "read":
        method, path = "PATCH", dm.base + "/read"
    else:
        path = dm.base + "/attachments"
    response = client.request(
        method,
        path,
        headers=headers,
        **(
            {"files": {"file": ("blocked.txt", b"blocked", "text/plain")}}
            if operation == "upload"
            else {"json": body}
        ),
    )
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "official_apps.writer_unavailable"
    assert response.headers["Retry-After"] == "5"
    assert snapshot(dm.factory) == before
    assert dm.objects.values == original_objects and len(dm.objects.puts) == puts
    assert not dm.events.mock_calls
    assert client.get(dm.base + "/messages", headers=dm.headers).status_code == 200


def test_dm_exact_existing_direct_read_during_drain_does_not_create_participants(client, dm):
    body = {"recipient_user_id": dm.peers[0]["id"]}
    first = client.post("/api/v1/dm/conversations", headers=dm.headers, json=body)
    assert first.status_code == 201
    before = snapshot(dm.factory)
    with dm.factory.begin() as db:
        change(db, dm.admin)
    again = client.post("/api/v1/dm/conversations", headers=dm.headers, json=body)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert snapshot(dm.factory) == before
    # A caller outside the group still cannot read during drain.
    denied_read = client.get(dm.base + "/messages", headers=dm.peers[2]["headers"])
    assert denied_read.status_code == 404


def seed(conn, user_id):
    conn.execute(
        "INSERT INTO dm_conversations(id,conversation_type,title,created_by_id,message_seq,created_at,updated_at) VALUES ('dm-conversation','group','Original',%s,1,now(),now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_conversation_participants(id,conversation_id,user_id,role,joined_at,created_at) VALUES ('dm-member','dm-conversation',%s,'owner',now(),now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_messages(id,conversation_id,sequence,sender_id,body,created_at) VALUES ('dm-message','dm-conversation',1,%s,'Original message',now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_message_attachments(id,conversation_id,message_id,uploader_id,filename,content_type,size_bytes,storage_key,created_at) VALUES ('dm-attachment','dm-conversation','dm-message',%s,'Original.txt','text/plain',9,'dm/synthetic/original',now())",
        [user_id],
    )
    conn.execute("UPDATE dm_conversation_participants SET last_read_message_id='dm-message'")


def contents(conn):
    return {
        table: conn.execute(
            f"SELECT to_jsonb(row)-'writer_scope' FROM {table} row ORDER BY id"
        ).fetchall()
        for table in SOURCES
    }


def old_schema(world):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)


def assert_revision(world, revision, *, fenced):
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
    for table in SOURCES:
        assert (
            "writer_scope" in {c["name"] for c in inspect(world.engine).get_columns(table)}
        ) is fenced


def test_dm_migration_preserves_all_four_sources_constraints_and_rollback(world):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    config = _migration_config(sa_dsn(world.dsn))
    command.upgrade(config, REVISION)
    assert_revision(world, REVISION, fenced=True)
    with world.connect() as conn:
        assert contents(conn) == before
        for table in SOURCES:
            assert conn.execute(f"SELECT writer_scope FROM {table}").fetchone()[0] == SUITE_SCOPE
            denied(conn, f"UPDATE {table} SET writer_scope='other'", "23514")
    schema = inspect(world.engine)
    for table in SOURCES:
        assert any(
            fk["constrained_columns"] == ["writer_scope"]
            and fk["referred_table"] == "official_runtime_ownership"
            for fk in schema.get_foreign_keys(table)
        )
    command.downgrade(config, PREVIOUS)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before
    command.upgrade(config, REVISION)
    with world.connect() as conn:
        assert contents(conn) == before


@pytest.mark.parametrize("table", SOURCES)
def test_dm_raw_statements_copy_truncate_and_stale_generation_are_fenced(world, table):
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    draining = move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        for statement in (
            f"INSERT INTO {table} DEFAULT VALUES",
            f"UPDATE {table} SET writer_scope=writer_scope WHERE false",
            f"DELETE FROM {table}",
            f"TRUNCATE {table} CASCADE",
        ):
            denied(conn, statement, "55000")
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction(), conn.cursor().copy(f"COPY {table}(id) FROM STDIN") as stream:
                stream.write_row(("blocked",))
        assert error.value.sqlstate == "55000" and contents(conn) == before
    active = move(world, draining, "draining", state="active")
    with world.connect() as conn:
        denied(conn, f"UPDATE {table} SET writer_scope=writer_scope WHERE false", "55000")
        conn.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            [
                '{"scope":"official.suite","owner":"legacy","generation":%d,"artifact":null}'
                % active.generation
            ],
        )
        conn.execute(f"UPDATE {table} SET writer_scope=writer_scope WHERE false")


def test_dm_late_statement_failure_rolls_back_preceding_changes_in_all_four_sources(world):
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    with Session(world.engine) as db:
        db.get(DmConversation, "dm-conversation").title = "Uncommitted"
        db.get(DmConversationParticipant, "dm-member").muted_at = utcnow_naive()
        db.get(DmMessage, "dm-message").body = "Uncommitted"
        db.get(DmMessageAttachment, "dm-attachment").filename = "Uncommitted.txt"
        db.flush()
        # A privileged legacy assertion mismatch on a later statement must abort
        # earlier real DML as well; no ORM-only compensation is involved.
        db.execute(
            text("SELECT set_config('miy.official_writer', :identity, true)"),
            {
                "identity": '{"scope":"official.suite","owner":"legacy","generation":99,"artifact":null}'
            },
        )
        with pytest.raises(DBAPIError) as error:
            db.execute(text("UPDATE dm_messages SET body=body WHERE false"))
        assert error.value.orig.sqlstate == "55000"
        db.rollback()
    with world.connect() as conn:
        assert contents(conn) == before


@pytest.mark.parametrize("outcome", ["commit", "storage_failure", "commit_failure"])
def test_dm_attachment_holds_writer_until_storage_transaction_settles(world, outcome):
    with world.connect() as conn:
        seed(conn, world.user_id)
        if outcome == "commit_failure":
            # A real server rejection at COMMIT, after successful flush and put.
            foreign_key = conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid='dm_message_attachments'::regclass "
                "AND confrelid='dm_messages'::regclass"
            ).fetchone()[0]
            conn.execute(
                psycopg.sql.SQL(
                    "ALTER TABLE dm_message_attachments ALTER CONSTRAINT {} DEFERRABLE INITIALLY DEFERRED"
                ).format(psycopg.sql.Identifier(foreign_key))
            )
    entered, release = Event(), Event()
    objects = Objects()
    upload_pid = []
    finished_counts = []

    class Storage:
        def put(self, **kwargs):
            entered.set()
            # The blocker probe may use eight seconds. It must finish before
            # this test-owned storage gate times out and releases the DB lock.
            assert release.wait(15)
            if outcome == "storage_failure":
                raise OSError("synthetic object write failure")
            objects.put(**kwargs)

        def remove(self, **kwargs):
            objects.remove(**kwargs)

    def upload():
        with Session(world.engine) as db:
            upload_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            row = DmMessageAttachment(
                id="new-attachment",
                conversation_id="dm-conversation",
                message_id="missing-message" if outcome == "commit_failure" else None,
                uploader_id=world.user_id,
                filename="new.txt",
                content_type="text/plain",
                size_bytes=3,
                storage_key="dm/synthetic/new",
            )

            def call():
                return attachment_persistence.persist_created_attachment(
                    db,
                    row=row,
                    object_write=attachment_persistence.DmAttachmentObjectWrite(
                        storage_key=row.storage_key,
                        content=BytesIO(b"new"),
                        size_bytes=3,
                        content_type="text/plain",
                    ),
                    object_storage=Storage(),
                )

            if outcome == "commit":
                call()
            else:
                with pytest.raises(HTTPException) as error:
                    call()
                assert error.value.status_code == (502 if outcome == "storage_failure" else 500)
                if outcome == "commit_failure":
                    assert error.value.detail.code == "dm.attachment_save_failed"
            finished_counts.append(True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(upload)
        pending = None
        try:
            assert entered.wait(5)
            pending = pool.submit(move, world, BASE, "active", state="draining")
            wait_for_blocker(world, upload_pid[0])
            assert not pending.done() and not finished_counts
        finally:
            release.set()
        writing.result(timeout=8)
        assert pending.result(timeout=8).generation == 2
    with world.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM dm_message_attachments WHERE id='new-attachment'"
        ).fetchall()
        assert bool(rows) is (outcome == "commit")
        assert (
            conn.execute(
                "SELECT filename FROM dm_message_attachments WHERE id='dm-attachment'"
            ).fetchone()[0]
            == "Original.txt"
        )
    assert objects.values == ({"dm/synthetic/new": b"new"} if outcome == "commit" else {})
    assert objects.removes == (["dm/synthetic/new"] if outcome == "commit_failure" else [])


@pytest.mark.parametrize("accepted", [False, True])
def test_dm_attachment_commit_response_loss_preserves_committed_object(world, accepted):
    with world.connect() as conn:
        seed(conn, world.user_id)
    objects = Objects()
    with Session(world.engine) as db:
        actual_commit = db.commit

        def lose_commit_response():
            if accepted:
                actual_commit()
            raise OSError("synthetic commit response lost")

        db.commit = lose_commit_response
        row = DmMessageAttachment(
            id="accepted-attachment",
            conversation_id="dm-conversation",
            uploader_id=world.user_id,
            filename="accepted.txt",
            content_type="text/plain",
            size_bytes=8,
            storage_key="dm/synthetic/accepted",
        )
        with pytest.raises(HTTPException) as error:
            attachment_persistence.persist_created_attachment(
                db,
                row=row,
                object_write=attachment_persistence.DmAttachmentObjectWrite(
                    storage_key=row.storage_key,
                    content=BytesIO(b"accepted"),
                    size_bytes=8,
                    content_type="text/plain",
                ),
                object_storage=objects,
            )
        assert error.value.status_code == 500
        assert error.value.detail.code == "dm.attachment_save_unknown"
        assert error.value.__cause__ is None and error.value.__suppress_context__
    with world.connect() as conn:
        stored = conn.execute(
            "SELECT storage_key FROM dm_message_attachments WHERE id='accepted-attachment'"
        ).fetchone()
        assert stored == (("dm/synthetic/accepted",) if accepted else None)
    assert objects.removes == []
    assert objects.values == {"dm/synthetic/accepted": b"accepted"}


@pytest.mark.parametrize("locale", ["ko-KR", "en-US"])
def test_dm_attachment_unknown_http_response_is_localized_and_retains_bytes(
    client, dm, monkeypatch, locale
):
    persist = attachment_persistence.persist_created_attachment

    def lose_response(db, **kwargs):
        commit = db.commit

        def accepted_commit():
            commit()
            raise OSError("private commit transport failure")

        db.commit = accepted_commit
        try:
            return persist(db, **kwargs)
        finally:
            db.commit = commit

    monkeypatch.setattr(attachment_persistence, "persist_created_attachment", lose_response)
    before = dict(dm.objects.values)
    response = client.post(
        dm.base + "/attachments",
        headers={**dm.headers, "Accept-Language": locale},
        files={"file": ("unknown.txt", b"retained bytes", "text/plain")},
    )
    assert response.status_code == 500
    assert response.headers["X-MIY-Error-Code"] == "dm.attachment_save_unknown"
    assert "Retry-After" not in response.headers
    message = response.json()["detail"]
    assert ("확인할 수 없습니다" if locale == "ko-KR" else "result is unknown") in message
    assert "private" not in response.text and "transport" not in response.text
    new_keys = set(dm.objects.values) - set(before)
    assert len(new_keys) == 1 and dm.objects.removes == []
    key = new_keys.pop()
    assert dm.objects.values[key] == b"retained bytes"
    with dm.factory() as db:
        assert db.scalar(
            select(DmMessageAttachment.id).where(DmMessageAttachment.storage_key == key)
        )
    assert all(dm.objects.values[k] == value for k, value in before.items())
    assert dm.events.mock_calls == []


def test_hardened_fifteen_to_nineteen_requires_drain_and_new_principal(world, monkeypatch):
    # This historical schema predates the append-only projection transport.
    monkeypatch.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
    # This historical migration exposes 19 sources, independently of current88.
    monkeypatch.setattr(writer_roles, "COVERED_SOURCE_TABLES", (*OLD_SOURCES, *SOURCES))
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    with monkeypatch.context() as old:
        old.setattr(writer_roles, "COVERED_SOURCE_TABLES", OLD_SOURCES)
        role, guard_owner, oid = activate(world)
    config = _migration_config(sa_dsn(world.dsn))
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, REVISION)
    assert prepare(world, role, ACTIVE, draining, "draining") == oid
    with world.connect() as conn:
        assert contents(conn) == before
        for table in SOURCES:
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'UPDATE')", [role, table]
            ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 19
        )
    identity = WriterIdentity(SUITE_SCOPE, "legacy", 5, "sha256:" + "b" * 64)
    new_role = world.role()
    prepare(world, new_role, identity, draining, "draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=guard_owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=oid, expected=draining, expected_state="draining"
        )
        db.commit()
    with world.connect(new_role) as stale_session:
        denied(stale_session, "UPDATE dm_messages SET body=body WHERE false", "55000")
        move(world, draining, "draining", state="active", artifact=identity.artifact)
        # Same physical session becomes usable only for its immutable exact generation.
        stale_session.execute("UPDATE dm_messages SET body='New generation'")
        stale_session.commit()
        next_drain = move(world, identity, "active", state="draining", artifact=identity.artifact)
        denied(stale_session, "UPDATE dm_messages SET body=body WHERE false", "55000")
        with Session(world.engine) as db:
            revoke_principal(
                db,
                world.actor,
                role_oid=prepare(world, new_role, identity, next_drain, "draining"),
                expected=next_drain,
                expected_state="draining",
            )
            db.commit()
        denied(stale_session, "UPDATE dm_messages SET body=body WHERE false", "55000")
    with world.connect(role) as conn:
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
        denied(conn, "UPDATE dm_messages SET body=body WHERE false")
    with world.connect(new_role) as conn:
        for sql in (
            "TRUNCATE dm_messages CASCADE",
            "UPDATE official_runtime_ownership SET state='active'",
            "SELECT * FROM audit_logs",
            "SELECT * FROM users",
            "UPDATE file_manager_files SET filename=filename WHERE false",
        ):
            denied(conn, sql)
    with pytest.raises(RuntimeError, match="requires_explicit_retirement"):
        command.downgrade(config, PREVIOUS)
    assert_revision(world, REVISION, fenced=True)


def test_current_helper_refuses_new_role_against_unfenced_old_dm_schema(world):
    old_schema(world)
    role = world.role()
    with pytest.raises(WriterControlError, match="writer_role_trigger_inventory_invalid"):
        prepare(world, role)
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='official_writer.principal.prepare'"
            ).fetchone()[0]
            == 0
        )
        for table in SOURCES:
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'UPDATE')", [role, table]
            ).fetchone()[0]


@pytest.mark.parametrize("hazard", ["disabled", "mixed", "arguments"])
def test_dm_upgrade_rejects_bad_old_guard_without_partial_ddl(world, hazard):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
        if hazard == "disabled":
            conn.execute("ALTER TABLE planner_events DISABLE TRIGGER miy_official_source_writer")
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON planner_events")
            function = (
                "miy_guard_official_source_writer_by_role"
                if hazard == "mixed"
                else "miy_guard_official_source_writer"
            )
            argument = "official.suite" if hazard == "mixed" else "invalid"
            conn.execute(
                f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON planner_events FOR EACH STATEMENT EXECUTE FUNCTION {function}('{argument}')"
            )
    with pytest.raises(RuntimeError, match="guard_inventory_invalid"):
        command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before


@pytest.mark.parametrize("isolation", ["AUTOCOMMIT", "REPEATABLE READ"])
def test_dm_migration_requires_owned_lock_transaction(world, isolation):
    old_schema(world)
    module = ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module
    with world.engine.connect().execution_options(isolation_level=isolation) as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="requires_transaction|requires_read_committed"):
                module.upgrade()
    assert_revision(world, PREVIOUS, fenced=False)
