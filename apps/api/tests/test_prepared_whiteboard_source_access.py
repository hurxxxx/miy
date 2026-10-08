"""Explicit inactive Whiteboard ACL reads; no operational Source activation."""

import asyncio
from functools import partial
from secrets import token_hex
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.requests import Request

from miy_api import api_registry, official_auth
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import User
from miy_api.domains.whiteboard import collab_source_access as source, router as whiteboard
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardGroupShare, WhiteboardUserShare
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_prepared_official_ws_auth import SyntheticHub, socket_connection


def test_explicit_source_callback_is_bound_only_by_prepared_server_assembly(monkeypatch):
    # No room, default Source factory or real runtime participates in assembly.
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    app = FastAPI()

    def source_factory():
        return None

    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=lambda: None,
        official_auth_max_concurrent_reads=1,
        official_whiteboard_source_session_factory=source_factory,
        official_whiteboard_source_max_concurrent_reads=1,
    )
    assert callable(app.state.prepared_whiteboard_source_access)
    assert callable(app.state.prepared_official_auth_dependency)


@pytest.mark.parametrize(
    "options",
    [
        {"official_whiteboard_source_session_factory": lambda: None},
        {"official_whiteboard_source_max_concurrent_reads": 1},
        {
            "official_whiteboard_source_session_factory": lambda: None,
            "official_whiteboard_source_max_concurrent_reads": 1,
        },
    ],
)
def test_source_options_cannot_select_default_or_partial_assembly(monkeypatch, options):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    with pytest.raises(ValueError):
        api_registry.register_api_routers(
            FastAPI(), get_settings(), composition="official", **options
        )


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_source_budget_is_a_positive_integer(budget):
    with pytest.raises(ValueError):
        source.build_prepared_whiteboard_source_access(
            session_factory=lambda: None, max_concurrent_reads=budget
        )


class MarkerBase(DeclarativeBase):
    pass


class Marker(MarkerBase):
    __tablename__ = "synthetic_caller_marker"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str]


@pytest.mark.parametrize("state", ["active", "nested", "new", "dirty", "deleted", "cached"])
def test_fresh_refusal_preserves_real_borrowed_caller_and_allocates_no_sql(monkeypatch, state):
    engine = create_engine("sqlite://")
    MarkerBase.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(Marker(id=1, value="original"))
    db.commit()
    db.expunge_all()
    marker = None
    if state in {"dirty", "deleted", "cached"}:
        marker = db.get(Marker, 1)
        if state == "dirty":
            marker.value = "pending"
        elif state == "deleted":
            db.delete(marker)
        else:
            db.commit()  # idle identity-map reuse must still refuse
    elif state == "new":
        marker = Marker(id=2, value="pending")
        db.add(marker)
    else:
        db.begin()
        if state == "nested":
            db.begin_nested()
    transaction, nested = db.get_transaction(), db.get_nested_transaction()
    pending = (set(db.new), set(db.dirty), set(db.deleted), tuple(db.identity_map.values()))
    statements, cleanup = [], []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(1))
    rollback, close = db.rollback, db.close
    monkeypatch.setattr(db, "rollback", lambda: cleanup.append("rollback"))
    monkeypatch.setattr(db, "close", lambda: cleanup.append("close"))
    try:
        with pytest.raises(source.WhiteboardSourceReaderRefused) as caught:
            source.require_prepared_whiteboard_edit_access(
                lambda: db, item_id="synthetic", user=User(id="member")
            )
        assert caught.value.reason == "fresh_session_required"
        assert db.get_transaction() is transaction and db.get_nested_transaction() is nested
        assert (
            set(db.new),
            set(db.dirty),
            set(db.deleted),
            tuple(db.identity_map.values()),
        ) == pending
        assert cleanup == [] and statements == []
    finally:
        rollback()
        close()
        engine.dispose()


