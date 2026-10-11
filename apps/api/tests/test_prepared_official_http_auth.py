"""Explicit inactive HTTP assembly; pure adapter controls and genuine restricted PG."""

from threading import Event
from types import SimpleNamespace

import anyio
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from test_official_authority_reader import authority as authority
from test_official_authority_reader import bound_official as bound_official
from test_official_authority_reader import client as client
from test_official_authority_reader import isolated_data_cluster as isolated_data_cluster
from test_official_authority_reader import role_template as role_template

from miy_api import api_registry, official_auth
from miy_api.api_composition import RouterSpec
from miy_api.app import localized_http_exception_handler
from miy_api.core.db import get_db_session
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import require_auth_context, require_current_user


def probe_app(monkeypatch, *, scope="docs", factory=lambda: None, budget=1):
    router, child = APIRouter(), APIRouter()

    @child.get("/prepared-probe")
    def probe(user=Depends(require_current_user), context=Depends(require_auth_context)):
        return {"id": user.id, "roles": sorted(context.system_roles)}

    router.include_router(child)
    monkeypatch.setattr(
        api_registry,
        "router_specs",
        lambda _: (RouterSpec(router, "protected", 0, "official", "fixture", scope),),
    )
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.dependency_overrides[get_db_session] = lambda: pytest.fail("auth used Source Session")
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=factory,
        official_auth_max_concurrent_reads=budget,
    )
    return app


def request_for(app):
    return Request(
        {"type": "http", "app": app, "state": {"official_logical_app_id": "docs"}, "headers": []}
    )


def test_waiting_cancel_does_not_allocate_and_running_cancel_keeps_owned_work(monkeypatch):
    started, release, finished = Event(), Event(), Event()
    calls = []
    context = SimpleNamespace(user=SimpleNamespace(id="member"), system_roles=frozenset())

    def resolve(factory, token, *, logical_app_id):
        calls.append(factory())
        started.set()
        try:
            assert release.wait(3)
            return context
        finally:
            finished.set()

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", resolve)
    dependency = official_auth.build_prepared_official_auth_dependency(
        session_factory=lambda: "owned", max_concurrent_reads=1
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic")
    scopes = {}
    app = FastAPI()

    async def invoke(label):
        with anyio.CancelScope() as cancel:
            scopes[label] = cancel
            await dependency(request_for(app), credentials)
        scopes[label + "_done"] = True

    async def scenario():
        with anyio.fail_after(3):
            async with anyio.create_task_group() as tasks:
                try:
                    tasks.start_soon(invoke, "running")
                    while not started.is_set():
                        await anyio.sleep(0)
                    tasks.start_soon(invoke, "waiting")
                    while "waiting" not in scopes:
                        await anyio.sleep(0)
                    scopes["waiting"].cancel()
                    while not scopes.get("waiting_done"):
                        await anyio.sleep(0)
                    assert calls == ["owned"]
                    scopes["running"].cancel()
                    await anyio.sleep(0.02)
                    assert not finished.is_set() and not scopes.get("running_done")
                finally:
                    release.set()
            assert finished.is_set() and scopes["running_done"]
            assert await dependency(request_for(app), credentials) is context

    anyio.run(scenario)
    assert calls == ["owned", "owned"]


# Genuine lifecycle/profile fixtures; no operational database or broad auth mock.


@pytest.fixture
def http_world(authority, client):
    from company_admission_fixture import seed_company_app_access
    from sqlalchemy import event
    from test_independent_app_delivery import FakeRuntime, current_installation, enqueue, execute
    from test_independent_apps import exchange, launch

    from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
    from miy_api.domains.auth.models import User
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.docs.models import NativeDoc, NativeDocPage, NativeDocUserShare
    from miy_api.domains.official_apps.auth import approve_binding
    from miy_api.domains.whiteboard.models import Whiteboard

    world = authority
    state = world.state
    # A genuine next deployment generation makes a fresh immutable binding.
    # No UPDATE of binding scope, fake permission or changed reader admission.
    installation = current_installation(state["installation"]["id"])
    deployment, _ = enqueue(
        client,
        (
            state["admin"],
            {"Authorization": "Bearer " + state["admin"]["token"]},
            None,
            installation,
            None,
        ),
        state["release_id"],
    )
    assert execute(deployment, FakeRuntime()).state == "succeeded"
    installation = current_installation(installation["id"])
    with world.core() as db:
        seed_company_app_access(db, app_ids=["docs", "whiteboard"])
        admin = resolve_auth_context_from_token(db, state["admin"]["token"], update_last_seen=False)
        binding = approve_binding(
            db,
            admin,
            installation_id=installation["id"],
            expected_generation=installation["generation"],
            expected_release_id=state["release_id"],
            expected_artifact="sha256:" + "a" * 64,
            logical_app_ids=frozenset({"docs", "whiteboard"}),
        )
        member = state["member_id"]
        other = User(
            id=new_id(),
            login_id="unshared-http-owner",
            email="unshared@example.test",
            full_name="Synthetic owner",
            password_hash="synthetic",
        )
        db.add(other)
        db.flush()
        owned = NativeDoc(id=new_id(), owner_id=member, title="Owned synthetic document")
        shared = NativeDoc(id=new_id(), owner_id=admin.user.id, title="Shared synthetic document")
        private = NativeDoc(id=new_id(), owner_id=other.id, title="Private synthetic document")
        board = Whiteboard(id=new_id(), owner_id=member, title="Synthetic board")
        db.add_all([owned, shared, private, board])
        db.flush()
        page = NativeDocPage(
            id=new_id(),
            doc_id=shared.id,
            title="Synthetic page",
            created_by_id=admin.user.id,
            content_text="Owned test text",
        )
        share = NativeDocUserShare(
            id=new_id(),
            doc_id=shared.id,
            user_id=member,
            created_by_id=admin.user.id,
            access_level="read",
        )
        db.add_all([page, share])
        db.commit()
        world.ids = dict(
            owned=owned.id,
            shared=shared.id,
            private=private.id,
            board=board.id,
            page=page.id,
            share=share.id,
            binding=binding.id,
        )
    exchanged = exchange(
        client, launch(client, {"Authorization": "Bearer " + state["login_token"]}, installation)
    )
    assert exchanged.status_code == 200
    world.token = exchanged.json()["token"]
    world.source_calls = []
    world.auth_commands = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        world.auth_commands.append(statement.lstrip().split()[0].upper())

    event.listen(world.engine, "before_cursor_execute", capture)
    try:
        yield world
    finally:
        event.remove(world.engine, "before_cursor_execute", capture)


def native_app(monkeypatch, world, *, factory=None, after_lookup=None):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source
        in {
            "miy_api.domains.docs.router",
            "miy_api.domains.docs.group_sharing",
            "miy_api.domains.whiteboard.router",
        }
        and spec.protection == "protected"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)

    def source():
        world.source_calls.append("Source")
        with world.core() as db:
            yield db

    app.dependency_overrides[get_db_session] = source
    if after_lookup is not None:
        original = official_auth.resolve_prepared_official_auth_context

        def coordinated(*args, **kwargs):
            context = original(*args, **kwargs)
            after_lookup()
            return context

        monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", coordinated)
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=world.factory if factory is None else factory,
        official_auth_max_concurrent_reads=1,
    )
    return app


