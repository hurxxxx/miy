"""Owned restricted PostgreSQL authority, separate from business Sessions."""

from datetime import timedelta
from secrets import token_hex
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.app_access_models import AppAccessPolicy
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.security import hash_token, new_id
from miy_api.domains.auth.models import (
    AuditLog,
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.groups.models import GroupMember
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppSession
from miy_api.domains.official_apps import authority_reader as reader
from miy_api.domains.official_apps.models import OfficialAppBinding
from conftest import _build_client, _teardown_client_state
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_app_auth import bound_official as bound_official
from test_official_writer_roles import role_template as role_template, sa_dsn


@pytest.fixture
def client(role_template, monkeypatch):
    """Run the real binding setup on our role-capable disposable cluster."""
    cluster, template = role_template
    name = "miy_test_authority_" + token_hex(8)
    with psycopg.connect(cluster, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        )
    try:
        dsn = sa_dsn(make_conninfo(cluster, dbname=name))
        with _build_client(monkeypatch, postgres_dsn=dsn) as test_client:
            yield test_client
    finally:
        try:
            _teardown_client_state()
        finally:
            with psycopg.connect(cluster, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )


@pytest.fixture
def authority(bound_official):
    core_factory = get_session_factory()
    with core_factory() as db:
        engine = db.get_bind()
    name = "miy_auth_test_" + token_hex(8)
    password = token_hex(24)

    def core_sql(statement):
        connection = engine.raw_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement)
            connection.commit()
        finally:
            connection.close()

    role = sql.Identifier(name)
    core_sql(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(role, sql.Literal(password))
    )
    limited = None
    try:
        core_sql(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        for table, columns in reader.AUTHORITY_READ_COLUMNS.items():
            core_sql(
                sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table), role
                )
            )
        limited = create_engine(engine.url.set(username=name, password=password))
        yield SimpleNamespace(
            state=bound_official,
            core=core_factory,
            role=role,
            core_sql=core_sql,
            engine=limited,
            factory=sessionmaker(bind=limited),
        )
    finally:
        if limited is not None:
            limited.dispose()
        core_sql(sql.SQL("DROP OWNED BY {}").format(role))
        core_sql(sql.SQL("DROP ROLE {}").format(role))


def resolve(world, *, factory=None, app="docs", token=None):
    return reader.resolve_prepared_official_auth_context(
        factory or world.factory,
        world.state["app_token"] if token is None else token,
        logical_app_id=app,
    )


@pytest.mark.parametrize(
    "token,app,status",
    [
        ("", "docs", 401),
        ("a\n", "docs", 401),
        ("a" * 1025, "docs", 401),
        (None, "docs", 401),
        ("valid", "unknown", 403),
    ],
)
def test_invalid_input_never_calls_factory(token, app, status):
    def forbidden():
        pytest.fail("invalid input acquired a Session")

    with pytest.raises(HTTPException) as caught:
        reader.resolve_prepared_official_auth_context(forbidden, token, logical_app_id=app)
    assert caught.value.status_code == status


