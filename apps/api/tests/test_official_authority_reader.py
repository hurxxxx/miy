"""Owned restricted PostgreSQL authority, separate from business Sessions."""

from datetime import timedelta
from secrets import token_hex
from types import SimpleNamespace

import psycopg
import pytest
from conftest import _build_client, _teardown_client_state
from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_app_auth import bound_official as bound_official
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import sa_dsn

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.app_access_models import AppAccessPolicy
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.models import (
    AuditLog,
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.auth.security import new_id
from miy_api.domains.groups.models import GroupMember
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from miy_api.domains.official_apps import authority_reader as reader
from miy_api.domains.official_apps.models import OfficialAppBinding


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
        "UPDATE public.independent_app_workspaces SET state='ready'",
    ],
)
def test_actual_role_cannot_read_credentials_other_core_data_or_write(authority, statement):
    with authority.factory() as db:
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert caught.value.orig.sqlstate == "42501"


def test_current_reader_uses_only_admission_columns_and_current_workspace_fence(authority):
    world, state = authority, authority.state
    from miy_api.domains.independent_apps.models import load_installation_authority

    with world.factory() as db:
        installation = load_installation_authority(db, state["installation"]["id"])
        assert installation.id == state["installation"]["id"]
        app_id = installation.app_id
        with pytest.raises(InvalidRequestError):
            _ = installation.archived_origin
    assert resolve(world).user.id == state["member_id"]
    with world.core() as db:
        db.add(
            AppWorkspaceRecord(
                id=new_id(),
                app_id=app_id,
                owner_user_id=state["member_id"],
                parent_installation_id=state["installation"]["id"],
                installation_id=state["installation"]["id"],
                profile_id="synthetic-current-auth",
                profile_digest="a" * 64,
                creation_digest="b" * 64,
                state="ready",
            )
        )
        db.commit()
    assert resolve(world).user.id == state["member_id"]
    for closing_state in ("stopping", "stopped", "cleanup_pending", "cleaned"):
        with world.core() as db:
            workspace = db.scalar(
                select(AppWorkspaceRecord).where(
                    AppWorkspaceRecord.installation_id == state["installation"]["id"]
                )
            )
            workspace.state = closing_state
            db.commit()
        with pytest.raises(HTTPException) as caught:
            resolve(world)
        assert caught.value.status_code == 401


@pytest.mark.parametrize(
    "change",
    ["binding", "source_revoke", "inactive", "generation", "verification", "membership", "company"],
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
    ["extra_read", "missing_read", "table_write", "membership", "function", "zero_columns_read"],
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


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_noncurrent_isolation_refused_with_owned_cleanup(authority, isolation):
    engine = authority.engine.execution_options(isolation_level=isolation)
    with pytest.raises(reader.OfficialAuthorityReaderRefused) as caught:
        resolve(authority, factory=sessionmaker(bind=engine))
    assert caught.value.reason == "read_committed_required"
    assert authority.engine.pool.checkedout() == 0


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