def native_headers(world):
    return {"Authorization": "Bearer " + world.token}


def source_snapshot(world):
    from sqlalchemy import func, select

    from miy_api.domains.auth.models import AuditLog, AuthSession
    from miy_api.domains.docs.models import NativeDocPage
    from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
    from miy_api.domains.rag.models import RagSyncJob
    from miy_api.domains.search.models import SearchIndexJob

    with world.core() as db:
        return (
            db.get(AuthSession, world.state["source_id"]).last_seen_at,
            db.get(NativeDocPage, world.ids["page"]).title,
            *(
                db.scalar(select(func.count()).select_from(model))
                for model in (AuditLog, OfficialProjectionOutbox, RagSyncJob, SearchIndexJob)
            ),
        )


def test_genuine_four_routes_use_restricted_detached_auth_and_source_acl(http_world, monkeypatch):
    world = http_world
    before = source_snapshot(world)
    calls = []

    def factory():
        calls.append("auth")
        return world.factory()

    app = native_app(monkeypatch, world, factory=factory)
    with TestClient(app) as client:
        for path in [
            f"/docs/items/{world.ids['owned']}",
            f"/docs/items/{world.ids['shared']}/pages",
            f"/docs/items/{world.ids['owned']}/sharing/groups",
            f"/whiteboard/items/{world.ids['board']}",
        ]:
            assert client.get("/api/v1" + path, headers=native_headers(world)).status_code == 200
        assert (
            client.get(
                f"/api/v1/docs/items/{world.ids['private']}", headers=native_headers(world)
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/docs/items/{world.ids['shared']}/sharing/groups",
                headers=native_headers(world),
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/docs/pages/{world.ids['page']}",
                headers=native_headers(world),
                json={"title": "Forbidden change"},
            ).status_code
            == 403
        )
    assert len(calls) == 7
    assert world.auth_commands and set(world.auth_commands) <= {"SELECT", "SHOW", "SET"}
    assert source_snapshot(world) == before


def test_real_profile_refusal_is_503_before_source_and_does_not_fall_back(http_world, monkeypatch):
    world = http_world
    monkeypatch.setattr(
        official_auth,
        "resolve_official_auth_context",
        lambda *a, **k: pytest.fail("broad fallback"),
    )
    # The isolated business role is intentionally broader than the14/87 auth role.
    with TestClient(native_app(monkeypatch, world, factory=world.core)) as client:
        response = client.get(
            f"/api/v1/docs/items/{world.ids['owned']}", headers=native_headers(world)
        )
    assert response.status_code == 503
    assert response.json()["code"] == "official_apps.authority_unavailable"
    assert world.source_calls == []
