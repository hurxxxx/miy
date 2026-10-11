from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.data_store import CHECKSUM, SEARCH_CHECKSUM, DataStoreError
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppReleaseRecord,
)
from miy_api.domains.independent_apps import (
    search_backends,
    search_consumer,
    search_service,
)
from miy_api.domains.independent_apps.search_backends import (
    CoreSearchBackends,
    SearchCandidate,
    SearchFailure,
    marker,
    names,
)
from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
from miy_api.domains.independent_apps.search_store import SearchSourceStore
from test_independent_app_data import actor, prepare
from test_independent_app_data import data_store as _data_store
from test_independent_app_data import isolated_data_cluster as _isolated_data_cluster
from test_independent_app_data_template import notes_app as _notes_app

data_store = _data_store
isolated_data_cluster = _isolated_data_cluster
notes_app = _notes_app


def manifest():
    return {
        "schema_version": 1,
        "app_id": "fixture-app",
        "display": {"name": "Synthetic"},
        "source": {"repository": "https://example.test/app.git"},
        "runtime_profile": "web-api-postgres-v1",
        "requested_permissions": ["identity:read", "data:read", "data:write", "search:read"],
        "search": {
            "collections": {"notes": {"text_fields": ["text"], "modes": ["keyword", "semantic"]}}
        },
    }


def binding(installation=None, *, generation=1, workspace=None, spec=None):
    installation = installation or str(uuid4())
    workspace = workspace or str(uuid4())
    keyword, vector = names(workspace, generation)
    return AppSearchBindingRecord(
        installation_id=installation,
        generation=generation,
        workspace_id=workspace,
        search_spec_sha256=spec or AppDefinition.model_validate(manifest()).search.content_hash(),
        candidate_release_id=str(uuid4()),
        definition_digest="sha256:" + "a" * 64,
        opensearch_index=keyword,
        opensearch_uuid="synthetic-owned-index-id",
        qdrant_collection=vector,
        embedding_profile=search_backends.PROFILE,
        embedding_config_sha256="a" * 64,
        embedding_dimensions=2,
        state="ready",
    )


def prepared_search(store, owner, selected):
    store.prepare_search(
        installation_id=owner.installation_id,
        app_id=owner.app_id,
        environment=owner.environment,
        artifact_digest="sha256:" + "a" * 64,
        request_id=str(uuid4()),
        generation=selected.generation,
        workspace_id=selected.workspace_id,
        search_spec_sha256=selected.search_spec_sha256,
    )
    return SimpleNamespace(
        id=owner.installation_id, app_id=owner.app_id, environment=owner.environment
    )


