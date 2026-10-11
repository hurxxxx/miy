"""Inactive owner-only actor admission in disposable, migrated PostgreSQL.

Core auth uses its current restricted 15-table/89-column LOGIN. The distinct
actor LOGIN has no business/Core SELECT or DML; its private capability holds
current positive witnesses until caller COMMIT/rollback. A synthetic, explicitly
registered privileged Core fixture may mutate metadata through the unchanged
Source trigger. This is fixture authority, not operational role provisioning.

No runtime factory, Yjs save, full resource ACL or physical-COMMIT expiry fence
is activated. Database locators detect known different databases, not a
cryptographic cluster identity. Missing APIs are readiness failures, never RED.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
import re
from shutil import copyfile
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.official_apps.writer_roles import install_role_guard
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, BASE, DRAIN, PASSWORD, move
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as current_head_http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)

CAPABILITY = "public.miy_whiteboard_lock_owner_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
SERVICE = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER = "public.miy_recording_lock_producer(bigint,text,integer,text)"
ROLE_GUARD = "public.miy_guard_official_source_writer_by_role()"


def _capture_before_actor_revision(world):
    """Capture current authority before a test pins only historical actor SQL."""
    world.owner_revision_execution = _api().runtime.capture_whiteboard_write_execution(
        world.factory,
        token=world.token,
        original_user_id=world.state["member_id"],
        original_source_session_id=world.state["source_id"],
    )


@pytest.fixture
def http_world(current_head_http_world, request, tmp_path, monkeypatch):  # noqa: F811
    """Keep actor behavior at head; pin only the owner revision's own checks."""
    revision = getattr(request, "param", None)
    if revision is None:
        return current_head_http_world
    assert revision == "wb_actor_owner_20261009"
    # The current auth reader requires the current workspace fence. Capture its
    # real detached execution before pinning only the historical actor SQL/schema.
    _capture_before_actor_revision(current_head_http_world)
    with current_head_http_world.core() as db:
        dsn = db.get_bind().url.render_as_string(hide_password=False)
    original_config = _migration_config
    config = original_config(dsn)
    ancestors = list(ScriptDirectory.from_config(config).walk_revisions(base="base", head=revision))
    command.downgrade(config, revision)
    versions = tmp_path / "owner_migration_versions"
    versions.mkdir()
    for ancestor in ancestors:
        source = Path(ancestor.path)
        copyfile(source, versions / source.name)

    def owner_config(dsn=None):
        scoped = original_config(dsn)
        scoped.set_main_option("version_locations", str(versions))
        return scoped

    monkeypatch.setattr(__name__ + "._migration_config", owner_config)
    return current_head_http_world


def _api():
    try:
        return SimpleNamespace(
            roles=import_module("miy_api.domains.official_apps.whiteboard_actor_writer_roles"),
            runtime=import_module("miy_api.domains.official_apps.whiteboard_actor_writer"),
            service=import_module("miy_api.domains.official_apps.whiteboard_source_writer_roles"),
        )
    except ModuleNotFoundError:
        pytest.fail("Actor owner API readiness missing; no behavioral RED", pytrace=False)


def _oid(conn, name):
    return conn.execute("SELECT oid::bigint FROM pg_roles WHERE rolname=%s", (name,)).fetchone()[0]