def test_standard_single_engine_routing_guard_is_before_sql_and_cleanup(monkeypatch):
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    statements = []
    for engine in (first, second):
        event.listen(engine, "before_cursor_execute", lambda *a: statements.append(1))

    class Routed(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            return second if clause is not None else first

    class Standard(Session):
        pass

    cases = [
        (Routed(bind=first), "standard_session_binding_required"),
        (Session(bind=first, binds={User: second}), "single_engine_required"),
        (Session(), "engine_binding_required"),
    ]
    with first.connect() as connection:
        cases.append((Session(bind=connection), "engine_binding_required"))
        for db, reason in cases:
            cleanup = []
            close = db.close
            monkeypatch.setattr(db, "close", lambda: cleanup.append(1))
            try:
                with pytest.raises(source.WhiteboardSourceReaderRefused) as caught:
                    source.require_prepared_whiteboard_edit_access(
                        lambda: db, item_id="synthetic", user=User(id="member")
                    )
                assert caught.value.reason == reason and cleanup == []
            finally:
                close()
    with Standard(bind=first, binds={User: first}) as db:
        source._fresh(db)
    assert statements == []
    first.dispose()
    second.dispose()


def test_cleanup_cancellation_preserves_original_body_and_attempts_both_actions():
    class Cancel(BaseException):
        pass

    calls = []

    def fail(name):
        def action():
            calls.append(name)
            raise Cancel()

        return action

    db = SimpleNamespace(
        rollback=fail("rollback"),
        close=fail("close"),
        invalidate=lambda: calls.append("invalidate"),
    )
    original = localized_http_exception(status_code=403, code="whiteboard.edit_access_required")
    with pytest.raises(HTTPException) as caught:
        try:
            raise original
        finally:
            source._cleanup(db)
    assert caught.value is original
    assert calls == ["rollback", "invalidate", "close", "invalidate"]


@pytest.mark.parametrize(
    "error", [source.WhiteboardSourceReaderRefused("private"), SQLAlchemyError("private")]
)
def test_source_control_errors_are_fixed_private_503_without_fallback(monkeypatch, error):
    def refuse(*a, **k):
        raise error

    monkeypatch.setattr(source, "require_prepared_whiteboard_edit_access", refuse)
    callback = source.build_prepared_whiteboard_source_access(
        session_factory=lambda: None, max_concurrent_reads=1
    )

    async def scenario():
        with pytest.raises(HTTPException) as caught:
            await callback(item_id="synthetic", user=User(id="member"))
        assert (
            caught.value.status_code == 503
            and caught.value.detail.code == "official_apps.authority_unavailable"
        )
        assert "private" not in str(caught.value.detail)

    anyio.run(scenario)


@pytest.mark.parametrize("outcome", ["same", "actor", "session", "missing", "denied"])
def test_after_source_cleanup_same_callable_rechecks_connection_actor_and_session(
    monkeypatch, outcome
):
    app, calls = FastAPI(), []
    first = SimpleNamespace(user=User(id="member"), session=SimpleNamespace(id="session"))

    async def auth(connection, credentials):
        calls.append("auth")
        assert connection.state.official_logical_app_id == "whiteboard"
        assert credentials.credentials == "synthetic"
        if len(calls) == 1 or outcome == "same":
            return first
        if outcome == "denied":
            raise localized_http_exception(status_code=401, code="auth.required")
        return SimpleNamespace(
            user=User(id="other" if outcome == "actor" else "member"),
            session=SimpleNamespace(id="other" if outcome == "session" else "session"),
        )

    app.state.prepared_official_auth_dependency = auth

    async def read(*, item_id, user):
        calls.append("Source cleanup done")
        assert item_id == "synthetic" and user.id == "member"
        if outcome == "missing":
            del app.state.prepared_official_auth_dependency

    monkeypatch.setattr(
        whiteboard, "get_session_factory", lambda: pytest.fail("global Source fallback")
    )

    async def scenario():
        invocation = whiteboard._authorize_prepared_whiteboard_collab_access(
            socket_connection(app),
            item_id="synthetic",
            token="synthetic",
            user_id="member",
            source_session_id="session",
            source_access=read,
        )
        if outcome == "same":
            await invocation
        else:
            with pytest.raises(HTTPException) as caught:
                await invocation
            assert caught.value.status_code == (503 if outcome == "missing" else 401)

    anyio.run(scenario)
    assert calls == (
        ["auth", "Source cleanup done"]
        if outcome == "missing"
        else ["auth", "Source cleanup done", "auth"]
    )


@pytest.mark.parametrize("running", [False, True])
def test_source_raw_repeated_cancel_keeps_worker_and_admission_until_cleanup(monkeypatch, running):
    started, release, finished = Event(), Event(), Event()
    calls = []

    def read(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            try:
                assert release.wait(3)
            finally:
                finished.set()

    monkeypatch.setattr(source, "require_prepared_whiteboard_edit_access", read)
    callback = source.build_prepared_whiteboard_source_access(
        session_factory=lambda: None, max_concurrent_reads=1
    )

    async def invoke():
        await callback(item_id="synthetic", user=User(id="member"))

    async def scenario():
        with anyio.fail_after(3):
            active = asyncio.create_task(invoke())
            queued = None
            try:
                while not started.is_set():
                    await anyio.sleep(0)
                if running:
                    active.cancel()
                    await anyio.sleep(0)
                    active.cancel()
                    queued = asyncio.create_task(invoke())
                    for _ in range(10):
                        await anyio.sleep(0)
                    assert calls == [1] and not active.done() and not finished.is_set()
                else:
                    queued = asyncio.create_task(invoke())
                    await anyio.sleep(0)
                    queued.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await queued
                    queued = None
                    assert calls == [1]
            finally:
                release.set()
                if running:
                    with pytest.raises(asyncio.CancelledError):
                        await active
                else:
                    await active
                if queued is not None:
                    await queued
            assert finished.is_set()

    anyio.run(scenario)
    assert calls == ([1, 1] if running else [1])


def test_auth_and_source_have_separate_explicit_budgets(monkeypatch):
    auth_started, source_started, release = Event(), Event(), Event()

    def auth(*a, **k):
        auth_started.set()
        assert release.wait(3)
        return SimpleNamespace(user=User(id="member"))

    def read(*a, **k):
        source_started.set()
        assert release.wait(3)

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", auth)
    monkeypatch.setattr(source, "require_prepared_whiteboard_edit_access", read)
    dependency = official_auth.build_prepared_official_auth_dependency(
        session_factory=lambda: None, max_concurrent_reads=1
    )
    callback = source.build_prepared_whiteboard_source_access(
        session_factory=lambda: None, max_concurrent_reads=1
    )
    request = Request(
        {
            "type": "http",
            "app": FastAPI(),
            "state": {"official_logical_app_id": "whiteboard"},
            "headers": [],
        }
    )

    async def scenario():
        with anyio.fail_after(3):
            async with anyio.create_task_group() as group:
                try:
                    group.start_soon(
                        dependency,
                        request,
                        HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic"),
                    )
                    while not auth_started.is_set():
                        await anyio.sleep(0)
                    group.start_soon(partial(callback, item_id="synthetic", user=User(id="member")))
                    while not source_started.is_set():
                        await anyio.sleep(0)
                finally:
                    release.set()

    anyio.run(scenario)
    assert auth_started.is_set() and source_started.is_set()


# Actual migrated PostgreSQL fixtures below create only disposable test roles.
_SOURCE_TABLES = (
    "whiteboard_targets",
    "whiteboard_user_shares",
    "whiteboard_group_shares",
    "pms_spaces",
    "pms_space_members",
    "pms_space_group_bindings",
    "pms_task_lists",
    "meetings",
    "meeting_attendees",
)
_BOARD_COLUMNS = ("id", "owner_id", "ownership_kind", "company_visible", "trashed_at")


@pytest.fixture
def source_world(http_world):
    world = http_world
    name, password = "miy_wb_source_" + token_hex(8), token_hex(24)
    role = sql.Identifier(name)
    world.core_sql(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(role, sql.Literal(password))
    )
    engine = None
    try:
        world.core_sql(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        for table, columns in {
            **source.CORE_POLICY_READ_COLUMNS,
            "whiteboards": _BOARD_COLUMNS,
        }.items():
            world.core_sql(
                sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table), role
                )
            )
        for table in _SOURCE_TABLES:
            world.core_sql(
                sql.SQL("GRANT SELECT ON public.{} TO {}").format(sql.Identifier(table), role)
            )
        with world.core() as db:
            url = db.get_bind().url.set(username=name, password=password)
        engine = create_engine(url, pool_size=1, max_overflow=0)
        yield SimpleNamespace(
            world=world,
            role=role,
            name=name,
            engine=engine,
            factory=sessionmaker(bind=engine, autoflush=False),
        )
    finally:
        if engine is not None:
            engine.dispose()
        world.core_sql(sql.SQL("DROP OWNED BY {}").format(role))
        world.core_sql(sql.SQL("DROP ROLE {}").format(role))


def context(c):
    return official_auth.resolve_prepared_official_auth_context(
        c.world.factory, c.world.token, logical_app_id="whiteboard"
    )


def invoke(c):
    source.require_prepared_whiteboard_edit_access(
        c.factory, item_id=c.world.ids["board"], user=context(c).user
    )


def shared(c, level="edit"):
    from miy_api.domains.auth.security import new_id

    with c.world.core() as db:
        db.get(Whiteboard, c.world.ids["board"]).owner_id = c.world.state["admin"]["user"]["id"]
        row = WhiteboardUserShare(
            id=new_id(),
            whiteboard_id=c.world.ids["board"],
            user_id=c.world.state["member_id"],
            created_by_id=c.world.state["admin"]["user"]["id"],
            access_level=level,
        )
        db.add(row)
        db.commit()
        return row.id


def callback(c, monkeypatch):
    app = FastAPI()
    app.state.prepared_official_auth_dependency = (
        official_auth.build_prepared_official_auth_dependency(
            session_factory=c.world.factory, max_concurrent_reads=1
        )
    )
    read = source.build_prepared_whiteboard_source_access(
        session_factory=c.factory, max_concurrent_reads=1
    )
    monkeypatch.setattr(
        whiteboard, "get_session_factory", lambda: pytest.fail("global Source callback used")
    )
    return partial(
        whiteboard._authorize_prepared_whiteboard_collab_access,
        socket_connection(app),
        item_id=c.world.ids["board"],
        token=c.world.token,
        user_id=c.world.state["member_id"],
        source_session_id=c.world.state["source_id"],
        source_access=read,
    )


def test_genuine_minimum_columns_owner_and_share_without_scene_or_user_graph(
    source_world, monkeypatch
):
    c = source_world
    observed = []
    original = source.load_whiteboard_for_acl_or_404

    def inspect_loaded(db, **kwargs):
        result = original(db, **kwargs)
        assert set(inspect(result.whiteboard).unloaded) >= {
            "scene",
            "title",
            "owner",
            "user_shares",
            "group_shares",
            "link_shares",
            "targets",
        }
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        assert db.scalar(text("SHOW search_path")) == "pg_catalog, public, pg_temp"
        with pytest.raises(InvalidRequestError):
            _ = result.whiteboard.scene
        observed.append(1)
        return result

    monkeypatch.setattr(source, "load_whiteboard_for_acl_or_404", inspect_loaded)
    invoke(c)
    shared(c)
    invoke(c)
    assert observed == [1, 1]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT password_hash FROM public.users",
        "SELECT display_name FROM public.users",
        "SELECT token_hash FROM public.auth_sessions",
        "SELECT id FROM public.user_system_roles",
        "SELECT * FROM public.official_runtime_ownership",
        "SELECT * FROM public.official_projection_outbox",
        "UPDATE public.company_app_controls SET enabled=enabled WHERE false",
        "UPDATE public.whiteboards SET title=title WHERE false",
    ],
)
def test_genuine_source_role_denies_credentials_extra_columns_controls_and_writes(
    source_world, statement
):
    with source_world.engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.execute(text(statement))
        assert caught.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "change,status",
    [("read", 403), ("unshared", 404), ("trashed", 404), ("app", 403), ("user", 403)],
)
def test_genuine_current_source_acl_and_app_policy_remain_required(source_world, change, status):
    from miy_api.domains.auth.models import CompanyAppControl, utcnow_naive

    c = source_world
    actor = context(c).user
    share = shared(c, "read" if change == "read" else "edit")
    with c.world.core() as db:
        if change == "unshared":
            db.delete(db.get(WhiteboardUserShare, share))
        elif change == "trashed":
            db.get(Whiteboard, c.world.ids["board"]).trashed_at = utcnow_naive()
        elif change == "app":
            db.get(CompanyAppControl, "whiteboard").enabled = False
        elif change == "user":
            db.get(User, c.world.state["member_id"]).status = "inactive"
        db.commit()
    with pytest.raises(HTTPException) as caught:
        source.require_prepared_whiteboard_edit_access(
            c.factory, item_id=c.world.ids["board"], user=actor
        )
    assert caught.value.status_code == status