def test_native_source_projection_is_atomic_rls_scoped_and_monotonic_after_delete(data_store):
    owner = actor()
    prepare(data_store, owner)
    first = data_store.write(owner, "notes", {"text": "original"}, record_key="key")
    chosen = binding(owner.installation_id)
    installation = prepared_search(data_store, owner, chosen)
    source = SearchSourceStore(data_store)
    assert search_service.pending(source, owner, "notes", chosen) is True
    with source.next_projection(installation, chosen) as selected:
        conn, projection = selected
        assert (projection.sequence, projection.payload, projection.deleted) == (
            1,
            {"text": "original"},
            False,
        )
        source.acknowledge(conn, projection, "keyword", chosen.generation)
        source.acknowledge(conn, projection, "complete", chosen.generation)
    assert search_service.pending(source, owner, "notes", chosen) is False
    with pytest.raises(DataStoreError, match="conflict"):
        data_store.write(
            owner, "notes", {"text": "wrong"}, record_id=str(first["id"]), expected_version=2
        )
    data_store.delete(owner, "notes", str(first["id"]), 1)
    recreated = data_store.write(owner, "notes", {"text": "recreated"}, record_key="key")
    assert recreated["version"] == 1 and recreated["id"] == first["id"]
    with source.next_projection(installation, chosen) as selected:
        conn, projection = selected
        assert projection.sequence == 3 and projection.deleted is False
        assert projection.payload == {"text": "recreated"}
        source.acknowledge(conn, projection, "complete", chosen.generation)
    # Stale pre-deletion hits and another source owner never disclose data.
    assert source.current_records(owner, "notes", [SearchCandidate(str(first["id"]), 1, 0.5)]) == []
    assert (
        source.current_records(
            owner.model_copy(update={"user_id": "user-b"}),
            "notes",
            [SearchCandidate(str(first["id"]), 3, 0.5)],
        )
        == []
    )
    assert source.current_records(owner, "notes", [SearchCandidate(str(first["id"]), 3, 0.5)])[0][
        "record"
    ]["payload"] == {"text": "recreated"}
    database, migrator, gateway = data_store.names(owner.installation_id)
    with data_store._connect(database=database, role=gateway) as conn:
        conn.execute("SELECT set_config('miy.actor_id','user-b',true)")
        assert conn.execute("SELECT count(*) FROM miy_data.search_outbox").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM miy_data.projection_heads").fetchone()[0] == 0
    with data_store._connect(database=database, role=migrator) as conn:
        assert conn.execute("SELECT version,checksum FROM miy_data.installation").fetchone() == (
            1,
            CHECKSUM,
        )
        assert conn.execute("SELECT version,checksum FROM miy_data.search_schema").fetchone() == (
            1,
            SEARCH_CHECKSUM,
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM miy_data.search_outbox WHERE NOT completed"
            ).fetchone()[0]
            == 0
        )


def test_native_new_generation_backfills_without_overwriting_active_generation(data_store):
    owner = actor()
    prepare(data_store, owner)
    first = binding(owner.installation_id)
    installation = prepared_search(data_store, owner, first)
    row = data_store.write(owner, "notes", {"text": "first"})
    source = SearchSourceStore(data_store)
    with source.next_projection(installation, first) as selected:
        conn, projection = selected
        source.acknowledge(conn, projection, "keyword", first.generation)
        source.acknowledge(conn, projection, "held", first.generation)
    second = binding(
        owner.installation_id, generation=2, workspace=first.workspace_id, spec="b" * 64
    )
    prepared_search(data_store, owner, second)
    updated = data_store.write(
        owner, "notes", {"text": "latest"}, record_id=str(row["id"]), expected_version=1
    )
    assert updated["version"] == 2
    with source.next_projection(installation, first) as selected:
        assert selected is None
    assert source.has_held(installation, first)
    with source.next_projection(installation, second) as selected:
        conn, projection = selected
        assert projection.payload == {"text": "latest"} and projection.sequence == 2
        source.acknowledge(conn, projection, "complete", second.generation)
    assert source.has_held(installation, second) is False
    data_store.stop_search_generation(
        installation_id=installation.id,
        app_id=installation.app_id,
        environment=installation.environment,
        generation=1,
    )
    with pytest.raises(DataStoreError, match="schema_identity"):
        with source.next_projection(installation, first):
            pass
    assert data_store.read(owner, "notes", str(row["id"]))["payload"] == {"text": "latest"}


def test_native_record_write_rolls_back_when_projection_publication_fails(data_store, monkeypatch):
    owner = actor()
    prepare(data_store, owner)
    chosen = binding(owner.installation_id)
    installation = prepared_search(data_store, owner, chosen)
    original = data_store._record_projection

    def abort(*args, **kwargs):
        original(*args, **kwargs)
        raise DataStoreError("synthetic_rollback")

    monkeypatch.setattr(data_store, "_record_projection", abort)
    with pytest.raises(DataStoreError, match="synthetic_rollback"):
        data_store.write(owner, "notes", {"text": "must rollback"})
    assert data_store.list_records(owner, "notes") == []
    with SearchSourceStore(data_store).next_projection(installation, chosen) as selected:
        assert selected is None