@pytest.fixture
def actor_boundary(http_world):
    api, world = _api(), http_world
    with world.core() as db:
        engine = db.get_bind()
        admin = resolve_auth_context_from_token(
            db, world.state["admin"]["token"], update_last_seen=False
        )
        db.expunge_all()
    url = engine.url
    # Connection parameters stay private; all credential values are synthetic.
    dsn = make_conninfo(
        host=url.host, port=url.port, dbname=url.database, user=url.username, password=url.password
    )
    roles = []

    def connect(role_name=None, **kwargs):
        return psycopg.connect(
            make_conninfo(
                dsn,
                user=role_name or url.username,
                password=PASSWORD if role_name else url.password,
            ),
            **kwargs,
        )

    def role(*, login=True):
        name = "actor_fixture_" + uuid4().hex[:20]
        with connect() as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(
                    sql.Identifier(name),
                    sql.SQL("LOGIN" if login else "NOLOGIN"),
                    sql.Literal(PASSWORD),
                )
            )
        roles.append(name)
        return name

    control = SimpleNamespace(engine=engine, actor=admin)
    with connect() as conn:
        migration_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (CAPABILITY,)
        ).fetchone()[0]
        service_migration_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (SERVICE,)
        ).fetchone()[0]
        producer_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (PRODUCER,)
        ).fetchone()[0]
    guard, service_owner, owner = role(login=False), role(login=False), role(login=False)
    source = role()
    assert move(control, BASE, "active", state="draining") == DRAIN
    with Session(engine) as db:
        install_role_guard(db, admin, guard_owner=guard, expected=DRAIN)
        db.commit()
    with connect() as conn:
        guard_oid, service_oid, owner_oid = (
            _oid(conn, name) for name in (guard, service_owner, owner)
        )
    with Session(engine) as db:
        api.service.install_whiteboard_source_writer_guard(
            db,
            admin,
            guard_owner=service_owner,
            expected=DRAIN,
            expected_migration_owner_oid=service_migration_owner,
            expected_producer_owner_oid=producer_owner,
            expected_source_guard_owner_oid=guard_oid,
        )
        db.commit()
    c = SimpleNamespace(
        api=api,
        world=world,
        engine=engine,
        actor=admin,
        control=control,
        connect=connect,
        role=role,
        roles=roles,
        dsn=dsn,
        guard=guard,
        source_guard_owner_oid=guard_oid,
        service_owner=service_owner,
        service_capability_owner_oid=service_oid,
        capability_owner=owner,
        capability_owner_oid=owner_oid,
        migration_owner_oid=migration_owner,
        producer_owner_oid=producer_owner,
        source=source,
        expected=DRAIN,
        expected_state="draining",
        board_id=world.ids["board"],
    )
    try:
        yield c
    finally:
        # Only this disposable database and locally owned synthetic roles.
        with connect(autocommit=True) as conn:
            for name in reversed(roles):
                conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(name)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def _install(c, db):
    return c.api.roles.install_whiteboard_actor_owner_guard(
        db,
        c.actor,
        guard_owner=c.capability_owner,
        expected=DRAIN,
        expected_migration_owner_oid=c.migration_owner_oid,
        expected_service_capability_owner_oid=c.service_capability_owner_oid,
        expected_producer_owner_oid=c.producer_owner_oid,
        expected_source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _prepare(c, db, name=None, *, identity=None):
    return c.api.roles.prepare_whiteboard_actor_owner_principal(
        db,
        c.actor,
        role_name=c.source if name is None else name,
        identity=identity or ACTIVE,
        expected=c.expected,
        expected_state=c.expected_state,
        capability_owner_oid=c.capability_owner_oid,
        service_capability_owner_oid=c.service_capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _capture(c, **kwargs):
    if not kwargs and hasattr(c.world, "owner_revision_execution"):
        return c.world.owner_revision_execution
    return c.api.runtime.capture_whiteboard_write_execution(
        c.world.factory,
        token=kwargs.get("token", c.world.token),
        original_user_id=kwargs.get("user", c.world.state["member_id"]),
        original_source_session_id=kwargs.get("session", c.world.state["source_id"]),
    )


def _lock(c, db, *, execution=None, writer=None, board=None):
    return c.api.runtime.lock_whiteboard_owner_actor_write(
        db,
        writer=c.writer if writer is None else writer,
        execution=c.execution if execution is None else execution,
        whiteboard_id=c.board_id if board is None else board,
    )


@pytest.fixture
def actor_prepared(actor_boundary):
    c = actor_boundary
    with Session(c.engine) as db:
        assert _install(c, db) is None
        result = _prepare(c, db)
        c.writer = result.writer
        assert result.profile_prepared is True
        db.commit()
    assert move(c.control, DRAIN, "draining", state="active", artifact=ACTIVE.artifact) == ACTIVE
    c.expected, c.expected_state = ACTIVE, "active"
    # A test-only original privileged Core identity lets the real hardened
    # Source trigger run for metadata changes. Actor privileges remain DML0.
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO official_writer_principals "
            "(role_oid,role_name,scope,owner,generation,artifact,approved_by_user_id,approved_by_session_id,created_at) "
            "SELECT oid::bigint,rolname,%s,%s,%s,%s,%s,%s,timezone('UTC',clock_timestamp()) FROM pg_roles WHERE rolname=session_user",
            (
                ACTIVE.scope,
                ACTIVE.owner,
                ACTIVE.generation,
                ACTIVE.artifact,
                c.actor.user.id,
                c.actor.session.id,
            ),
        )
    c.source_engine = create_engine(
        c.engine.url.set(username=c.source, password=PASSWORD), pool_size=1, max_overflow=0
    )
    c.execution = _capture(c)
    try:
        yield c
    finally:
        c.source_engine.dispose()


def _params(c):
    return {
        "user": c.execution.actor_user_id,
        "session": c.execution.source_session_id,
        "digest": c.execution.delegated_token_digest,
        "installation": c.execution.installation_id,
        "binding": c.execution.binding_id,
        "release": c.execution.release_id,
        "verification": c.execution.verification_id,
        "board": c.board_id,
        "group": c.world.state["group_id"],
        "other": c.actor.user.id,
        "role": c.writer.role_oid,
    }


def _collab_snapshot(c):
    with c.connect() as conn:
        return conn.execute(
            "SELECT id,whiteboard_id,room_key,yjs_state,updated_at,writer_scope "
            "FROM whiteboard_collab_documents ORDER BY id"
        ).fetchall()


@contextmanager
def _commands(engine):
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield commands
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _refused(c, db, **kwargs):
    with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
        _lock(c, db, **kwargs)
    assert str(caught.value) == "whiteboard_actor_writer_refused"
    db.rollback()


def _wait_for_blocker(observer, waiter, holder):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if observer.execute("SELECT %s=ANY(pg_blocking_pids(%s))", (holder, waiter)).fetchone()[0]:
            return
        time.sleep(0.01)
    pytest.fail("Actual captured row holder did not block native admission")


def _replace_body(conn, signature):
    definition = conn.execute(
        "SELECT pg_get_functiondef(%s::regprocedure)", (signature,)
    ).fetchone()[0]
    marker = re.search(r"\bAS (\$[A-Za-z0-9_]*\$)", definition)
    assert marker is not None
    end = definition.index(marker.group(1), marker.end())
    conn.execute(definition[: marker.end()] + "\nBEGIN RETURN; END;\n" + definition[end:])


METADATA_CHANGES = {
    "user_inactive": "UPDATE users SET status='inactive' WHERE id=:user",
    "user_blocked": "UPDATE users SET login_blocked=true WHERE id=:user",
    "user_reset": "UPDATE users SET must_change_password=true WHERE id=:user",
    "source_revoked": "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE id=:session",
    "source_expired": "UPDATE auth_sessions SET expires_at=timezone('UTC',clock_timestamp())-interval '1 second' WHERE id=:session",
    "source_impersonation": "UPDATE auth_sessions SET impersonator_user_id=:other WHERE id=:session",
    "delegated_revoked": "UPDATE independent_app_sessions SET revoked_at=clock_timestamp() WHERE token_hash=:digest",
    "delegated_permissions": "UPDATE independent_app_sessions SET permissions='[]'::json WHERE token_hash=:digest",
    "installation_disabled": "UPDATE independent_app_installations SET enabled=false WHERE id=:installation",
    "installation_generation": "UPDATE independent_app_installations SET generation=generation+1 WHERE id=:installation",
    "installation_release_null": "UPDATE independent_app_installations SET release_id=NULL WHERE id=:installation",
    "installation_permissions": "UPDATE independent_app_installations SET granted_permissions='[]'::json WHERE id=:installation",
    "installation_origin": "UPDATE independent_app_installations SET origin='https://changed.example.test' WHERE id=:installation",
    "verification_revoked": "UPDATE independent_app_build_verifications SET revoked_at=clock_timestamp() WHERE id=:verification",
    "release_verification_null": "UPDATE independent_app_releases SET verification_id=NULL WHERE id=:release",
    "binding_revoked": "UPDATE official_app_bindings SET revoked_at=clock_timestamp() WHERE id=:binding",
    "company_app_disabled": "UPDATE company_app_controls SET enabled=false WHERE app_id=(SELECT app_id FROM independent_app_installations WHERE id=:installation)",
    "whiteboard_app_disabled": "UPDATE company_app_controls SET enabled=false WHERE app_id='whiteboard'",
    "policy_missing": "DELETE FROM app_access_policies WHERE app_id='whiteboard'",
    "selected_witness_revoked": "DELETE FROM group_members WHERE group_id=:group AND user_id=:user",
    "board_owner": "UPDATE whiteboards SET owner_id=:other WHERE id=:board",
    "board_trashed": "UPDATE whiteboards SET trashed_at=clock_timestamp() WHERE id=:board",
}


LOCKED_MUTATIONS = {
    "runtime_ownership": (
        "SELECT 1 FROM official_runtime_ownership WHERE scope='official.suite' FOR UPDATE",
        "UPDATE official_runtime_ownership SET state='draining' WHERE scope='official.suite'",
    ),
    "writer_principal": (
        "SELECT 1 FROM official_writer_principals WHERE role_oid=%(role)s FOR UPDATE",
        "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_oid=:role",
    ),
    "source_session": (
        "SELECT 1 FROM auth_sessions WHERE id=%(session)s FOR UPDATE",
        METADATA_CHANGES["source_revoked"],
    ),
    "user": ("SELECT 1 FROM users WHERE id=%(user)s FOR UPDATE", METADATA_CHANGES["user_blocked"]),
    "delegated_session": (
        "SELECT 1 FROM independent_app_sessions WHERE token_hash=%(digest)s FOR UPDATE",
        METADATA_CHANGES["delegated_revoked"],
    ),
    "installation": (
        "SELECT 1 FROM independent_app_installations WHERE id=%(installation)s FOR UPDATE",
        METADATA_CHANGES["installation_disabled"],
    ),
    "binding": (
        "SELECT 1 FROM official_app_bindings WHERE id=%(binding)s FOR UPDATE",
        METADATA_CHANGES["binding_revoked"],
    ),
    "group_membership": (
        "SELECT 1 FROM group_members WHERE group_id=%(group)s AND user_id=%(user)s FOR UPDATE",
        METADATA_CHANGES["selected_witness_revoked"],
    ),
    "board_owner": (
        "SELECT 1 FROM whiteboards WHERE id=%(board)s FOR UPDATE",
        METADATA_CHANGES["board_owner"],
    ),
    "board_trash": (
        "SELECT 1 FROM whiteboards WHERE id=%(board)s FOR UPDATE",
        METADATA_CHANGES["board_trashed"],
    ),
    "company_control": (
        "SELECT 1 FROM company_app_controls WHERE app_id='whiteboard' FOR UPDATE",
        METADATA_CHANGES["whiteboard_app_disabled"],
    ),
    "installation_company_control": (
        "SELECT 1 FROM company_app_controls WHERE app_id=(SELECT app_id FROM independent_app_installations WHERE id=%(installation)s) FOR UPDATE",
        METADATA_CHANGES["company_app_disabled"],
    ),
    "verification": (
        "SELECT 1 FROM independent_app_build_verifications WHERE id=%(verification)s FOR UPDATE",
        "UPDATE independent_app_build_verifications SET checks=json_build_object('test',false) WHERE id=:verification",
    ),
    "release": (
        "SELECT 1 FROM independent_app_releases WHERE id=%(release)s FOR UPDATE",
        "UPDATE independent_app_releases SET artifact='sha256:'||repeat('b',64) WHERE id=:release",
    ),
    "policy": (
        "SELECT 1 FROM app_access_policies WHERE app_id='whiteboard' FOR UPDATE",
        "UPDATE app_access_policies SET audience='selected' WHERE app_id='whiteboard'",
    ),
    "group_active": (
        "SELECT 1 FROM groups WHERE id=%(group)s FOR UPDATE",
        "UPDATE groups SET active=false WHERE id=:group",
    ),
}


def _native_statement(statement):
    return re.sub(r"(?<!:):([a-z_]+)", r"%(\1)s", statement)


@pytest.mark.parametrize("target", ["source_session"])
def test_genuine_waited_current_row_is_rechecked_after_native_revocation(actor_prepared, target):
    c = actor_prepared
    p = _params(c)
    original = _collab_snapshot(c)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        revoker.execute(LOCKED_MUTATIONS[target][0], p)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder)
                assert not future.done()
                revoker.execute(_native_statement(LOCKED_MUTATIONS[target][1]), p)
                revoker.commit()
                with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()
    assert _collab_snapshot(c) == original


