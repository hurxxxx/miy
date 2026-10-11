"""Explicit inactive Whiteboard ACL reads; no operational Source activation."""

from functools import partial
from secrets import token_hex
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.whiteboard import collab_source_access as source, router as whiteboard
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardUserShare
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
)


class MarkerBase(DeclarativeBase):
    pass


class Marker(MarkerBase):
    __tablename__ = "synthetic_caller_marker"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str]


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

    # The same native profile may read its declared data, but cannot expand authority.
    with source_world.engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("SELECT password_hash FROM public.users"))
        assert denied.value.orig.sqlstate == "42501"
    with source_world.engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("SELECT * FROM public.official_runtime_ownership"))
        assert denied.value.orig.sqlstate == "42501"
    with source_world.engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("UPDATE public.whiteboards SET title=title WHERE false"))
        assert denied.value.orig.sqlstate == "42501"


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