def test_native_temporary_cleanup_requires_durable_receipt_and_no_active_connections(data_store):
    owner = actor()
    prepare(data_store, owner)
    chosen = binding(owner.installation_id)
    prepared_search(data_store, owner, chosen)
    arguments = dict(
        installation_id=owner.installation_id, app_id=owner.app_id, environment=owner.environment
    )
    with pytest.raises(DataStoreError, match="receipt_required"):
        data_store.remove_temporary(**arguments)
    receipts = []
    database, _, gateway = data_store.names(owner.installation_id)
    with data_store._connect(database=database, role=gateway):
        with pytest.raises(DataStoreError, match="active_connections"):
            data_store.remove_temporary(
                **arguments, persist_receipt=lambda receipt: receipts.append(receipt)
            )
    assert receipts[-1]["phase"] == "verified"
    result = data_store.remove_temporary(
        **arguments, receipt=receipts[-1], persist_receipt=lambda receipt: receipts.append(receipt)
    )
    assert result["phase"] == "removed"
    assert (
        data_store.remove_temporary(**arguments, receipt=result, persist_receipt=lambda _: None)[
            "phase"
        ]
        == "removed"
    )
    with pytest.raises(DataStoreError, match="cleanup_denied"):
        data_store.remove_temporary(
            **(arguments | {"environment": "production"}), persist_receipt=lambda _: None
        )


@pytest.fixture
def native_backends(monkeypatch):
    chosen = binding()
    requests = []
    payload = {
        "record_id": str(uuid4()),
        "sequence": 2,
        "kind": "record",
        "owner_id": "user-a",
        "app_collection": "notes",
        "owner_digest": marker(chosen)["owner_digest"],
    }

    def respond(request):
        requests.append(request)
        if request.url.host == "keyword.test":
            if request.url.path.endswith("/_search"):
                return httpx.Response(
                    200, json={"hits": {"hits": [{"_source": payload, "_score": 1.0}]}}
                )
            return httpx.Response(
                200,
                json={
                    chosen.opensearch_index: {
                        "mappings": {"_meta": marker(chosen)},
                        "settings": {"index": {"uuid": chosen.opensearch_uuid}},
                    }
                },
            )
        if request.url.path.endswith("/points/query"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {"id": str(uuid4()), "version": 1, "score": 0.8, "payload": payload}
                        ]
                    },
                    "time": 0.001,
                    "status": "ok",
                },
            )
        raise AssertionError("Unexpected native SDK route")

    settings = SimpleNamespace(
        independent_app_search_enabled=True,
        rag_embedding_provider="inference_gateway",
        opensearch_url="http://keyword.test",
        rag_qdrant_url="http://vector.test",
        rag_qdrant_api_key="",
    )
    monkeypatch.setattr(search_backends, "_Transport", lambda: httpx.MockTransport(respond))
    monkeypatch.setattr(
        search_backends,
        "retrieval_embedding_generation_identity",
        lambda _: SimpleNamespace(config_sha256="a" * 64),
    )
    embedding = SimpleNamespace(
        embed_query=lambda text, **_: [0.1, 0.2], embed_texts=lambda text, **_: [[0.1, 0.2]]
    )
    monkeypatch.setattr(
        search_backends,
        "get_rag_provider_registry",
        lambda: SimpleNamespace(build_embedding=lambda *_: embedding),
    )
    backend = CoreSearchBackends(settings)
    # Resource identity is tested separately; this native SDK assertion observes
    # actual query serialization and fixed field filters, without a Qdrant service.
    monkeypatch.setattr(backend, "_vector_owned", lambda selected: backend._binding(selected))
    yield backend, chosen, requests, payload, embedding, settings
    backend.close()