@pytest.mark.parametrize("kind", ["local", "hr"])
def test_genuine_current_group_share_and_membership_revocation(source_world, kind):
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.groups.models import Group, GroupMember

    c = source_world
    group_id = new_id()
    with c.world.core() as db:
        db.get(Whiteboard, c.world.ids["board"]).owner_id = c.world.state["admin"]["user"]["id"]
        db.add(
            Group(
                id=group_id,
                name="Synthetic ACL group",
                source=kind,
                active=True,
                slug="synthetic-" + group_id if kind == "hr" else None,
                unit_type="department" if kind == "hr" else None,
            )
        )
        db.flush()
        if kind == "local":
            db.add(GroupMember(group_id=group_id, user_id=c.world.state["member_id"]))
        else:
            db.get(User, c.world.state["member_id"]).primary_organization_unit_id = group_id
        db.add(
            WhiteboardGroupShare(
                whiteboard_id=c.world.ids["board"],
                group_id=group_id,
                access_level="edit",
                created_by_id=c.world.state["admin"]["user"]["id"],
            )
        )
        db.commit()
    invoke(c)
    with c.world.core() as db:
        db.get(Group, group_id).active = False
        db.commit()
    with pytest.raises(HTTPException) as caught:
        invoke(c)
    assert caught.value.status_code == 404


