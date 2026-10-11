"""Explicit inactive Docs Source ACL and separate Core writer read assembly."""

import asyncio
from functools import partial
from secrets import token_hex
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import sessionmaker

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import new_id
from miy_api.domains.docs import collab_source_access as source, router as docs
from miy_api.domains.docs.access_context import load_native_page_for_acl_or_404
from miy_api.domains.docs.models import (
    NativeDoc,
    NativeDocUserShare,
)
from miy_api.domains.official_apps import owned_read_session as guards, writer_access as writer
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_prepared_official_ws_auth import (
    SyntheticHub as SyntheticHub,
    socket_connection as socket_connection,
    socket_path as socket_path,
    ws_world as ws_world,  # noqa: F401
)
from test_prepared_whiteboard_source_access import Marker as Marker, MarkerBase as MarkerBase


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


@pytest.mark.parametrize("kind,running", [("docs", True)])
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

    # The same native profile may read its declared data, but cannot expand authority.
    with docs_world.source_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(
                text("SELECT content_blocks FROM public.docs_native_doc_pages LIMIT 0")
            )
        assert denied.value.orig.sqlstate == "42501"
    with docs_world.source_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("SELECT password_hash FROM public.users LIMIT 0"))
        assert denied.value.orig.sqlstate == "42501"
    with docs_world.source_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(
                text(
                    "UPDATE public.docs_native_doc_pages SET content_format=content_format WHERE false"
                )
            )
        assert denied.value.orig.sqlstate == "42501"
    with docs_world.writer_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("SELECT id FROM public.docs_native_docs LIMIT 0"))
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("kind", ["local"])
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


@pytest.mark.parametrize("kind,revoke", [("Source", "session"), ("Core", "app")])
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