def test_fresh_rejects_routing_and_preserves_caller_work_before_sql():
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    statements = []
    for engine in (first, second):
        event.listen(engine, "before_cursor_execute", lambda *args: statements.append(1))

    class Custom(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            return second if clause is not None else first

    class Standard(Session):
        pass

    cases = [
        (Custom(bind=first), "standard_session_binding_required"),
        (Session(bind=first, binds={User: second}), "single_engine_required"),
        (Session(), "engine_binding_required"),
    ]
    with first.connect() as connection:
        cases.append((Session(bind=connection), "engine_binding_required"))
        for db, reason in cases:
            try:
                with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
                    reader._fresh(db)
                assert caught.value.reason == reason
            finally:
                db.close()
    with Standard(bind=first, binds={User: first}) as db:
        reader._fresh(db)
        marker = User(
            id="unrelated",
            login_id="unrelated",
            email="unused@example.test",
            full_name="Synthetic",
            password_hash="synthetic",
        )
        db.add(marker)
        with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
            reader.resolve_prepared_official_auth_context(
                lambda: db, "opaque", logical_app_id="docs"
            )
        assert caught.value.reason == "fresh_session_required" and marker in db.new
        db.rollback()
        db.begin()
        with pytest.raises(reader.OfficialAuthorityReaderRefused):
            reader._fresh(db)
        assert db.in_transaction()
    assert statements == []
    first.dispose()
    second.dispose()


def test_cleanup_failures_attempt_both_and_invalidate_without_masking():
    calls = []

    class Cancel(BaseException):
        pass

    def broken(name):
        def action():
            calls.append(name)
            raise Cancel()

        return action

    db = SimpleNamespace(
        rollback=broken("rollback"),
        close=broken("close"),
        invalidate=lambda: calls.append("invalidate"),
    )
    reader._cleanup(db)
    assert calls == ["rollback", "invalidate", "close", "invalidate"]


def test_idle_cached_caller_credentials_refused_without_sql_or_cleanup(authority):
    world = authority
    with world.core() as core:
        core_engine = core.get_bind()
    with Session(bind=core_engine, expire_on_commit=False) as db:
        user = db.get(User, world.state["member_id"])
        source = db.get(AuthSession, world.state["source_id"])
        db.commit()
        db.bind = world.engine
        assert not db.in_transaction() and not db.new and not db.dirty
        statements = []

        def capture(*args):
            statements.append(1)

        event.listen(world.engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
                resolve(world, factory=lambda: db)
            assert caught.value.reason == "fresh_session_required"
            assert inspect(user).session is db and inspect(source).session is db
            assert user.password_hash == "fixture" and source.token_hash
            assert not db.in_transaction() and statements == []
        finally:
            event.remove(world.engine, "before_cursor_execute", capture)


def test_restricted_reader_preserves_principal_without_graph_credentials_or_writes(authority):
    world = authority
    with world.core() as db:
        original = resolve_auth_context_from_token(
            db, world.state["login_token"], update_last_seen=False
        )
        before = (original.session.last_seen_at, db.scalars(select(AuditLog.id)).all())
        expected = (original.user.id, original.session.id, original.system_roles)
    commands = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(world.engine, "before_cursor_execute", capture)
    try:
        context = resolve(world)
        assert (context.user.id, context.session.id, context.system_roles) == expected
        assert context.user.email == "member@example.test"
        assert context.user.locale == "ko-KR" and context.user.time_zone == "Asia/Seoul"
        assert inspect(context.user).detached and inspect(context.session).detached
        count = len(commands)
        for model, attr in (
            (context.user, "password_hash"),
            (context.user, "sessions"),
            (context.session, "token_hash"),
            (context.session, "user"),
        ):
            with pytest.raises((InvalidRequestError, DetachedInstanceError)):
                getattr(model, attr)
        assert len(commands) == count
        assert set(commands) <= {"SELECT", "SHOW", "SET"}
    finally:
        event.remove(world.engine, "before_cursor_execute", capture)
    with world.core() as db:
        assert (
            db.get(AuthSession, context.session.id).last_seen_at,
            db.scalars(select(AuditLog.id)).all(),
        ) == before
    assert resolve(world, app="pms").user.id == context.user.id
    with pytest.raises(HTTPException):
        resolve(world, token=world.state["login_token"])
    with pytest.raises(HTTPException):
        resolve(world, app="files")


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT password_hash FROM public.users",
        "SELECT token_hash FROM public.auth_sessions",
        "SELECT id FROM public.audit_logs",
        "UPDATE public.users SET status='inactive'",
        "DELETE FROM public.official_app_bindings",
    ],
)
def test_actual_role_cannot_read_credentials_other_core_data_or_write(authority, statement):
    with authority.factory() as db:
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert caught.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "change",
    [
        "binding",
        "source_revoke",
        "source_expired",
        "impersonation",
        "blocked",
        "forced_password",
        "inactive",
        "installation",
        "generation",
        "identity_permission",
        "verification",
        "membership",
        "company",
        "selected",
    ],
)
def test_current_policy_revocation_refuses_same_app_token(authority, change):
    world, state = authority, authority.state
    with world.core() as db:
        if change == "binding":
            db.get(OfficialAppBinding, state["binding_id"]).revoked_at = utcnow_naive()
        elif change.startswith("source_") or change == "impersonation":
            session = db.get(AuthSession, state["source_id"])
            if change == "source_revoke":
                session.revoked_at = utcnow_naive()
            elif change == "source_expired":
                session.expires_at = utcnow_naive() - timedelta(seconds=1)
            else:
                session.impersonator_user_id = state["admin"]["user"]["id"]
        elif change in {"blocked", "forced_password", "inactive"}:
            user = db.get(User, state["member_id"])
            setattr(
                user,
                {
                    "blocked": "login_blocked",
                    "forced_password": "must_change_password",
                    "inactive": "status",
                }[change],
                "inactive" if change == "inactive" else True,
            )
        elif change in {"installation", "generation", "identity_permission"}:
            installation = db.get(AppInstallationRecord, state["installation"]["id"])
            if change == "installation":
                installation.enabled = False
            elif change == "generation":
                installation.generation += 1
            else:
                installation.granted_permissions = []
        elif change == "verification":
            binding = db.get(OfficialAppBinding, state["binding_id"])
            db.get(AppBuildVerification, binding.verification_id).revoked_at = utcnow_naive()
        elif change == "membership":
            db.delete(db.get(GroupMember, (state["group_id"], state["member_id"])))
        elif change == "company":
            db.get(CompanyAppControl, "docs").enabled = False
        else:
            db.get(AppAccessPolicy, "docs").audience = "selected"
        db.commit()
    with pytest.raises(HTTPException) as caught:
        resolve(world)
    assert caught.value.status_code in {401, 403}