@pytest.mark.parametrize("target", ["space", "task_list", "meeting"])
def test_genuine_existing_target_adapters_and_target_app_revoke(source_world, target):
    from company_admission_fixture import seed_company_app_access
    from miy_api.domains.auth.models import CompanyAppControl, utcnow_naive
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.meeting.models import Meeting, MeetingAttendee
    from miy_api.domains.pms.models import TaskList
    from miy_api.domains.pms.space_models import Team, TeamMember
    from miy_api.domains.whiteboard.models import WhiteboardTarget

    c = source_world
    with c.world.core() as db:
        seed_company_app_access(db, app_ids=["pms", "meeting"])
        db.get(Whiteboard, c.world.ids["board"]).owner_id = c.world.state["admin"]["user"]["id"]
        identifier = new_id()
        if target == "meeting":
            now = utcnow_naive()
            db.add(
                Meeting(
                    id=identifier,
                    title="Synthetic target",
                    organizer_id=c.world.state["admin"]["user"]["id"],
                    start_at=now,
                    end_at=now,
                )
            )
            db.flush()
            db.add(
                MeetingAttendee(
                    id=new_id(), meeting_id=identifier, user_id=c.world.state["member_id"]
                )
            )
            app = "meeting"
        else:
            team = Team(id=identifier, key="synthetic-" + identifier[:8], name="Synthetic target")
            db.add(team)
            db.flush()
            db.add(
                TeamMember(
                    id=new_id(),
                    team_id=identifier,
                    user_id=c.world.state["member_id"],
                    role="member",
                )
            )
            if target == "task_list":
                listing = TaskList(
                    id=new_id(),
                    key="synthetic-" + identifier[:8],
                    team_id=identifier,
                    name="Synthetic list",
                    created_by_id=c.world.state["admin"]["user"]["id"],
                )
                db.add(listing)
                db.flush()
                identifier = listing.id
            app = "pms"
        db.add(
            WhiteboardTarget(
                id=new_id(),
                whiteboard_id=c.world.ids["board"],
                target_app=app,
                target_type=target,
                target_id=identifier,
            )
        )
        db.commit()
    invoke(c)
    with c.world.core() as db:
        db.get(CompanyAppControl, app).enabled = False
        db.commit()
    with pytest.raises(HTTPException) as caught:
        invoke(c)
    assert caught.value.status_code == 404


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_snapshot_and_autocommit_are_refused_before_acl(source_world, isolation):
    c = source_world
    engine = c.engine.execution_options(isolation_level=isolation)
    with pytest.raises(source.WhiteboardSourceReaderRefused) as caught:
        source.require_prepared_whiteboard_edit_access(
            sessionmaker(bind=engine), item_id=c.world.ids["board"], user=context(c).user
        )
    assert caught.value.reason == "read_committed_required"