def test_native_keyword_and_qdrant_sdk_queries_fix_owner_resource_and_fields(native_backends):
    backend, chosen, requests, payload, _, _ = native_backends
    for mode in ("keyword", "semantic"):
        hits = backend.query(
            chosen, owner_id="user-a", collection="notes", mode=mode, query="장비", limit=3
        )
        assert hits == [SearchCandidate(payload["record_id"], 2, 1.0 if mode == "keyword" else 0.8)]
    keyword = json.loads(
        next(request for request in requests if request.url.path.endswith("/_search")).content
    )
    assert keyword["size"] == 3
    assert {
        item["term"]["owner_id"]
        for item in keyword["query"]["bool"]["filter"]
        if "owner_id" in item["term"]
    } == {"user-a"}
    vector = json.loads(
        next(request for request in requests if request.url.path.endswith("/points/query")).content
    )
    assert vector["using"] == "dense" and vector["with_vector"] is False
    assert {
        item["match"]["value"] for item in vector["filter"]["must"] if item["key"] == "owner_id"
    } == {"user-a"}
    assert all(
        "notes" in json.loads(request.content).__str__()
        for request in requests
        if request.method == "POST"
    )


@pytest.fixture
def binding_database(monkeypatch):
    from miy_api.domains.independent_apps.delivery_models import AppBuildVerification

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [
        AppDefinitionRecord.__table__,
        AppReleaseRecord.__table__,
        AppInstallationRecord.__table__,
        AppBuildVerification.__table__,
        AppSearchBindingRecord.__table__,
    ]
    AppDefinitionRecord.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(engine)
    installation_id, release_id = str(uuid4()), str(uuid4())
    definition = AppDefinition.model_validate(manifest())
    with factory() as db:
        db.add(
            AppDefinitionRecord(
                app_id="fixture-app",
                owner_user_id="user-a",
                manifest=definition.model_dump(mode="json"),
                definition_digest="sha256:" + "a" * 64,
                source_revision="a" * 40,
            )
        )
        db.add(
            AppReleaseRecord(
                id=release_id,
                app_id="fixture-app",
                definition_snapshot=definition.model_dump(mode="json"),
                definition_digest="sha256:" + "a" * 64,
                source_revision="a" * 40,
                artifact="sha256:" + "b" * 64,
            )
        )
        db.add(
            AppInstallationRecord(
                id=installation_id,
                app_id="fixture-app",
                environment="development",
                origin="https://fixture.test",
                enabled=True,
                release_id=release_id,
            )
        )
        selected = binding(installation_id)
        selected.candidate_release_id = release_id
        db.add(selected)
        db.commit()

    def trusted(db, installation, target):
        return db.get(AppReleaseRecord, target) if installation.release_id == target else None

    monkeypatch.setattr(search_service, "trusted_release", trusted)
    monkeypatch.setattr(search_consumer, "trusted_release", trusted)
    yield factory, installation_id, release_id
    engine.dispose()


def test_cleanup_never_adopts_uncertain_provisioning_or_missing_phase(
    binding_database, monkeypatch
):
    factory, installation_id, _ = binding_database
    monkeypatch.setattr(
        search_consumer, "CoreSearchBackends", lambda _: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        search_consumer,
        "configured_store",
        lambda _: pytest.fail("Held resources cannot be changed"),
    )
    for state, phase in (
        ("preparing", None),
        ("unknown", None),
        ("cleanup_pending", None),
        ("cleanup_pending", "unexpected"),
    ):
        with factory() as db:
            saved = db.get(AppSearchBindingRecord, (installation_id, 1))
            saved.state, saved.cleanup_phase = state, phase
            db.commit()
        with pytest.raises(SearchFailure, match="cleanup_held") as error:
            search_consumer.cleanup_binding(
                factory, installation_id=installation_id, generation=1, settings=object()
            )
        assert error.value.uncertain is False
        with factory() as db:
            saved = db.get(AppSearchBindingRecord, (installation_id, 1))
            assert (saved.state, saved.cleanup_phase) == (state, phase)