@pytest.mark.parametrize(
    "change",
    [
        "extra_read",
        "missing_read",
        "column_write",
        "table_write",
        "grant_option",
        "membership",
        "foreign_schema",
        "function",
        "sequence",
        "parameter",
        "pg_prefix",
        "pg_sequence",
        "zero_columns_read",
        "zero_columns_write",
    ],
)
def test_actual_extra_or_incomplete_principal_refused_before_identity(
    authority, monkeypatch, change
):
    world = authority
    statements = {
        "extra_read": "GRANT SELECT (password_hash) ON public.users TO {}",
        "missing_read": "REVOKE SELECT (locale) ON public.users FROM {}",
        "column_write": "GRANT UPDATE (status) ON public.users TO {}",
        "table_write": "GRANT DELETE ON public.official_app_bindings TO {}",
        "grant_option": "GRANT SELECT (id) ON public.users TO {} WITH GRANT OPTION",
        "membership": "GRANT pg_read_all_data TO {}",
        "foreign_schema": "GRANT UPDATE ON reader_extra.synthetic TO {}",
        "sequence": "GRANT USAGE ON SEQUENCE reader_extra.synthetic_seq TO {}",
        "parameter": "GRANT SET ON PARAMETER session_replication_role TO {}",
        "pg_prefix": "GRANT UPDATE ON pgx_reader.synthetic TO {}",
        "pg_sequence": "GRANT USAGE ON SEQUENCE pgx_reader.synthetic_seq TO {}",
        "zero_columns_read": "GRANT SELECT ON public.reader_zero_columns TO {}",
        "zero_columns_write": "GRANT INSERT ON public.reader_zero_columns TO {}",
    }
    if change in {"foreign_schema", "sequence", "function"}:
        world.core_sql("CREATE SCHEMA reader_extra")
        if change == "foreign_schema":
            world.core_sql("CREATE TABLE reader_extra.synthetic(id integer)")
        elif change == "sequence":
            world.core_sql("CREATE SEQUENCE reader_extra.synthetic_seq")
        else:
            world.core_sql(
                "CREATE FUNCTION reader_extra.synthetic() RETURNS integer LANGUAGE sql "
                "SECURITY DEFINER SET search_path=pg_catalog AS 'SELECT 1'"
            )
    if change != "function":
        if change in {"pg_prefix", "pg_sequence"}:
            world.core_sql("CREATE SCHEMA pgx_reader")
            world.core_sql(
                "CREATE TABLE pgx_reader.synthetic(id integer)"
                if change == "pg_prefix"
                else "CREATE SEQUENCE pgx_reader.synthetic_seq"
            )
        if change in {"zero_columns_read", "zero_columns_write"}:
            world.core_sql("CREATE TABLE public.reader_zero_columns()")
        world.core_sql(sql.SQL(statements[change]).format(world.role))
    monkeypatch.setattr(
        reader, "resolve_official_auth_context", lambda *a, **k: pytest.fail("profile admitted")
    )
    try:
        with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
            resolve(world)
        assert caught.value.reason in {"reader_principal_required", "reader_privileges_required"}
    finally:
        if change in {"foreign_schema", "sequence", "function"}:
            world.core_sql("DROP SCHEMA reader_extra CASCADE")
        if change in {"pg_prefix", "pg_sequence"}:
            world.core_sql("DROP SCHEMA pgx_reader CASCADE")
        if change in {"zero_columns_read", "zero_columns_write"}:
            world.core_sql("DROP TABLE public.reader_zero_columns")


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_noncurrent_isolation_refused_with_owned_cleanup(authority, isolation):
    engine = authority.engine.execution_options(isolation_level=isolation)
    with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
        resolve(authority, factory=sessionmaker(bind=engine))
    assert caught.value.reason == "read_committed_required"
    assert authority.engine.pool.checkedout() == 0