def test_genuine_safe_role_catalog_reuse_refuses_privileged_factory_before_acl(source_world):
    c = source_world
    with pytest.raises(source.WhiteboardSourceReaderRefused) as caught:
        source.require_prepared_whiteboard_edit_access(
            c.world.core, item_id=c.world.ids["board"], user=context(c).user
        )
    assert caught.value.reason == "source_role_required"


@pytest.mark.parametrize("revoke", ["source", "app"])
def test_genuine_source_wait_final_auth_recheck_denies_before_continuation(
    source_world, monkeypatch, revoke
):
    from miy_api.domains.auth.models import AuthSession, CompanyAppControl, utcnow_naive

    c = source_world
    shared(c)
    authorize = callback(c, monkeypatch)
    waiter, pid = Event(), []

    def wait_observed(connection, cursor, statement, params, ctx, many):
        if "FROM whiteboard_user_shares" in statement:
            pid.append(connection.scalar(text("SELECT pg_catalog.pg_backend_pid()")))
            waiter.set()

    event.listen(c.engine, "before_cursor_execute", wait_observed)
    lock = c.world.core()
    lock.execute(text("LOCK TABLE public.whiteboard_user_shares IN ACCESS EXCLUSIVE MODE"))

    async def scenario():
        with anyio.fail_after(4):
            task = asyncio.create_task(authorize())
            try:
                while not waiter.is_set():
                    await anyio.sleep(0)
                blocked = False
                for _ in range(100):
                    with c.world.core() as db:
                        blocked = bool(
                            db.scalar(
                                text("SELECT cardinality(pg_catalog.pg_blocking_pids(:pid))>0"),
                                {"pid": pid[0]},
                            )
                        )
                    if blocked:
                        break
                    await anyio.sleep(0.005)
                assert blocked
                with c.world.core() as db:
                    if revoke == "source":
                        db.get(AuthSession, c.world.state["source_id"]).revoked_at = utcnow_naive()
                    else:
                        db.get(CompanyAppControl, "whiteboard").enabled = False
                    db.commit()
            finally:
                lock.rollback()
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == (401 if revoke == "source" else 403)

    try:
        anyio.run(scenario)
    finally:
        lock.close()
        event.remove(c.engine, "before_cursor_execute", wait_observed)
    assert waiter.is_set() and len(pid) == 1