@pytest.mark.parametrize("target,finish", [("binding", "commit")])
def test_genuine_positive_actor_witness_locks_survive_until_actual_caller_end(
    actor_prepared, target, finish
):
    c = actor_prepared
    p = _params(c)
    original = _collab_snapshot(c)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        holder = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _lock(c, db) is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(revoker.execute, _native_statement(LOCKED_MUTATIONS[target][1]), p)
            try:
                _wait_for_blocker(observer, holder, source_pid)
                assert not future.done()
                getattr(db, finish)()
                future.result(timeout=5)
                revoker.commit()
            finally:
                db.rollback()
                revoker.rollback()
        _refused(c, db)
    assert _collab_snapshot(c) == original


def test_genuine_expiry_after_actual_board_wait_is_checked_at_decision_time(actor_prepared):
    c = actor_prepared
    with c.connect() as core:
        core.execute(
            "UPDATE independent_app_sessions SET expires_at=timezone('UTC',clock_timestamp())+interval '1 second' WHERE token_hash=%s",
            (c.execution.delegated_token_digest,),
        )
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as holder,
        Session(c.source_engine) as db,
    ):
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        holder.rollback()
        holder.execute("SELECT 1 FROM whiteboards WHERE id=%s FOR UPDATE", (c.board_id,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder_pid)
                deadline = time.monotonic() + 3
                while observer.execute(
                    "SELECT expires_at>timezone('UTC',clock_timestamp()) FROM independent_app_sessions WHERE token_hash=%s",
                    (c.execution.delegated_token_digest,),
                ).fetchone()[0]:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert not future.done()
                holder.rollback()
                with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_writer_refused"
            finally:
                holder.rollback()
                db.rollback()


def _migration_snapshot(c):
    with c.connect() as conn:
        return {
            "version": conn.execute("SELECT version_num FROM alembic_version").fetchone()[0],
            "actor": conn.execute(
                "SELECT pg_get_function_identity_arguments(p.oid),p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_owner_actor' ORDER BY 1"
            ).fetchall(),
            "existing": (
                conn.execute(
                    "SELECT id,owner_id,trashed_at,scene,updated_at,writer_scope FROM whiteboards ORDER BY id"
                ).fetchall(),
                conn.execute(
                    "SELECT id,whiteboard_id,room_key,yjs_state,updated_at,writer_scope FROM whiteboard_collab_documents ORDER BY id"
                ).fetchall(),
                conn.execute("SELECT * FROM official_runtime_ownership ORDER BY scope").fetchall(),
                conn.execute(
                    "SELECT * FROM official_writer_principals ORDER BY role_oid"
                ).fetchall(),
                conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0],
                conn.execute(
                    "SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE t.tgname IN ('miy_official_source_writer','miy_official_principal_immutable') ORDER BY 1,2,3"
                ).fetchall(),
                conn.execute(
                    "SELECT p.proname,p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN "
                    "('miy_guard_official_source_writer','miy_guard_official_source_writer_by_role','miy_recording_lock_producer','miy_whiteboard_lock_source_writer','miy_immutable_official_writer_principal') ORDER BY 1"
                ).fetchall(),
                conn.execute(
                    "SELECT oid::bigint,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconfig FROM pg_roles WHERE rolname=ANY(%s::text[]) ORDER BY oid",
                    (c.roles,),
                ).fetchall(),
                conn.execute(
                    "SELECT c.relname,c.relacl::text,a.attname,a.attacl::text FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname,a.attnum"
                ).fetchall(),
            ),
        }