def test_pooled_temp_and_shadow_current_setting_do_not_override_canonical_authority(authority):
    world = authority
    with world.factory() as db:
        db.execute(text("CREATE TEMP TABLE users(id text)"))
        db.execute(text("CREATE TEMP TABLE auth_sessions(id text)"))
        db.execute(text("CREATE TEMP TABLE official_app_bindings(id text)"))
        db.execute(text("SET search_path = pg_temp, public, pg_catalog"))
        db.commit()
    assert resolve(world).user.id == world.state["member_id"]
    world.core_sql(
        "CREATE FUNCTION public.current_setting(text) RETURNS text LANGUAGE sql "
        "AS 'SELECT ''read committed''::text'"
    )
    try:
        engine = world.engine.execution_options(isolation_level="REPEATABLE READ")
        with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
            resolve(world, factory=sessionmaker(bind=engine))
        assert caught.value.reason == "read_committed_required"
    finally:
        world.core_sql("DROP FUNCTION public.current_setting(text)")


def test_explicit_falsy_internal_loader_failure_never_falls_back(authority, monkeypatch):
    from miy_api.domains.independent_apps import service
    from miy_api.domains.official_apps.auth import resolve_official_auth_context

    class FalsyLoader:
        def __bool__(self):
            return False

        def __call__(self, *_):
            raise HTTPException(status_code=401, detail="synthetic")

    monkeypatch.setattr(service, "_source_user", lambda *_: pytest.fail("fallback invoked"))
    with authority.core() as db:
        with pytest.raises(HTTPException) as caught:
            resolve_official_auth_context(
                db,
                authority.state["app_token"],
                logical_app_id="docs",
                source_user_loader=FalsyLoader(),
            )
    assert caught.value.status_code == 401


def test_role_revoked_during_final_admission_cannot_return_stale_admin(authority, monkeypatch):
    from miy_api.domains.official_apps import auth

    world = authority
    with world.core() as db:
        db.add(UserSystemRole(id=new_id(), user_id=world.state["member_id"], role="platform_admin"))
        db.commit()
    original, calls = auth.can_use_app, []

    def admitted_then_revoke(db, **kwargs):
        allowed = original(db, **kwargs)
        calls.append(allowed)
        if len(calls) == 2:
            with world.core() as core:
                core.execute(
                    delete(UserSystemRole).where(
                        UserSystemRole.user_id == world.state["member_id"],
                        UserSystemRole.role == "platform_admin",
                    )
                )
                core.commit()
        return allowed

    monkeypatch.setattr(auth, "can_use_app", admitted_then_revoke)
    with pytest.raises(HTTPException) as caught:
        resolve(world)
    assert caught.value.status_code == 403 and calls == [True, True]


@pytest.mark.parametrize("change", ["expired", "revoked"])
def test_delegated_credential_changed_during_final_admission_is_refused(
    authority, monkeypatch, change
):
    from miy_api.domains.official_apps import auth

    world, original, calls = authority, auth.can_use_app, []

    def admitted_then_change(db, **kwargs):
        allowed = original(db, **kwargs)
        calls.append(allowed)
        if len(calls) == 2:
            with world.core() as core:
                session = core.get(AppSession, hash_token(world.state["app_token"]))
                if change == "expired":
                    session.expires_at = utcnow_naive() - timedelta(seconds=1)
                else:
                    session.revoked_at = utcnow_naive()
                core.commit()
        return allowed

    monkeypatch.setattr(auth, "can_use_app", admitted_then_change)
    with pytest.raises(HTTPException) as caught:
        resolve(world)
    assert caught.value.status_code == 401 and calls == [True, True]


def test_expiry_during_cleanup_and_cancellation_release_owned_session(authority, monkeypatch):
    world, original_cleanup = authority, reader._cleanup

    def delayed_cleanup(db):
        original_cleanup(db)
        monkeypatch.setattr(reader, "utcnow_naive", lambda: utcnow_naive() + timedelta(hours=2))

    monkeypatch.setattr(reader, "_cleanup", delayed_cleanup)
    with pytest.raises(HTTPException) as caught:
        resolve(world)
    assert caught.value.status_code == 401 and world.engine.pool.checkedout() == 0
    monkeypatch.setattr(reader, "utcnow_naive", utcnow_naive)
    monkeypatch.setattr(reader, "_cleanup", original_cleanup)

    class Cancel(BaseException):
        pass

    def cancelled(*args, **kwargs):
        raise Cancel()

    monkeypatch.setattr(reader, "resolve_official_auth_context", cancelled)
    with pytest.raises(Cancel):
        resolve(world)
    assert world.engine.pool.checkedout() == 0


def test_sql_failure_is_private_and_owned_session_released(authority, monkeypatch):
    def failed(*args, **kwargs):
        raise SQLAlchemyError("private-synthetic-selector")

    monkeypatch.setattr(reader, "resolve_official_auth_context", failed)
    with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
        resolve(authority)
    assert caught.value.reason == "authority_read_failed"
    assert str(caught.value) == "official_authority_reader_refused"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert authority.engine.pool.checkedout() == 0
