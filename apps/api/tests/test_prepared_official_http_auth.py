"""Explicit inactive HTTP assembly; pure adapter controls and genuine restricted PG."""

from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from miy_api import api_registry, official_auth
from miy_api.api_composition import RouterSpec
from miy_api.app import localized_http_exception_handler
from miy_api.core.db import get_db_session
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import require_auth_context, require_current_user
from miy_api.domains.official_apps.authority_reader import OfficialAuthorityReaderRefused


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


def test_explicit_prepared_http_factory_replaces_only_owned_auth(monkeypatch):
    seen = []
    marker = object()
    app = probe_app(monkeypatch, factory=lambda: marker)

    def resolve(factory, token, *, logical_app_id):
        seen.append((factory(), token, logical_app_id))
        return SimpleNamespace(user=SimpleNamespace(id="member"), system_roles=frozenset({"user"}))

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", resolve)
    monkeypatch.setattr(
        official_auth, "resolve_official_auth_context", lambda *a, **k: pytest.fail("fallback")
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/prepared-probe?logical_app_id=pms",
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-MIY-App-Id": "pms",
                "X-MIY-User-Id": "admin",
                "X-MIY-System-Roles": "platform_admin",
            },
        )
    assert response.status_code == 200
    assert response.json() == {"id": "member", "roles": ["user"]}
    assert seen == [(marker, "synthetic-token", "docs")]


@pytest.mark.parametrize(
    "composition,factory,budget",
    [
        ("official", lambda: None, None),
        ("official", None, 1),
        ("legacy", lambda: None, 1),
        ("platform", lambda: None, 1),
        ("unknown", lambda: None, 1),
    ],
)
def test_partial_or_nonofficial_prepared_options_refused_before_assembly(
    composition, factory, budget
):
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(
            app,
            get_settings(),
            composition=composition,
            official_auth_session_factory=factory,
            official_auth_max_concurrent_reads=budget,
        )
    assert require_auth_context not in app.dependency_overrides
    assert not any(route.path.startswith("/api/") for route in app.routes)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "1"])
def test_prepared_budget_is_explicit_positive_integer(budget):
    with pytest.raises(ValueError):
        official_auth.build_prepared_official_auth_dependency(
            session_factory=lambda: None, max_concurrent_reads=budget
        )


@pytest.mark.parametrize(
    "header,scope,status",
    [
        (None, "docs", 401),
        ("Basic synthetic", "docs", 401),
        ("Bearer synthetic", None, 403),
        ("Bearer synthetic", "unknown", 403),
    ],
)
def test_input_denial_precedes_auth_and_source_allocation(monkeypatch, header, scope, status):
    app = probe_app(
        monkeypatch, scope=scope, factory=lambda: pytest.fail("denied input allocated Session")
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/prepared-probe", headers={} if header is None else {"Authorization": header}
        )
    assert response.status_code == status


