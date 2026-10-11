from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import sys
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import psycopg
import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient, models as vector_models
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
from miy_api.domains.independent_apps.search_api import SearchQuery
from miy_api.domains.independent_apps import (
    search_api,
    search_backends,
    search_consumer,
    search_service,
)
from miy_api.domains.independent_apps.data_api import get_store, identity
from miy_api.core.db import get_db_session
from miy_api.domains.independent_apps.search_backends import (
    CoreSearchBackends,
    SearchCandidate,
    SearchFailure,
    marker,
    names,
)
from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
from miy_api.domains.independent_apps.search_store import Projection, SearchSourceStore
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


def test_absent_search_preserves_exact_legacy_manifest_and_data_checksum():
    old = manifest()
    del old["search"]
    old["requested_permissions"].remove("search:read")
    definition = AppDefinition.model_validate(old)
    serialized = definition.model_dump(mode="json")
    assert "search" not in serialized
    assert (
        AppDefinition.model_validate(old | {"search": None}).model_dump(mode="json") == serialized
    )
    assert CHECKSUM == "sha256:1fa13280e39bd527d2b57293824d39c3730849785dffea5a9dab46ea0444bac7"
    declared = AppDefinition.model_validate(manifest())
    assert len(declared.search.content_hash()) == 64
    assert (
        declared.search.content_hash()
        != AppDefinition.model_validate(
            manifest()
            | {
                "search": {
                    "collections": {"notes": {"text_fields": ["other"], "modes": ["keyword"]}}
                }
            }
        ).search.content_hash()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"runtime_profile": "web-api-v1"},
        {"search": None},
        {"requested_permissions": ["search:read"]},
        {
            "search": {
                "collections": {"notes": {"text_fields": ["text", "text"], "modes": ["keyword"]}}
            }
        },
        {
            "search": {
                "collections": {"notes": {"text_fields": ["text"], "modes": ["keyword", "keyword"]}}
            }
        },
        {"search": {"collections": {"../other": {"text_fields": ["text"], "modes": ["keyword"]}}}},
        {
            "search": {
                "collections": {
                    "notes": {"text_fields": ["text"], "modes": ["semantic"], "provider": "other"}
                }
            }
        },
    ],
)
def test_search_manifest_rejects_scope_and_provider_expansion(change):
    with pytest.raises(ValidationError):
        AppDefinition.model_validate(manifest() | change)


@pytest.mark.parametrize(
    "body",
    [
        {"query": " "},
        {"query": "x", "limit": True},
        {"query": "x", "limit": 21},
        {"query": "x", "mode": "dsl"},
        {"query": "x", "owner_id": "other"},
        {"query": "x" * 2001},
        {"query": "\ud800"},
    ],
)
def test_search_query_is_bounded_and_never_a_dsl(body):
    with pytest.raises(ValidationError):
        SearchQuery.model_validate(body)


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


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "other"),
        ("app_collection", "other"),
        ("owner_digest", "other"),
        ("sequence", True),
        ("record_id", "not-uuid"),
    ],
)
def test_engine_hits_never_expand_scope_or_return_invalid_identity(native_backends, field, value):
    backend, chosen, _, payload, _, _ = native_backends
    payload[field] = value
    with pytest.raises(SearchFailure, match="response_invalid"):
        backend.query(
            chosen, owner_id="user-a", collection="notes", mode="keyword", query="text", limit=3
        )


def test_profile_dimensions_resolve_only_native_core_gateway_and_validate_output(native_backends):
    backend, chosen, _, _, embedding, settings = native_backends
    assert search_backends.resolve_embedding_dimensions(settings) == 2
    embedding.embed_query = lambda *_, **__: [float("nan")]
    with pytest.raises(SearchFailure, match="embedding_invalid"):
        search_backends.resolve_embedding_dimensions(settings)
    with pytest.raises(SearchFailure, match="profile_invalid"):
        CoreSearchBackends(
            SimpleNamespace(independent_app_search_enabled=True, rag_embedding_provider="fake")
        )
    chosen.embedding_config_sha256 = "b" * 64
    with pytest.raises(SearchFailure, match="profile_changed"):
        backend._binding(chosen)


