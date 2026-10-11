"""Native Core binding allocation is independent of successful deployment epochs."""

from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text

from miy_api.core.db import get_session_factory
from miy_api.core.settings import WORKSPACE_ROOT, get_settings
from miy_api.domains.independent_apps import data_store, local_runtime, search_consumer
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.search_backends import SearchFailure, marker
from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    delivery_app as delivery_app,
    enqueue,
)


def define(client, app, text_field):
    definition = json.loads(json.dumps(app[2]["definition"]))
    definition["runtime_profile"] = "web-api-postgres-v1"
    definition["requested_permissions"] = ["identity:read", "data:read", "search:read"]
    definition["search"] = {
        "collections": {"notes": {"text_fields": [text_field], "modes": ["keyword", "semantic"]}}
    }
    response = client.put(
        "/api/v1/independent-apps/definitions",
        headers=app[1],
        json={
            "definition": definition,
            "source_revision": "a" * 40,
            "expected_digest": app[2]["definition_digest"],
            "expected_source_revision": app[2]["source_revision"],
        },
    )
    assert response.status_code == 200, response.text
    app[2] = response.json()


@pytest.fixture
def search_delivery(client, delivery_app, monkeypatch):
    app = list(delivery_app)
    define(client, app, "text")
    monkeypatch.setenv("MIY_INDEPENDENT_APP_SEARCH_ENABLED", "1")
    get_settings.cache_clear()
    state = {
        "profile": "a" * 64,
        "dimensions": 2,
        "dimension_calls": 0,
        "fail_health": False,
        "resources": {},
        "data_generations": [],
    }

    class Backend:
        def __init__(self):
            self.profile_hash = state["profile"]

        def _binding(self, selected):
            assert selected.embedding_config_sha256 == self.profile_hash
            return marker(selected)

        def prepare(self, selected):
            identity = (selected.workspace_id, selected.generation)
            assert identity not in state["resources"]
            state["resources"][identity] = marker(selected)
            selected.opensearch_uuid = "synthetic-owned-index-" + str(selected.generation)
            if hook := state.get("prepare_hook"):
                hook()

        def close(self):
            pass

    class Data:
        def prepare(self, **_):
            pass

        def prepare_search(self, **arguments):
            state["data_generations"].append(arguments["generation"])

    def dimensions(_):
        state["dimension_calls"] += 1
        if hook := state.get("dimension_hook"):
            hook()
        return state["dimensions"]

    class Runtime(FakeRuntime):
        def __init__(self, **arguments):
            super().__init__()
            self.prepare_search = arguments["prepare_search"]
            self.fail_health = state["fail_health"]

        def prepare(self, spec):
            self.prepare_hook = lambda: self.prepare_search(spec)
            super().prepare(spec)

    monkeypatch.setattr(search_consumer, "CoreSearchBackends", lambda _: Backend())
    monkeypatch.setattr(search_consumer, "resolve_embedding_dimensions", dimensions)
    monkeypatch.setattr(search_consumer, "configured_store", lambda _: Data())
    monkeypatch.setattr(data_store, "configured_store", lambda _: Data())
    monkeypatch.setattr(local_runtime, "DockerRuntime", Runtime)
    monkeypatch.chdir(WORKSPACE_ROOT)
    spec = importlib.util.spec_from_file_location(
        "search_generation_delivery_cli", WORKSPACE_ROOT / "scripts/independent-app-delivery.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    yield app, state, cli
    get_settings.cache_clear()


def bindings(installation_id):
    with get_session_factory()() as db:
        return [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in db.scalars(
                select(AppSearchBindingRecord)
                .where(AppSearchBindingRecord.installation_id == installation_id)
                .order_by(AppSearchBindingRecord.generation)
            )
        ]


def execute_cli(cli, app, request, tmp_path):
    return cli.run(
        Namespace(
            command="execute",
            app_id=app[2]["definition"]["app_id"],
            installation_id=app[3]["id"],
            request_id=request["request_id"],
            state_root=tmp_path / "state",
            ingress_image="sha256:" + "b" * 64,
            platform_origin="https://platform.test",
            platform_api_origin=None,
        )
    )


@pytest.mark.parametrize("change", ["embedding"])
def test_failed_health_keeps_old_resources_and_allows_changed_search_deploy(
    client, search_delivery, tmp_path, change
):
    app, state, cli = search_delivery
    first_release = build_release(app[2])
    first, _ = enqueue(client, app, first_release)
    state["fail_health"] = True
    failed = execute_cli(cli, app, first, tmp_path)
    assert failed["state"] == "failed" and failed["failure_code"] == "health_check_failed"
    before = current_installation(app[3]["id"])
    assert before["generation"] == app[3]["generation"] and before["release_id"] is None
    saved = bindings(app[3]["id"])
    assert len(saved) == 1 and saved[0]["state"] == "ready"
    resources = dict(state["resources"])
    if change == "declaration":
        define(client, app, "title")
    else:
        state["profile"], state["dimensions"] = "b" * 64, 4
    next_release = build_release(app[2], "b")
    second, _ = enqueue(client, app, next_release, installation=before)
    state["fail_health"] = False
    deployed = execute_cli(cli, app, second, tmp_path)
    assert deployed["state"] == "succeeded", deployed.get("failure_code")
    after = bindings(app[3]["id"])
    assert after[0] == saved[0] and [row["generation"] for row in after] == [1, 2]
    assert after[1]["candidate_release_id"] == next_release and after[1]["state"] == "ready"
    assert all(state["resources"][identity] == value for identity, value in resources.items())
    assert len(state["resources"]) == 2 and state["data_generations"] == [1, 2]
    assert current_installation(app[3]["id"])["release_id"] == next_release


def test_native_concurrent_search_allocation_holds_pending_then_uses_next_generation(
    client, search_delivery
):
    app, state, _ = search_delivery
    first_release = build_release(app[2])
    define(client, app, "title")
    second_release = build_release(app[2], "b")
    factory = get_session_factory()
    resolving, release_dimensions = Event(), Event()
    preparing, release_backend = Event(), Event()
    second_started = Event()
    second_pid = []

    def wait_dimensions():
        resolving.set()
        assert release_dimensions.wait(5)

    def wait_backend():
        preparing.set()
        assert release_backend.wait(5)

    state["dimension_hook"], state["prepare_hook"] = wait_dimensions, wait_backend

    @contextmanager
    def second_factory():
        with factory() as db:
            second_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            second_started.set()
            yield db

    def prepare(release_id, sessions=factory):
        return search_consumer.prepare_binding(
            sessions,
            installation_id=app[3]["id"],
            workspace_id=app[3]["id"],
            release_id=release_id,
            settings=get_settings(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(prepare, first_release)
        try:
            assert resolving.wait(5)
            second = pool.submit(prepare, second_release, second_factory)
            assert second_started.wait(5)
            with factory() as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    if observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": second_pid[0]}
                    ):
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Concurrent search allocator did not reach the native row lock")
            release_dimensions.set()
            assert preparing.wait(5)
            with pytest.raises(SearchFailure, match="search_preparation_held") as held:
                second.result(timeout=5)
            assert held.value.uncertain is False
        finally:
            release_dimensions.set()
            release_backend.set()
        assert first.result(timeout=10) == "ready"
    saved = bindings(app[3]["id"])
    assert len(saved) == 1 and saved[0]["generation"] == 1
    state.pop("dimension_hook")
    state.pop("prepare_hook")
    assert prepare(second_release) == "ready"
    after = bindings(app[3]["id"])
    assert after[0] == saved[0] and [row["generation"] for row in after] == [1, 2]
    assert len(state["resources"]) == 2 and state["dimension_calls"] == 2


def test_unknown_search_preparation_does_not_allocate_or_replay(client, search_delivery):
    app, state, _ = search_delivery
    release_id = build_release(app[2])
    factory = get_session_factory()

    def prepare(candidate):
        return search_consumer.prepare_binding(
            factory,
            installation_id=app[3]["id"],
            workspace_id=app[3]["id"],
            release_id=candidate,
            settings=get_settings(),
        )

    assert prepare(release_id) == "ready"
    with factory() as db:
        db.get(AppSearchBindingRecord, (app[3]["id"], 1)).state = "unknown"
        db.commit()
    saved, resources, dimensions = (
        bindings(app[3]["id"]),
        dict(state["resources"]),
        state["dimension_calls"],
    )
    define(client, app, "title")
    candidate = build_release(app[2], "b")
    with pytest.raises(SearchFailure, match="search_preparation_held") as held:
        prepare(candidate)
    assert held.value.uncertain is False
    assert bindings(app[3]["id"]) == saved
    assert state["resources"] == resources and state["dimension_calls"] == dimensions
    with factory() as db:
        assert db.get(AppInstallationRecord, app[3]["id"]).generation == app[3]["generation"]