@pytest.mark.parametrize(
    "error", [OfficialAuthorityReaderRefused("private detail"), SQLAlchemyError("private detail")]
)
def test_prepared_failure_is_private_503_without_fallback(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", fail)
    monkeypatch.setattr(
        official_auth, "resolve_official_auth_context", lambda *a, **k: pytest.fail("fallback")
    )
    with TestClient(probe_app(monkeypatch)) as client:
        response = client.get(
            "/api/v1/prepared-probe", headers={"Authorization": "Bearer synthetic"}
        )
    assert response.status_code == 503
    assert response.json()["code"] == "official_apps.authority_unavailable"
    assert "private detail" not in response.text


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
from test_official_authority_reader import (  # noqa: E402
    authority as authority,
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)


@pytest.fixture
def http_world(authority, client):
    from sqlalchemy import event
    from company_admission_fixture import seed_company_app_access
    from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
    from miy_api.domains.auth.models import User
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.docs.models import NativeDoc, NativeDocPage, NativeDocUserShare
    from miy_api.domains.official_apps.auth import approve_binding
    from miy_api.domains.whiteboard.models import Whiteboard
    from test_independent_app_delivery import FakeRuntime, current_installation, enqueue, execute
    from test_independent_apps import exchange, launch

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


@pytest.mark.parametrize("revocation", ["source", "delegated", "binding", "app", "user"])
def test_next_http_request_observes_current_real_revocation(http_world, monkeypatch, revocation):
    from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
    from miy_api.domains.auth.security import hash_token
    from miy_api.domains.independent_apps.models import AppSession
    from miy_api.domains.official_apps.models import OfficialAppBinding

    world = http_world
    with TestClient(native_app(monkeypatch, world)) as client:
        path = f"/api/v1/docs/items/{world.ids['owned']}"
        assert client.get(path, headers=native_headers(world)).status_code == 200
        world.source_calls.clear()
        with world.core() as db:
            if revocation == "source":
                db.get(AuthSession, world.state["source_id"]).revoked_at = utcnow_naive()
            elif revocation == "delegated":
                db.get(AppSession, hash_token(world.token)).revoked_at = utcnow_naive()
            elif revocation == "binding":
                db.get(OfficialAppBinding, world.ids["binding"]).revoked_at = utcnow_naive()
            elif revocation == "app":
                db.get(CompanyAppControl, "docs").enabled = False
            else:
                db.get(User, world.state["member_id"]).status = "inactive"
            db.commit()
        response = client.get(path, headers=native_headers(world))
    assert response.status_code in {401, 403}
    assert world.source_calls == []


@pytest.mark.parametrize("change", ["share", "app"])
def test_real_policy_change_after_lookup_is_denied_by_current_source(
    http_world, monkeypatch, change
):
    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.docs.models import NativeDocUserShare

    world = http_world

    def revoke():
        with world.core() as db:
            if change == "share":
                db.delete(db.get(NativeDocUserShare, world.ids["share"]))
            else:
                db.get(CompanyAppControl, "docs").enabled = False
            db.commit()

    with TestClient(native_app(monkeypatch, world, after_lookup=revoke)) as client:
        response = client.get(
            f"/api/v1/docs/items/{world.ids['shared']}/pages", headers=native_headers(world)
        )
    assert response.status_code == (404 if change == "share" else 403)
    assert world.source_calls


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


def test_actual_reader_rejects_borrowed_caller_without_sql_or_cleanup(http_world, monkeypatch):
    from sqlalchemy import event
    from miy_api.domains.auth.models import User

    world = http_world
    db = world.factory()
    marker = User(
        id="pending-marker",
        login_id="pending-marker",
        email="marker@example.test",
        full_name="Synthetic",
        password_hash="synthetic",
    )
    db.add(marker)
    commands = []

    def trap(*args):
        commands.append(1)

    event.listen(world.engine, "before_cursor_execute", trap)
    try:
        with TestClient(native_app(monkeypatch, world, factory=lambda: db)) as client:
            response = client.get(
                f"/api/v1/docs/items/{world.ids['owned']}", headers=native_headers(world)
            )
        assert response.status_code == 503 and marker in db.new
        assert db.in_transaction() and not commands and not world.source_calls
    finally:
        event.remove(world.engine, "before_cursor_execute", trap)
        db.rollback()
        db.close()


@pytest.mark.parametrize("token", [None, "unknown-delegated-token"])
def test_genuine_missing_or_invalid_credential_never_acquires_source(
    http_world, monkeypatch, token
):
    world = http_world
    with TestClient(native_app(monkeypatch, world)) as client:
        response = client.get(
            f"/api/v1/docs/items/{world.ids['owned']}",
            headers={} if token is None else {"Authorization": "Bearer " + token},
        )
    assert response.status_code == 401 and not world.source_calls


def test_real_docs_only_binding_cannot_claim_whiteboard_scope(authority, monkeypatch):
    world = authority
    world.source_calls = []
    world.token = world.state["app_token"]
    with TestClient(native_app(monkeypatch, world)) as client:
        response = client.get(
            "/api/v1/whiteboard/items/synthetic",
            headers=native_headers(world) | {"X-MIY-App-Id": "docs"},
        )
    assert response.status_code == 403 and not world.source_calls


@pytest.mark.parametrize("status", [401, 403])
def test_prepared_current_policy_http_errors_are_preserved(monkeypatch, status):
    def denied(*args, **kwargs):
        raise HTTPException(status_code=status, detail="current policy denial")

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", denied)
    with TestClient(probe_app(monkeypatch)) as client:
        response = client.get(
            "/api/v1/prepared-probe", headers={"Authorization": "Bearer synthetic"}
        )
    assert response.status_code == status and response.json()["detail"] == "current policy denial"


def test_prepared_cancellation_control_is_not_reclassified_or_retried(monkeypatch):
    class ControlledCancellation(BaseException):
        pass

    attempts = []

    def interrupted(*args, **kwargs):
        attempts.append(1)
        raise ControlledCancellation()

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", interrupted)
    dependency = official_auth.build_prepared_official_auth_dependency(
        session_factory=lambda: None, max_concurrent_reads=1
    )

    async def scenario():
        with pytest.raises(ControlledCancellation):
            await dependency(
                request_for(FastAPI()),
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic"),
            )

    anyio.run(scenario)
    assert attempts == [1]


@pytest.mark.parametrize("kind", ["active", "nested", "cached", "routed", "custom", "connection"])
def test_real_reader_before_sql_rejection_preserves_borrowed_session(monkeypatch, kind):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session, make_transient_to_detached
    from miy_api.domains.auth.models import User

    first, other = create_engine("sqlite://"), create_engine("sqlite://")
    commands, cleanup = [], []
    connection = first.connect() if kind == "connection" else None

    class Routed(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            return first

    db = (
        Routed(bind=first)
        if kind == "custom"
        else Session(
            bind=connection if connection is not None else first,
            binds={User: other} if kind == "routed" else None,
        )
    )
    marker = None
    if kind == "active":
        db.begin()
    elif kind == "nested":
        db.begin_nested()
    elif kind == "cached":
        marker = User(
            id="cached",
            login_id="cached",
            full_name="Synthetic",
            email="cached@example.test",
            password_hash="synthetic",
        )
        make_transient_to_detached(marker)
        db.add(marker)
        # Idle caller with cached identity, not pending work or active SQL.
        db.commit()
    transaction, nested = db.get_transaction(), db.get_nested_transaction()
    original_rollback, original_close = db.rollback, db.close
    monkeypatch.setattr(db, "rollback", lambda: cleanup.append("rollback"))
    monkeypatch.setattr(db, "close", lambda: cleanup.append("close"))

    def record(*args):
        commands.append(1)

    event.listen(first, "before_cursor_execute", record)
    event.listen(other, "before_cursor_execute", record)
    try:
        with TestClient(probe_app(monkeypatch, factory=lambda: db)) as client:
            response = client.get(
                "/api/v1/prepared-probe", headers={"Authorization": "Bearer synthetic"}
            )
        assert response.status_code == 503
        assert not cleanup and not commands
        assert db.get_transaction() is transaction and db.get_nested_transaction() is nested
        if marker is not None:
            assert marker in db.identity_map.values()
    finally:
        event.remove(first, "before_cursor_execute", record)
        event.remove(other, "before_cursor_execute", record)
        original_rollback()
        original_close()
        if connection is not None:
            connection.close()
        first.dispose()
        other.dispose()


def test_explicit_selection_preserves_real_router_openapi_and_default_adapter(monkeypatch):
    specs = api_registry.router_specs("official")
    monkeypatch.setattr(api_registry, "router_specs", lambda _: specs)
    legacy = FastAPI()
    api_registry.register_api_routers(legacy, get_settings(), composition="official")
    prepared = FastAPI()
    api_registry.register_api_routers(
        prepared,
        get_settings(),
        composition="official",
        official_auth_session_factory=lambda: None,
        official_auth_max_concurrent_reads=1,
    )
    assert (
        legacy.dependency_overrides[require_auth_context]
        is official_auth.require_official_auth_context
    )
    assert (
        prepared.dependency_overrides[require_auth_context]
        is not official_auth.require_official_auth_context
    )
    assert prepared.openapi() == legacy.openapi()


@pytest.mark.parametrize("mode", ["waiting", "running", "repeated_running"])
def test_raw_asyncio_cancel_preserves_real_worker_admission_and_cleanup(monkeypatch, mode):
    import asyncio

    started, release, finished, second_started = Event(), Event(), Event(), Event()
    calls = []
    context = SimpleNamespace(user=SimpleNamespace(id="member"), system_roles=frozenset())

    def resolve(factory, token, *, logical_app_id):
        calls.append(factory())
        if len(calls) == 1:
            started.set()
            try:
                assert release.wait(3)
            finally:
                finished.set()
        else:
            second_started.set()
        return context

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", resolve)
    dependency = official_auth.build_prepared_official_auth_dependency(
        session_factory=lambda: "owned", max_concurrent_reads=1
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic")

    async def invoke():
        return await dependency(request_for(FastAPI()), credentials)

    async def scenario():
        with anyio.fail_after(3):
            first = asyncio.create_task(invoke())
            second = None
            try:
                while not started.is_set():
                    await anyio.sleep(0)
                if mode == "waiting":
                    second = asyncio.create_task(invoke())
                    await anyio.sleep(0.02)
                    second.cancel()
                    await anyio.sleep(0.02)
                    valid = second.cancelled() and calls == ["owned"]
                else:
                    first.cancel()
                    second = asyncio.create_task(invoke())
                    await anyio.sleep(0.02)
                    if mode == "repeated_running":
                        first.cancel()
                        await anyio.sleep(0.02)
                        first.cancel()
                    await anyio.sleep(0.02)
                    valid = not first.done() and not second_started.is_set()
            finally:
                release.set()
                await asyncio.gather(
                    first, *([] if second is None else [second]), return_exceptions=True
                )
                while not finished.is_set():
                    await anyio.sleep(0)
            assert valid
            assert second.cancelled() if mode == "waiting" else first.cancelled()
            assert await invoke() is context

    anyio.run(scenario)