def test_bounded_native_transport_rejects_redirect_compression_and_oversize(monkeypatch):
    for response in (
        httpx.Response(302, headers={"Location": "http://other.test"}),
        httpx.Response(200, headers={"Content-Encoding": "gzip"}),
        httpx.Response(200, stream=httpx.ByteStream(b"x" * (1024 * 1024 + 1))),
    ):
        transport = search_backends._Transport()
        transport.transport.close()
        transport.transport = httpx.MockTransport(lambda _: response)
        with httpx.Client(transport=transport) as client:
            with pytest.raises(SearchFailure, match="response_invalid"):
                client.get("http://synthetic.test/")


def test_starter_search_adapter_pins_installation_audience_and_bounds_inputs(
    notes_app, monkeypatch
):
    api, installation = notes_app
    # Match a native module import; the reused fixture's direct loader deliberately
    # omits sys.modules and its older business handlers have only builtin annotations.
    monkeypatch.setitem(sys.modules, api.__name__, api)
    api.SearchQuery.model_rebuild()
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [], "indexing_pending": False})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with TestClient(api.app) as client:
        assert client.post("/api/search/notes", json={"query": "text"}).status_code == 401
        headers = {"Authorization": "Bearer synthetic-app-session"}
        assert (
            client.post(
                "/api/search/notes?owner_id=other", headers=headers, json={"query": "text"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/search/notes", headers=headers, json={"query": "text", "model": "other"}
            ).status_code
            == 422
        )
        assert (
            client.post("/api/search/notes", headers=headers, content=b"x" * 20001).status_code
            == 413
        )
        assert seen == []
        assert (
            client.post(
                "/api/search/notes",
                headers=headers,
                json={"query": "장비", "mode": "keyword", "limit": 3},
            ).status_code
            == 200
        )
    assert len(seen) == 1 and seen[0].url.host == "platform.test"
    assert seen[0].url.path == "/api/v1/independent-apps/_search/notes"
    assert dict(seen[0].url.params) == {
        "installation_id": installation,
        "audience": "https://notes.test",
    }
    assert seen[0].headers["authorization"] == headers["Authorization"]


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


def test_current_release_selects_old_search_binding_even_when_candidate_changes(binding_database):
    factory, installation_id, release_id = binding_database
    owner = actor(installation_id).model_copy(update={"permissions": ["data:read", "search:read"]})
    with factory() as db:
        original = db.get(AppSearchBindingRecord, (installation_id, 1))
        candidate = binding(
            installation_id, generation=2, workspace=original.workspace_id, spec="f" * 64
        )
        candidate.candidate_release_id = release_id
        db.add(candidate)
        db.commit()
        _, selected = search_service.search_context(db, owner, "notes", "keyword")
        assert selected.generation == 1
        for foreign in ("other", "../other"):
            with pytest.raises(HTTPException) as error:
                search_service.search_context(db, owner, foreign, "keyword")
            assert error.value.status_code == 403
        for permissions in ([], ["data:read"], ["search:read"]):
            with pytest.raises(HTTPException) as error:
                search_service.search_context(
                    db, owner.model_copy(update={"permissions": permissions}), "notes", "keyword"
                )
            assert error.value.status_code == 403


def test_reusable_search_does_not_probe_embedding_or_reprovision_engines(
    binding_database, monkeypatch
):
    factory, installation_id, release_id = binding_database

    class ReadyBackend:
        profile_hash = "a" * 64

        def _binding(self, selected):
            return marker(selected)

        def close(self):
            pass

    monkeypatch.setattr(search_consumer, "CoreSearchBackends", lambda _: ReadyBackend())
    monkeypatch.setattr(
        search_consumer,
        "resolve_embedding_dimensions",
        lambda _: pytest.fail("No repeated embedding probe"),
    )
    monkeypatch.setattr(
        search_consumer,
        "verified_artifact",
        lambda db, app, target, **_: db.get(AppReleaseRecord, target),
    )
    with factory() as db:
        workspace = db.get(AppSearchBindingRecord, (installation_id, 1)).workspace_id
    assert (
        search_consumer.prepare_binding(
            factory,
            installation_id=installation_id,
            workspace_id=workspace,
            release_id=release_id,
            settings=object(),
        )
        == "ready"
    )
    with factory() as db:
        assert db.get(AppSearchBindingRecord, (installation_id, 2)) is None


def test_consumer_preserves_known_keyword_phase_and_holds_unknown_semantic_without_replay(
    binding_database, monkeypatch
):
    factory, installation_id, _ = binding_database
    projection = Projection(
        "notes", "user-a", str(uuid4()), 1, False, {"text": "source"}, False, False
    )
    phases, calls = [], []

    class Source:
        def __init__(self, _):
            pass

        @contextmanager
        def next_projection(self, installation, selected):
            yield object(), projection

        def acknowledge(self, conn, selected, phase, generation):
            phases.append((phase, generation))

    class Backend:
        def __init__(self, _):
            pass

        def write_keyword(self, *args):
            calls.append("keyword")

        def write_semantic(self, *args):
            calls.append("semantic")
            raise SearchFailure("search_effect_unknown")

        def close(self):
            pass

    monkeypatch.setattr(search_consumer, "configured_store", lambda _: object())
    monkeypatch.setattr(search_consumer, "SearchSourceStore", Source)
    assert (
        search_consumer.run_once(
            factory, installation_id=installation_id, settings=object(), backend_factory=Backend
        )
        == "held"
    )
    assert calls == ["keyword", "semantic"] and phases == [("keyword", 1), ("held", 1)]
    assert "complete" not in [phase for phase, _ in phases]


def test_native_cleanup_absent_is_safe_but_mixed_absence_is_not_adopted(
    data_store, isolated_data_cluster
):
    owner = actor()
    arguments = dict(
        installation_id=owner.installation_id, app_id=owner.app_id, environment=owner.environment
    )
    saved = []
    result = data_store.remove_temporary(
        **arguments, persist_receipt=lambda value: saved.append(value)
    )
    assert result["phase"] == "absent" and result["roles"] == {} and result["database_oid"] is None
    assert (
        data_store.remove_temporary(**arguments, receipt=result, persist_receipt=lambda _: None)
        == result
    )
    prepare(data_store, owner)
    with pytest.raises(DataStoreError, match="receipt_invalid"):
        data_store.remove_temporary(**arguments, receipt=result, persist_receipt=lambda _: None)
    with psycopg.connect(isolated_data_cluster, autocommit=True) as conn:
        database, _, _ = data_store.names(owner.installation_id)
        from psycopg import sql

        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
    with pytest.raises(DataStoreError, match="identity_mismatch"):
        data_store.remove_temporary(**arguments, persist_receipt=lambda _: None)


@pytest.mark.parametrize("invalid", ["envelope", "index_uuid"])
def test_backend_rejects_invalid_native_envelope_and_index_uuid_before_mutation(
    native_backends, invalid
):
    backend, chosen, _, _, _, _ = native_backends
    backend.keyword.close()
    body = (
        []
        if invalid == "envelope"
        else {
            chosen.opensearch_index: {
                "mappings": {"_meta": marker(chosen)},
                "settings": {"index": {"uuid": False}},
            }
        }
    )
    backend.keyword = httpx.Client(
        base_url="http://keyword.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    with pytest.raises(SearchFailure):
        backend.prepare(chosen)


def test_search_http_adapter_keeps_actors_and_binding_server_owned(binding_database, monkeypatch):
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from miy_api.app import localized_http_exception_handler

    factory, installation_id, _ = binding_database
    owner = actor(installation_id).model_copy(update={"permissions": ["data:read", "search:read"]})
    seen = []
    row_id = str(uuid4())

    class Backend:
        def query(self, selected, **kwargs):
            seen.append((selected.installation_id, selected.generation, kwargs))
            return [SearchCandidate(row_id, 1, 0.5)]

        def close(self):
            pass

    class Source:
        def __init__(self, _):
            pass

        def current_records(self, current, collection, candidates):
            assert (current.user_id, current.installation_id, collection) == (
                owner.user_id,
                installation_id,
                "notes",
            )
            return [
                {
                    "record": {
                        "id": row_id,
                        "payload": {"text": "current source"},
                        "version": 1,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    },
                    "score": candidates[0].score,
                }
            ]

    monkeypatch.setattr(search_api, "CoreSearchBackends", lambda _: Backend())
    monkeypatch.setattr(search_api, "SearchSourceStore", Source)
    monkeypatch.setattr(search_api, "pending", lambda *_: False)
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.include_router(search_api.router, prefix="/api/v1/independent-apps")

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_store] = lambda: object()
    app.dependency_overrides[identity] = lambda: owner
    with TestClient(app) as client:
        path = "/api/v1/independent-apps/_search/notes"
        response = client.post(path, json={"query": "장비", "limit": 3})
        assert response.status_code == 200
        assert response.json()["items"][0]["record"]["id"] == row_id
        assert seen == [
            (
                installation_id,
                1,
                {
                    "owner_id": owner.user_id,
                    "collection": "notes",
                    "mode": "keyword",
                    "query": "장비",
                    "limit": 3,
                },
            )
        ]
        assert client.post(path, json={"query": "text", "owner_id": "other"}).status_code == 422
        assert client.post(path, content=b"x" * (20 * 1024 + 1)).status_code == 413
        app.dependency_overrides[identity] = lambda: owner.model_copy(
            update={"permissions": ["data:read"]}
        )
        assert client.post(path, json={"query": "text"}).status_code == 403
        assert len(seen) == 1


def test_search_feature_defaults_closed_before_engines_or_embedding(monkeypatch):
    monkeypatch.setattr(
        search_backends,
        "get_rag_provider_registry",
        lambda: pytest.fail("Disabled search must not construct embedding"),
    )

    def prepare(settings):
        return search_consumer.prepare_binding(
            lambda: pytest.fail("Disabled search must not open a source transaction"),
            installation_id=str(uuid4()),
            workspace_id=str(uuid4()),
            release_id=str(uuid4()),
            settings=settings,
        )

    for settings in (SimpleNamespace(), SimpleNamespace(independent_app_search_enabled=False)):
        for operation in (
            CoreSearchBackends,
            search_backends.resolve_embedding_dimensions,
            prepare,
        ):
            with pytest.raises(SearchFailure, match="configuration_required") as error:
                operation(settings)
            assert error.value.uncertain is False


@pytest.mark.parametrize(
    "failure", ["partial_vector_delete", "lost_keyword_ack", "foreign_replacement"]
)
def test_cleanup_resumes_only_original_verified_resources(binding_database, monkeypatch, failure):
    factory, installation_id, _ = binding_database
    with factory() as db:
        chosen = db.get(AppSearchBindingRecord, (installation_id, 1))
        chosen.state = "stopped"
        db.commit()
        db.refresh(chosen)
        db.expunge(chosen)

    keyword = {"present": True, "uuid": chosen.opensearch_uuid, "delete_calls": 0}

    def respond(request):
        assert request.url.path == "/" + chosen.opensearch_index
        if request.method == "GET":
            if not keyword["present"]:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    chosen.opensearch_index: {
                        "mappings": {"_meta": marker(chosen)},
                        "settings": {"index": {"uuid": keyword["uuid"]}},
                    }
                },
            )
        assert request.method == "DELETE"
        with factory() as db:
            saved = db.get(AppSearchBindingRecord, (installation_id, 1))
            assert saved.state == "cleanup_pending" and saved.cleanup_phase == "verified"
        keyword["delete_calls"] += 1
        keyword["present"] = False
        if failure == "lost_keyword_ack" and keyword["delete_calls"] == 1:
            raise httpx.ReadTimeout("Synthetic lost acknowledgement", request=request)
        return httpx.Response(200, json={"acknowledged": True})

    backend = CoreSearchBackends.__new__(CoreSearchBackends)
    backend.profile_hash = chosen.embedding_config_sha256
    backend.keyword = httpx.Client(
        base_url="http://keyword.test", transport=httpx.MockTransport(respond)
    )
    # The native SDK's isolated local engine checks actual ownership-point and
    # collection lifecycle calls; no shared search service/model is contacted.
    backend.vector = QdrantClient(location=":memory:")
    backend.vector.create_collection(
        chosen.qdrant_collection,
        vectors_config={
            "dense": vector_models.VectorParams(size=2, distance=vector_models.Distance.COSINE)
        },
    )
    backend.vector.upsert(
        chosen.qdrant_collection,
        [
            vector_models.PointStruct(
                id=search_backends._OWNER_POINT,
                vector={"dense": [0.0, 0.0]},
                payload=marker(chosen),
            )
        ],
    )
    vector_delete = backend.vector.delete_collection
    vector_calls = []

    def remove_vector(name):
        with factory() as db:
            saved = db.get(AppSearchBindingRecord, (installation_id, 1))
            assert saved.state == "cleanup_pending" and saved.cleanup_phase == "keyword_removed"
        vector_calls.append(name)
        if failure != "lost_keyword_ack" and len(vector_calls) == 1:
            raise httpx.ReadTimeout("Synthetic vector delete failure")
        return vector_delete(name)

    monkeypatch.setattr(backend.vector, "delete_collection", remove_vector)
    monkeypatch.setattr(backend, "close", lambda: None)
    monkeypatch.setattr(search_consumer, "CoreSearchBackends", lambda _: backend)
    monkeypatch.setattr(
        search_consumer,
        "configured_store",
        lambda _: SimpleNamespace(stop_search_generation=lambda **_: None),
    )
    try:
        with pytest.raises(SearchFailure):
            search_consumer.cleanup_binding(
                factory, installation_id=installation_id, generation=1, settings=object()
            )
        with factory() as db:
            saved = db.get(AppSearchBindingRecord, (installation_id, 1))
            assert saved.state == "cleanup_pending"
            assert saved.cleanup_phase == (
                "verified" if failure == "lost_keyword_ack" else "keyword_removed"
            )
        assert keyword["present"] is False
        assert backend.vector.collection_exists(chosen.qdrant_collection)
        if failure == "foreign_replacement":
            keyword.update(present=True, uuid="foreign-index-id")
            with pytest.raises(SearchFailure, match="identity_mismatch"):
                search_consumer.cleanup_binding(
                    factory, installation_id=installation_id, generation=1, settings=object()
                )
            assert keyword["present"] is True and keyword["delete_calls"] == 1
            assert len(vector_calls) == 1
            assert backend.vector.collection_exists(chosen.qdrant_collection)
        else:
            assert (
                search_consumer.cleanup_binding(
                    factory, installation_id=installation_id, generation=1, settings=object()
                )
                == "removed"
            )
            with factory() as db:
                saved = db.get(AppSearchBindingRecord, (installation_id, 1))
                assert saved.state == "removed" and saved.cleanup_phase == "vector_removed"
            assert keyword["delete_calls"] == 1
            assert not backend.vector.collection_exists(chosen.qdrant_collection)
    finally:
        backend.keyword.close()
        backend.vector.close()


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