def test_genuine_temp_shadow_and_cleanup_preserve_public_acl(source_world):
    c = source_world
    shared(c, "read")
    with c.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TEMP TABLE whiteboard_user_shares AS SELECT * FROM public.whiteboard_user_shares"
            )
        )
        connection.execute(text("UPDATE pg_temp.whiteboard_user_shares SET access_level='edit'"))
    with pytest.raises(HTTPException) as caught:
        invoke(c)
    assert caught.value.status_code == 403
    with c.world.core() as db:
        assert (
            db.scalar(
                select(WhiteboardUserShare.access_level).where(
                    WhiteboardUserShare.whiteboard_id == c.world.ids["board"]
                )
            )
            == "read"
        )


def native_socket_app(c, monkeypatch):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == whiteboard.__name__ and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app, hub = FastAPI(), SyntheticHub(None)
    app.state.whiteboard_collab = hub
    # Original init remains a privileged synthetic Source fixture, explicitly
    # not a complete minimal hub/service composition.
    monkeypatch.setattr(whiteboard, "get_session_factory", lambda: c.world.core)
    calls = []

    def factory():
        calls.append(1)
        return c.factory()

    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=c.world.factory,
        official_auth_max_concurrent_reads=1,
        official_whiteboard_source_session_factory=factory,
        official_whiteboard_source_max_concurrent_reads=1,
    )
    return app, hub, calls


def test_genuine_socket_uses_explicit_acl_role_after_original_room_init(source_world, monkeypatch):
    c = source_world
    shared(c)
    app, hub, calls = native_socket_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/whiteboard/collab/items/{c.world.ids['board']}/ws"
        ) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"synthetic update")
            assert socket.receive_bytes() == b"echo:synthetic update"
    assert calls == [1, 1, 1] and hub.room.effects == [b"synthetic update"]


@pytest.mark.parametrize("phase", ["recv", "send"])
def test_genuine_open_socket_source_share_revoke_precedes_effect_or_send(
    source_world, monkeypatch, phase
):
    from starlette.websockets import WebSocketDisconnect

    c = source_world
    share_id = shared(c)
    app, hub, calls = native_socket_app(c, monkeypatch)

    def revoke():
        with c.world.core() as db:
            db.get(WhiteboardUserShare, share_id).access_level = "read"
            db.commit()

    if phase == "send":
        hub.room.after_receive = revoke
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/whiteboard/collab/items/{c.world.ids['board']}/ws"
        ) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            if phase == "recv":
                revoke()
            socket.send_bytes(b"synthetic update")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert caught.value.code == 1008
    assert hub.room.effects == ([] if phase == "recv" else [b"synthetic update"])
    assert calls == ([1, 1] if phase == "recv" else [1, 1, 1])