@pytest.mark.parametrize("http_world", ["wb_actor_owner_20261009"], indirect=True)
def test_actor_capability_install_capture_drain_retains_business_data(actor_prepared):
    c = actor_prepared
    with c.connect() as conn:
        assert conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE oid=%s", (c.capability_owner_oid,)
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE')",
            (c.source, CAPABILITY, c.source, SERVICE),
        ).fetchone() == (True, False)
    with Session(c.source_engine) as db:
        with pytest.raises(DBAPIError) as denied_read:
            db.execute(text("SELECT owner_id FROM whiteboards"))
        assert denied_read.value.orig.sqlstate == "42501"
        db.rollback()
        with pytest.raises(DBAPIError) as denied_write:
            db.execute(text("UPDATE whiteboard_collab_documents SET yjs_state=NULL WHERE false"))
        assert denied_write.value.orig.sqlstate == "42501"
        db.rollback()
    original = _collab_snapshot(c)
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        assert _lock(c, db) is None
        db.commit()
    assert set(commands) <= {"SELECT", "SET", "SHOW"}
    assert _collab_snapshot(c) == original
    with c.connect() as conn:
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        assert _prepare(c, db).writer == c.writer
        db.commit()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits
    before = _migration_snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_requires_draining"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)),
            "wb_source_writer_20261009",
        )
    assert _migration_snapshot(c) == before
    drained = move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation > ACTIVE.generation
    before = _migration_snapshot(c)
    command.downgrade(
        _migration_config(c.engine.url.render_as_string(hide_password=False)),
        "wb_source_writer_20261009",
    )
    removed = _migration_snapshot(c)
    assert removed["existing"] == before["existing"]
    assert _collab_snapshot(c) == original
    assert removed["version"] == "wb_source_writer_20261009"
    assert removed["actor"] == []
    with Session(c.source_engine) as db:
        _refused(c, db)
