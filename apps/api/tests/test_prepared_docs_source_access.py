"""Explicit inactive Docs Source ACL and separate Core writer read assembly."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from functools import partial
from secrets import token_hex
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import new_id
from miy_api.domains.docs import collab_source_access as source, router as docs
from miy_api.domains.docs.access_context import load_native_page_for_acl_or_404
from miy_api.domains.docs.models import (
    DocMeetingAccess,
    NativeDoc,
    NativeDocPage,
    NativeDocUserShare,
)
from miy_api.domains.official_apps import owned_read_session as guards, writer_access as writer
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_prepared_official_ws_auth import (
    SyntheticHub,
    socket_connection,
    socket_path,
    ws_world as ws_world,  # noqa: F401
)
from test_prepared_whiteboard_source_access import Marker, MarkerBase


def test_explicit_docs_source_and_core_writer_reads_require_prepared_server_assembly(monkeypatch):
    # Construction binds callbacks only; it cannot allocate SQL or start rooms.
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    app = FastAPI()

    def auth_factory():
        raise AssertionError("Assembly allocated an auth Session")

    def source_factory():
        raise AssertionError("Assembly allocated a Source Session")

    def writer_factory():
        raise AssertionError("Assembly allocated a Core writer Session")

    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=auth_factory,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=source_factory,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=writer_factory,
        official_writer_read_max_concurrent_reads=1,
    )
    assert callable(app.state.prepared_official_auth_dependency)
    assert callable(app.state.prepared_docs_source_access)
    assert callable(app.state.prepared_official_writer_access)


def options():
    return dict(
        composition="official",
        official_auth_session_factory=lambda: None,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=lambda: None,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=lambda: None,
        official_writer_read_max_concurrent_reads=1,
    )


@pytest.mark.parametrize(
    "missing",
    [
        "official_auth_session_factory",
        "official_auth_max_concurrent_reads",
        "official_docs_source_session_factory",
        "official_docs_source_max_concurrent_reads",
        "official_writer_read_session_factory",
        "official_writer_read_max_concurrent_reads",
    ],
)
def test_partial_docs_or_core_configuration_refuses_before_state(monkeypatch, missing):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    app, chosen = FastAPI(), options()
    del chosen[missing]
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert app.dependency_overrides == {} and app.state._state == {}


@pytest.mark.parametrize("composition", ["legacy", "platform"])
def test_docs_core_options_cannot_select_another_composition(monkeypatch, composition):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    chosen = options()
    chosen["composition"] = composition
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert app.dependency_overrides == {} and app.state._state == {}


@pytest.mark.parametrize(
    "key",
    [
        "official_auth_max_concurrent_reads",
        "official_docs_source_max_concurrent_reads",
        "official_writer_read_max_concurrent_reads",
    ],
)
@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "1"])
def test_invalid_budget_rejects_complete_group_before_mutation(monkeypatch, key, budget):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    chosen = options()
    chosen[key] = budget
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert app.dependency_overrides == {} and app.state._state == {}


@pytest.mark.parametrize(
    "key",
    [
        "official_auth_session_factory",
        "official_docs_source_session_factory",
        "official_writer_read_session_factory",
    ],
)
def test_noncallable_factory_refuses_complete_group_before_mutation(monkeypatch, key):
    chosen = options()
    chosen[key] = object()
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert app.dependency_overrides == {} and app.state._state == {}


def test_absent_options_build_no_docs_or_writer_state_or_sessions(monkeypatch):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    app = FastAPI()
    api_registry.register_api_routers(app, get_settings(), composition="official")
    assert app.state._state == {}


@pytest.mark.parametrize("kind", ["docs", "writer"])
@pytest.mark.parametrize("state", ["active", "nested", "new", "dirty", "deleted", "cached"])
def test_reader_borrowed_work_is_refused_before_sql_or_cleanup(monkeypatch, kind, state):
    engine = create_engine("sqlite://")
    MarkerBase.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(Marker(id=1, value="original"))
    db.commit()
    db.expunge_all()
    if state in {"dirty", "deleted", "cached"}:
        marker = db.get(Marker, 1)
        if state == "dirty":
            marker.value = "pending"
        elif state == "deleted":
            db.delete(marker)
        else:
            db.commit()
    elif state == "new":
        db.add(Marker(id=2, value="pending"))
    else:
        db.begin()
        if state == "nested":
            db.begin_nested()
    previous = (
        db.get_transaction(),
        db.get_nested_transaction(),
        tuple(db.new),
        tuple(db.dirty),
        tuple(db.deleted),
        tuple(db.identity_map.values()),
    )
    statements, cleanup = [], []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(1))
    rollback, close = db.rollback, db.close
    monkeypatch.setattr(db, "rollback", lambda: cleanup.append("rollback"))
    monkeypatch.setattr(db, "close", lambda: cleanup.append("close"))
    try:
        with pytest.raises(
            source.DocsSourceReaderRefused if kind == "docs" else writer.CoreWriterReaderRefused
        ) as denied:
            if kind == "docs":
                source.require_prepared_docs_edit_access(
                    lambda: db, page_ref="native_doc_page__unit", user=User(id="member")
                )
            else:
                writer.require_prepared_active_writer(
                    lambda: db, writer_identity=WriterIdentity(SUITE_SCOPE, "legacy", 1)
                )
        assert denied.value.reason == "fresh_session_required"
        assert previous == (
            db.get_transaction(),
            db.get_nested_transaction(),
            tuple(db.new),
            tuple(db.dirty),
            tuple(db.deleted),
            tuple(db.identity_map.values()),
        )
        assert statements == cleanup == []
    finally:
        rollback()
        close()
        engine.dispose()


@pytest.mark.parametrize("kind", ["docs", "writer"])
def test_fixed_models_detect_cross_engine_table_routes_before_sql(kind):
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    statements = []
    for engine in (first, second):
        event.listen(engine, "before_cursor_execute", lambda *a: statements.append(1))
    model = NativeDocPage if kind == "docs" else RuntimeOwnership
    db = Session(bind=first, binds={model: second})
    try:
        with pytest.raises(guards.OwnedReadSessionRefused) as denied:
            guards.require_fresh_owned_read_session(
                db, models=source._MODELS if kind == "docs" else writer._MODELS
            )
        assert denied.value.reason == "single_engine_required" and not statements
    finally:
        db.close()
        first.dispose()
        second.dispose()


def test_shared_cleanup_preserves_original_baseexception_and_attempts_both_actions():
    class Stop(BaseException):
        pass

    actions = []

    def fail(name):
        def action():
            actions.append(name)
            raise Stop()

        return action

    db = SimpleNamespace(
        rollback=fail("rollback"),
        close=fail("close"),
        invalidate=lambda: actions.append("invalidate"),
    )
    original = Stop()
    with pytest.raises(Stop) as denied:
        try:
            raise original
        finally:
            guards.cleanup_owned_read_session(db)
    assert denied.value is original
    assert actions == ["rollback", "invalidate", "close", "invalidate"]


@pytest.mark.parametrize("kind", ["docs", "writer"])
@pytest.mark.parametrize("running", [False, True])
def test_queued_and_repeated_running_cancellation_join_reader_before_permit(
    monkeypatch, kind, running
):
    started, release, finished = Event(), Event(), Event()
    calls = []

    def read(*a, **k):
        calls.append(1)
        started.set()
        try:
            assert release.wait(8)
        finally:
            finished.set()

    if kind == "docs":
        monkeypatch.setattr(source, "require_prepared_docs_edit_access", read)
        invoke = partial(
            source.build_prepared_docs_source_access(
                session_factory=lambda: None, max_concurrent_reads=1
            ),
            page_ref="native_doc_page__unit",
            user=User(id="member"),
        )
    else:
        monkeypatch.setattr(writer, "require_prepared_active_writer", read)
        invoke = partial(
            writer.build_prepared_official_writer_access(
                session_factory=lambda: None, max_concurrent_reads=1
            ),
            writer_identity=WriterIdentity(SUITE_SCOPE, "legacy", 1),
        )

    async def scenario():
        with anyio.fail_after(8):
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
                    await anyio.sleep(0.02)
                    assert calls == [1] and not finished.is_set() and not active.done()
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


def pure_callback(*, mutate=None):
    app, seen = FastAPI(), []
    identity = WriterIdentity(SUITE_SCOPE, "legacy", 1)
    hub = SyntheticHub(identity)
    context = SimpleNamespace(user=User(id="member"), session=SimpleNamespace(id="original"))
    counts = {"auth": 0, "writer": 0, "Source": 0}

    async def step(name):
        counts[name] += 1
        seen.append(name)
        if mutate is not None:
            mutate(app, hub, context, name, counts[name])

    async def auth(connection, credentials):
        await step("auth")
        return context

    async def acl(*, page_ref, user):
        assert page_ref == "native_doc_page__unit" and user.id == "member"
        await step("Source")

    async def core(*, writer_identity):
        assert writer_identity is identity
        await step("writer")

    app.state.docs_collab = hub
    app.state.prepared_official_auth_dependency = auth
    app.state.prepared_docs_source_access = acl
    app.state.prepared_official_writer_access = core
    app.state.prepared_docs_source_configured = True
    callback = partial(
        docs._authorize_prepared_docs_source_access,
        socket_connection(app),
        page_ref="native_doc_page__unit",
        token="synthetic",
        user_id="member",
        source_session_id="original",
        auth_dependency=auth,
        source_access=acl,
        writer_access=core,
        hub=hub,
        writer_identity=identity,
    )
    return callback, seen


def test_explicit_frame_has_separate_current_writer_reads_around_source_and_final_auth():
    callback, seen = pure_callback()
    anyio.run(callback)
    assert seen == ["auth", "writer", "Source", "writer", "auth"]


@pytest.mark.parametrize(
    "point", [("auth", 1), ("writer", 1), ("Source", 1), ("writer", 2), ("auth", 2)]
)
@pytest.mark.parametrize(
    "change", ["auth", "Source", "writer", "hub", "identity", "marker", "actor", "session"]
)
def test_each_await_refuses_changed_captured_assembly_or_identity(point, change):
    def mutate(app, hub, context, name, count):
        if (name, count) != point:
            return
        if change in {"actor", "session"}:
            if change == "actor":
                context.user.id = "other"
            else:
                context.session.id = "other"
        elif change == "identity":
            hub.writer_identity = replace(hub.writer_identity)
        elif change == "hub":
            app.state.docs_collab = SyntheticHub(hub.writer_identity)
        elif change == "marker":
            app.state.prepared_docs_source_configured = False
        else:
            field = {
                "auth": "prepared_official_auth_dependency",
                "Source": "prepared_docs_source_access",
                "writer": "prepared_official_writer_access",
            }[change]

            async def replacement(*a, **k):
                return None

            setattr(app.state, field, replacement)

    callback, seen = pure_callback(mutate=mutate)

    async def scenario():
        with pytest.raises(HTTPException) as denied:
            await callback()
        assert denied.value.status_code == (401 if change in {"actor", "session"} else 503)

    anyio.run(scenario)
    expected = ["auth", "writer", "Source", "writer", "auth"]
    index = [("auth", 1), ("writer", 1), ("Source", 1), ("writer", 2), ("auth", 2)].index(point)
    assert seen == expected[: index + 1]


@pytest.mark.parametrize("kind", ["docs", "writer"])
def test_control_and_sql_reader_errors_use_private_authority_failure(monkeypatch, kind):
    def fail(*a, **k):
        raise SQLAlchemyError("private detail")

    if kind == "docs":
        monkeypatch.setattr(source, "require_prepared_docs_edit_access", fail)
        call = partial(
            source.build_prepared_docs_source_access(
                session_factory=lambda: None, max_concurrent_reads=1
            ),
            page_ref="native_doc_page__unit",
            user=User(id="member"),
        )
    else:
        monkeypatch.setattr(writer, "require_prepared_active_writer", fail)
        call = partial(
            writer.build_prepared_official_writer_access(
                session_factory=lambda: None, max_concurrent_reads=1
            ),
            writer_identity=WriterIdentity(SUITE_SCOPE, "legacy", 1),
        )

    async def scenario():
        with pytest.raises(HTTPException) as denied:
            await call()
        assert (
            denied.value.status_code == 503
            and denied.value.detail.code == "official_apps.authority_unavailable"
        )

    anyio.run(scenario)


# Genuine migrated PostgreSQL roles below; only disposable test roles are created.
_SOURCE_TABLES = (
    "docs_doc_targets",
    "docs_native_doc_user_shares",
    "docs_group_shares",
    "docs_meeting_access",
    "pms_spaces",
    "pms_space_members",
    "pms_space_group_bindings",
)
_DOC_COLUMNS = ("id", "owner_id", "ownership_kind", "company_visible", "trashed_at")
_PAGE_COLUMNS = ("id", "doc_id", "content_format", "trashed_at")
_WRITER_COLUMNS = ("scope", "active_owner", "generation", "artifact", "state", "updated_at")


@pytest.fixture
def docs_world(ws_world):
    world = ws_world
    engines, roles = [], []
    try:
        for kind in ("source", "writer"):
            name, password = "miy_docs_" + kind + "_" + token_hex(8), token_hex(24)
            role = sql.Identifier(name)
            world.core_sql(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(role, sql.Literal(password))
            )
            roles.append(role)
            world.core_sql(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            columns = (
                {
                    **guards.CORE_POLICY_READ_COLUMNS,
                    "docs_native_docs": _DOC_COLUMNS,
                    "docs_native_doc_pages": _PAGE_COLUMNS,
                }
                if kind == "source"
                else {"official_runtime_ownership": _WRITER_COLUMNS}
            )
            for table, fields in columns.items():
                world.core_sql(
                    sql.SQL("GRANT SELECT ({}) ON public.{} TO {}").format(
                        sql.SQL(",").join(map(sql.Identifier, fields)), sql.Identifier(table), role
                    )
                )
            if kind == "source":
                for table in _SOURCE_TABLES:
                    world.core_sql(
                        sql.SQL("GRANT SELECT ON public.{} TO {}").format(
                            sql.Identifier(table), role
                        )
                    )
            with world.core() as db:
                url = db.get_bind().url.set(username=name, password=password)
            engine = create_engine(url, pool_size=1, max_overflow=0)
            engines.append(engine)
        yield SimpleNamespace(
            world=world,
            source_engine=engines[0],
            writer_engine=engines[1],
            source_factory=sessionmaker(bind=engines[0], autoflush=False),
            writer_factory=sessionmaker(bind=engines[1], autoflush=False),
        )
    finally:
        for engine in engines:
            engine.dispose()
        for role in reversed(roles):
            world.core_sql(sql.SQL("DROP OWNED BY {}").format(role))
            world.core_sql(sql.SQL("DROP ROLE {}").format(role))


def actor(c):
    return official_auth.resolve_prepared_official_auth_context(
        c.world.factory, c.world.token, logical_app_id="docs"
    ).user


def invoke_source(c, user=None):
    source.require_prepared_docs_edit_access(
        c.source_factory,
        page_ref="native_doc_page__" + c.world.ids["ws_page"],
        user=actor(c) if user is None else user,
    )


def shared(c, level="edit"):
    with c.world.core() as db:
        db.get(NativeDoc, c.world.ids["owned"]).owner_id = c.world.state["admin"]["user"]["id"]
        row = NativeDocUserShare(
            id=new_id(),
            doc_id=c.world.ids["owned"],
            user_id=c.world.state["member_id"],
            created_by_id=c.world.state["admin"]["user"]["id"],
            access_level=level,
        )
        db.add(row)
        db.commit()
        return row.id


def native_app(c, monkeypatch):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == "miy_api.domains.docs.router" and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app = FastAPI()
    hub = SyntheticHub(c.world.writer)
    app.state.docs_collab = hub
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=c.world.factory,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=c.source_factory,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=c.writer_factory,
        official_writer_read_max_concurrent_reads=1,
    )
    initial = []

    def source_factory():
        initial.append("initial native Source")
        return c.world.core

    monkeypatch.setattr(docs, "get_session_factory", source_factory)
    return app, hub, initial


def callback(c, monkeypatch):
    app, hub, _ = native_app(c, monkeypatch)
    monkeypatch.setattr(
        docs, "get_session_factory", lambda: pytest.fail("explicit frame allocated global Source")
    )
    return partial(
        docs._authorize_prepared_docs_source_access,
        socket_connection(app),
        page_ref="native_doc_page__" + c.world.ids["ws_page"],
        token=c.world.token,
        user_id=c.world.state["member_id"],
        source_session_id=c.world.state["source_id"],
        auth_dependency=app.state.prepared_official_auth_dependency,
        source_access=app.state.prepared_docs_source_access,
        writer_access=app.state.prepared_official_writer_access,
        hub=hub,
        writer_identity=hub.writer_identity,
    )


def test_genuine_column_only_docs_and_disjoint_core_writer_reads(docs_world, monkeypatch):
    c = docs_world
    source_commands, writer_commands = [], []
    event.listen(
        c.source_engine,
        "before_cursor_execute",
        lambda _a, _b, statement, *_: source_commands.append(statement),
    )
    event.listen(
        c.writer_engine,
        "before_cursor_execute",
        lambda _a, _b, statement, *_: writer_commands.append(statement),
    )
    anyio.run(callback(c, monkeypatch))
    assert sum("official_runtime_ownership" in statement for statement in writer_commands) == 2
    assert not any("official_runtime_ownership" in statement for statement in source_commands)
    assert not any("docs_native" in statement for statement in writer_commands)
    assert not any(
        "content_blocks" in statement
        or "content_text" in statement
        or "password_hash" in statement
        or "docs_native_doc_link_shares" in statement
        for statement in source_commands
    )
    assert not any(
        statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        for statement in source_commands + writer_commands
    )
    with c.source_factory() as db:
        context = load_native_page_for_acl_or_404(db, page_id=c.world.ids["ws_page"], user=actor(c))
        for record, field in (
            (context.page, "content_blocks"),
            (context.page, "created_by"),
            (context.doc, "title"),
            (context.doc, "pages"),
        ):
            with pytest.raises(InvalidRequestError):
                getattr(record, field)


@pytest.mark.parametrize(
    "kind,statement",
    [
        ("source", "SELECT content_blocks FROM public.docs_native_doc_pages LIMIT 0"),
        ("source", "SELECT title FROM public.docs_native_docs LIMIT 0"),
        ("source", "SELECT scope FROM public.official_runtime_ownership LIMIT 0"),
        ("source", "SELECT password_hash FROM public.users LIMIT 0"),
        ("source", "SELECT full_name FROM public.users LIMIT 0"),
        ("source", "SELECT token_hash FROM public.auth_sessions LIMIT 0"),
        (
            "source",
            "UPDATE public.docs_native_doc_pages SET content_format=content_format WHERE false",
        ),
        ("writer", "SELECT id FROM public.docs_native_docs LIMIT 0"),
        ("writer", "SELECT id FROM public.auth_sessions LIMIT 0"),
        ("writer", "SELECT request_id FROM public.official_runtime_transitions LIMIT 0"),
        ("writer", "UPDATE public.official_runtime_ownership SET state=state WHERE false"),
    ],
)
def test_genuine_roles_cannot_read_unrelated_columns_or_write(docs_world, kind, statement):
    engine = docs_world.source_engine if kind == "source" else docs_world.writer_engine
    with engine.connect() as db:
        with pytest.raises(DBAPIError) as denied:
            db.execute(text(statement))
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "change", ["read", "share", "doc_trash", "page_trash", "app", "user", "format", "prefix"]
)
def test_genuine_current_docs_acl_and_native_page_scope_remain_required(docs_world, change):
    c = docs_world
    current = actor(c)
    identifier = shared(c, "read" if change == "read" else "edit")
    with c.world.core() as db:
        if change == "share":
            db.delete(db.get(NativeDocUserShare, identifier))
        elif change == "doc_trash":
            db.get(NativeDoc, c.world.ids["owned"]).trashed_at = utcnow_naive()
        elif change == "page_trash":
            db.get(NativeDocPage, c.world.ids["ws_page"]).trashed_at = utcnow_naive()
        elif change == "app":
            db.get(CompanyAppControl, "docs").enabled = False
        elif change == "user":
            db.get(User, c.world.state["member_id"]).status = "inactive"
        elif change == "format":
            db.get(NativeDocPage, c.world.ids["ws_page"]).content_format = "html"
        db.commit()
    with pytest.raises(HTTPException) as denied:
        source.require_prepared_docs_edit_access(
            c.source_factory,
            page_ref=("native_doc__" if change == "prefix" else "native_doc_page__")
            + c.world.ids["ws_page"],
            user=current,
        )
    assert denied.value.status_code == (404 if change in {"format", "prefix"} else 403)


@pytest.mark.parametrize("kind", ["local", "hr"])
def test_genuine_docs_group_share_rechecks_current_membership(docs_world, kind):
    from miy_api.domains.docs.models import NativeDocGroupShare
    from miy_api.domains.groups.models import Group, GroupMember

    c = docs_world
    gid = new_id()
    with c.world.core() as db:
        db.get(NativeDoc, c.world.ids["owned"]).owner_id = c.world.state["admin"]["user"]["id"]
        db.add(
            Group(
                id=gid,
                name="Synthetic Docs ACL group",
                source=kind,
                active=True,
                slug="synthetic-" + gid if kind == "hr" else None,
                unit_type="department" if kind == "hr" else None,
            )
        )
        db.flush()
        if kind == "local":
            db.add(GroupMember(group_id=gid, user_id=c.world.state["member_id"]))
        else:
            db.get(User, c.world.state["member_id"]).primary_organization_unit_id = gid
        db.add(
            NativeDocGroupShare(
                doc_id=c.world.ids["owned"],
                group_id=gid,
                created_by_id=c.world.state["admin"]["user"]["id"],
                access_level="edit",
            )
        )
        db.commit()
    invoke_source(c)
    with c.world.core() as db:
        if kind == "local":
            db.delete(db.get(GroupMember, (gid, c.world.state["member_id"])))
        else:
            db.get(User, c.world.state["member_id"]).primary_organization_unit_id = None
        db.commit()
    with pytest.raises(HTTPException) as denied:
        invoke_source(c)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_genuine_current_meeting_access_expiry_or_revoke_blocks_docs_edit(docs_world, state):
    c = docs_world
    with c.world.core() as db:
        db.get(NativeDoc, c.world.ids["owned"]).owner_id = c.world.state["admin"]["user"]["id"]
        grant = DocMeetingAccess(
            id=new_id(),
            doc_id=c.world.ids["owned"],
            user_id=c.world.state["member_id"],
            access_level="edit",
            granted_by_user_id=c.world.state["admin"]["user"]["id"],
        )
        db.add(grant)
        db.commit()
        identifier = grant.id
    invoke_source(c)
    with c.world.core() as db:
        grant = db.get(DocMeetingAccess, identifier)
        if state == "expired":
            grant.expires_at = utcnow_naive() - timedelta(seconds=1)
        else:
            grant.revoked_at = utcnow_naive()
        db.commit()
    with pytest.raises(HTTPException) as denied:
        invoke_source(c)
    assert denied.value.status_code == 403


def test_genuine_pms_target_current_edit_member_and_app_revocation(docs_world):
    from company_admission_fixture import seed_company_app_access
    from miy_api.domains.docs.models import NativeDocTarget
    from miy_api.domains.pms.space_models import Team, TeamMember

    c = docs_world
    with c.world.core() as db:
        seed_company_app_access(db, app_ids=["pms"])
        db.get(NativeDoc, c.world.ids["owned"]).owner_id = c.world.state["admin"]["user"]["id"]
        team = Team(id=new_id(), key="synthetic-" + token_hex(4), name="Synthetic Docs target")
        db.add(team)
        db.flush()
        db.add_all(
            [
                TeamMember(
                    id=new_id(), team_id=team.id, user_id=c.world.state["member_id"], role="member"
                ),
                NativeDocTarget(
                    id=new_id(),
                    doc_id=c.world.ids["owned"],
                    target_app="pms",
                    target_type="space",
                    target_id=team.id,
                ),
            ]
        )
        db.commit()
    invoke_source(c)
    with c.world.core() as db:
        db.get(CompanyAppControl, "pms").enabled = False
        db.commit()
    with pytest.raises(HTTPException) as denied:
        invoke_source(c)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("kind", ["source", "writer"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_readers_refuse_stale_or_autocommit_transactions(docs_world, kind, isolation):
    c = docs_world
    engine = (c.source_engine if kind == "source" else c.writer_engine).execution_options(
        isolation_level=isolation
    )
    factory = sessionmaker(bind=engine)
    with pytest.raises(
        source.DocsSourceReaderRefused if kind == "source" else writer.CoreWriterReaderRefused
    ) as denied:
        if kind == "source":
            source.require_prepared_docs_edit_access(
                factory, page_ref="native_doc_page__" + c.world.ids["ws_page"], user=actor(c)
            )
        else:
            writer.require_prepared_active_writer(factory, writer_identity=c.world.writer)
    assert denied.value.reason == "read_committed_required"


def test_genuine_temp_shadow_cannot_replace_public_page_or_core_writer(docs_world):
    c = docs_world

    def factory(base, statement):
        db = base()
        db.execute(text(statement))
        db.commit()
        db.expunge_all()
        return db

    invoke = partial(
        source.require_prepared_docs_edit_access,
        partial(
            factory,
            c.source_factory,
            "CREATE TEMP TABLE docs_native_doc_pages (id text, doc_id text, content_format text, trashed_at timestamp)",
        ),
        page_ref="native_doc_page__" + c.world.ids["ws_page"],
        user=actor(c),
    )
    invoke()
    writer.require_prepared_active_writer(
        partial(
            factory,
            c.writer_factory,
            "CREATE TEMP TABLE official_runtime_ownership (scope text, active_owner text, generation integer, artifact text, state text, updated_at timestamp)",
        ),
        writer_identity=c.world.writer,
    )


@pytest.mark.parametrize("change", ["generation", "owner", "artifact", "draining"])
def test_genuine_core_writer_never_adopts_current_state(docs_world, change):
    c = docs_world
    with c.world.core() as db:
        row = db.get(RuntimeOwnership, SUITE_SCOPE)
        if change == "generation":
            row.generation += 1
        elif change == "owner":
            row.active_owner = "official-suite"
        elif change == "artifact":
            row.artifact = "sha256:" + "b" * 64
        else:
            row.state = "draining"
        db.commit()
    with pytest.raises(HTTPException) as denied:
        writer.require_prepared_active_writer(c.writer_factory, writer_identity=c.world.writer)
    assert docs.writer_close_choice(denied.value) == (1013, "official_writer_unavailable")


@pytest.mark.parametrize("failure", ["source_sql", "writer_sql", "drain"])
def test_genuine_native_receive_blocks_private_reader_failures_and_only_drain_fences(
    docs_world, monkeypatch, failure
):
    c = docs_world
    app, hub, initial = native_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"

            def fail(*a, **k):
                raise SQLAlchemyError("private")

            if failure == "source_sql":
                monkeypatch.setattr(source, "require_prepared_docs_edit_access", fail)
            elif failure == "writer_sql":
                monkeypatch.setattr(writer, "require_prepared_active_writer", fail)
            else:
                with c.world.core() as db:
                    db.get(RuntimeOwnership, SUITE_SCOPE).state = "draining"
                    db.commit()
            socket.send_bytes(b"forbidden update")
            with pytest.raises(WebSocketDisconnect) as denied:
                socket.receive_bytes()
            assert denied.value.code == 1013
            assert denied.value.reason == (
                "official_writer_unavailable"
                if failure == "drain"
                else "official_authority_unavailable"
            )
    assert not hub.room.effects
    assert hub.fenced == ([hub.runtime] if failure == "drain" else [])
    assert len(initial) == 1


@pytest.mark.parametrize("direction", ["recv", "send", "monitor"])
def test_genuine_native_authorization_rechecks_real_source_session_revocation(
    docs_world, monkeypatch, direction
):
    c = docs_world
    if direction == "monitor":
        monkeypatch.setattr(
            docs, "get_settings", lambda: SimpleNamespace(collab_acl_recheck_seconds=0.02)
        )
    app, hub, initial = native_app(c, monkeypatch)

    def revoke():
        with c.world.core() as db:
            db.get(AuthSession, c.world.state["source_id"]).revoked_at = utcnow_naive()
            db.commit()

    with TestClient(app) as client:
        with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            if direction == "send":
                hub.room.after_receive = revoke
                socket.send_bytes(b"admitted before revoke")
            else:
                revoke()
                if direction == "recv":
                    socket.send_bytes(b"forbidden update")
            with pytest.raises(WebSocketDisconnect):
                socket.receive_bytes()
    assert hub.room.effects == ([b"admitted before revoke"] if direction == "send" else [])
    assert not hub.fenced and len(initial) == 1


@pytest.mark.parametrize("kind", ["Source", "Core"])
@pytest.mark.parametrize("revoke", ["session", "app"])
def test_genuine_lock_wait_rechecks_current_auth_after_joined_cleanup(
    docs_world, monkeypatch, kind, revoke
):
    c = docs_world
    authorize = callback(c, monkeypatch)
    selected = c.source_engine if kind == "Source" else c.writer_engine
    table = "docs_native_doc_pages" if kind == "Source" else "official_runtime_ownership"
    waiting, pids = Event(), []

    def observe(connection, _cursor, statement, *_):
        if "FROM " + table in statement:
            pids.append(connection.connection.driver_connection.info.backend_pid)
            waiting.set()

    event.listen(selected, "before_cursor_execute", observe)
    # All owned control connections are established before the source/core lock.
    lock, observer, revoker = c.world.core(), c.world.core(), c.world.core()
    for db in (lock, observer, revoker):
        db.execute(select(1))
    lock.execute(text("LOCK TABLE public." + table + " IN ACCESS EXCLUSIVE MODE"))

    async def scenario():
        with anyio.fail_after(8):
            task = asyncio.create_task(authorize())
            try:
                while not waiting.is_set():
                    await anyio.sleep(0)
                blocked = False
                for _ in range(200):
                    blocked = bool(
                        observer.scalar(
                            text("SELECT cardinality(pg_catalog.pg_blocking_pids(:pid))>0"),
                            {"pid": pids[0]},
                        )
                    )
                    if blocked:
                        break
                    await anyio.sleep(0.005)
                assert blocked
                if revoke == "session":
                    revoker.get(AuthSession, c.world.state["source_id"]).revoked_at = utcnow_naive()
                else:
                    revoker.get(CompanyAppControl, "docs").enabled = False
                revoker.commit()
            finally:
                lock.rollback()
            with pytest.raises(HTTPException) as denied:
                await task
            assert denied.value.status_code == (401 if revoke == "session" else 403)

    try:
        anyio.run(scenario)
    finally:
        lock.close()
        observer.close()
        revoker.close()
        event.remove(selected, "before_cursor_execute", observe)
    assert waiting.is_set()


@pytest.mark.parametrize("admission", ["company", "admin"])
def test_genuine_company_visible_or_admin_read_never_grants_edit(docs_world, admission):
    from miy_api.domains.auth.models import UserSystemRole

    c = docs_world
    with c.world.core() as db:
        row = db.get(NativeDoc, c.world.ids["owned"])
        row.owner_id = c.world.state["admin"]["user"]["id"]
        row.ownership_kind = "company"
        row.company_visible = admission == "company"
        if admission == "admin":
            db.add(
                UserSystemRole(
                    id=new_id(), user_id=c.world.state["member_id"], role="platform_admin"
                )
            )
        db.commit()
    with pytest.raises(HTTPException) as denied:
        invoke_source(c)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("missing", ["marker", "Source", "Core"])
def test_genuine_incomplete_configured_socket_never_uses_initial_global_factory(
    docs_world, monkeypatch, missing
):
    c = docs_world
    app, hub, initial = native_app(c, monkeypatch)
    if missing == "marker":
        del app.state.prepared_docs_source_configured
    elif missing == "Source":
        del app.state.prepared_docs_source_access
    else:
        del app.state.prepared_official_writer_access
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
                socket.send_json({"type": "auth", "token": c.world.token})
                socket.receive_bytes()
    assert denied.value.code == 1013 and not initial and not hub.acquired and not hub.room.effects


def test_genuine_successful_socket_only_initialization_uses_native_global_factory(
    docs_world, monkeypatch
):
    c = docs_world
    app, hub, initial = native_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"owned update")
            assert socket.receive_bytes() == b"echo:owned update"
    assert hub.room.effects == [b"owned update"] and len(initial) == 1
    assert hub.acquired == hub.released and not hub.fenced


@pytest.mark.parametrize("kind", ["source", "writer"])
def test_genuine_privileged_core_factory_is_reader_failure_not_writer_fence(docs_world, kind):
    c = docs_world
    with pytest.raises(
        source.DocsSourceReaderRefused if kind == "source" else writer.CoreWriterReaderRefused
    ) as denied:
        if kind == "source":
            source.require_prepared_docs_edit_access(
                c.world.core, page_ref="native_doc_page__" + c.world.ids["ws_page"], user=actor(c)
            )
        else:
            writer.require_prepared_active_writer(c.world.core, writer_identity=c.world.writer)
    assert denied.value.reason == (
        "source_role_required" if kind == "source" else "core_reader_role_required"
    )


def test_core_reader_refuses_client_shaped_identity_before_session_allocation():
    def factory():
        pytest.fail("Client-shaped writer identity allocated a Core Session")

    with pytest.raises(writer.CoreWriterReaderRefused) as denied:
        writer.require_prepared_active_writer(
            factory, writer_identity={"scope": SUITE_SCOPE, "owner": "legacy", "generation": 1}
        )
    assert denied.value.reason == "pinned_writer_identity_required"
