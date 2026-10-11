from __future__ import annotations

from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import subprocess
import time
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from disposable_postgres import native_bin_dir, native_cluster, postgres_major

from miy_api.domains.independent_apps.contracts import AppIdentityOut
from miy_api.domains.independent_apps.data_store import CHECKSUM, DataStoreError, PostgresAppData


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Disposable PostgreSQL fixture Docker command failed")
    return result.stdout.strip()


@pytest.fixture(scope="module")
def isolated_data_cluster():
    # No connections or grant changes to the checkout's development/core cluster.
    selected = os.getenv("MIY_TEST_APP_DATA_POSTGRES_IMAGE")
    selected_major = os.getenv("MIY_TEST_APP_DATA_POSTGRES_MAJOR")
    if bool(selected) != bool(selected_major):
        pytest.fail("An explicit disposable PostgreSQL image requires its server major")
    if selected:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", selected) or selected_major not in ("17", "18"):
            pytest.fail("Select an immutable local PostgreSQL image and supported server major")
        major = int(selected_major)
        target = selected
    else:
        major = postgres_major()
        directory = native_bin_dir(major)
        if directory is not None:
            with native_cluster(directory, major) as dsn:
                yield dsn
            return
        if os.getenv("CI") == "true":
            pytest.fail("CI requires same-major disposable PostgreSQL server binaries")
        target = f"postgres:{major}-alpine"
    try:
        image = docker("image", "inspect", target, "--format", "{{.Id}}")
    except (OSError, RuntimeError):
        if selected:
            pytest.fail("The selected immutable disposable PostgreSQL image is not local")
        pytest.skip(
            "Disposable data tests need same-major native server or local Docker image; no pull"
        )
    if selected and image != selected:
        pytest.fail("The disposable PostgreSQL image identity changed")
    name = "miy-app-data-test-" + uuid4().hex
    # Official images moved their VOLUME root in PostgreSQL 18.
    data_path = "/var/lib/postgresql" if major >= 18 else "/var/lib/postgresql/data"
    try:
        docker(
            "create",
            "--name",
            name,
            "--label",
            "miy.test.independent-data=1",
            "--publish",
            "127.0.0.1::5432",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--tmpfs",
            data_path + ":rw,size=256m",
            "--env",
            "POSTGRES_PASSWORD=synthetic-test-only",
            image,
        )
        docker("start", name)
        port = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0][
            "HostPort"
        ]
        dsn = f"postgresql://postgres:synthetic-test-only@127.0.0.1:{port}/postgres"
        for _ in range(100):
            try:
                with psycopg.connect(dsn, connect_timeout=1) as conn:
                    assert (
                        int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000 == major
                    )
                    break
            except psycopg.Error:
                time.sleep(0.1)
        else:
            pytest.fail("Disposable PostgreSQL failed to start")
        yield dsn
    finally:
        docker("rm", "--force", "--volumes", name)


@pytest.fixture(scope="module")
def data_store(isolated_data_cluster):
    store = PostgresAppData(isolated_data_cluster, "synthetic-credential-root-key-" + "x" * 32)
    # Confirm default PUBLIC CONNECT is refused before changing our own fixture.
    with pytest.raises(DataStoreError, match="data_cluster_public_connect"):
        store.prepare(
            installation_id=str(uuid4()),
            app_id="fixture-app",
            environment="development",
            artifact_digest="sha256:" + "a" * 64,
            request_id=str(uuid4()),
        )
    with psycopg.connect(isolated_data_cluster) as conn:
        for (name,) in conn.execute(
            "SELECT datname FROM pg_database WHERE datallowconn"
        ).fetchall():
            conn.execute(
                sql.SQL("REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(name)
                )
            )
    return store


def actor(installation_id=None, *, user="user-a", app="fixture-app", environment="development"):
    return AppIdentityOut(
        user_id=user,
        display_name="Synthetic",
        app_id=app,
        installation_id=installation_id or str(uuid4()),
        environment=environment,
        audience="https://fixture.test",
        permissions=["identity:read", "data:read", "data:write"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def prepare(store, identity, *, artifact="a", request_id=None):
    return store.prepare(
        installation_id=identity.installation_id,
        app_id=identity.app_id,
        environment=identity.environment,
        artifact_digest="sha256:" + artifact * 64,
        request_id=request_id or str(uuid4()),
    )


def test_native_user_app_environment_isolation_and_cas(data_store):
    owner = actor()
    prepare(data_store, owner)
    row = data_store.write(owner, "notes", {"text": "my private record"})
    another = owner.model_copy(update={"user_id": "user-b"})
    assert data_store.list_records(another, "notes") == []
    with pytest.raises(DataStoreError, match="not_found"):
        data_store.read(another, "notes", str(row["id"]))
    with pytest.raises(DataStoreError, match="conflict"):
        data_store.write(
            another, "notes", {"text": "stolen"}, record_id=str(row["id"]), expected_version=1
        )
    updated = data_store.write(
        owner, "notes", {"text": "changed"}, record_id=str(row["id"]), expected_version=1
    )
    assert updated["version"] == 2
    with pytest.raises(DataStoreError, match="conflict"):
        data_store.delete(owner, "notes", str(row["id"]), 1)
    for other in (actor(app="another-app"), actor(environment="production")):
        prepare(data_store, other)
        assert data_store.list_records(other, "notes") == []
        with pytest.raises(DataStoreError, match="not_found"):
            data_store.read(other, "notes", str(row["id"]))
    forged = owner.model_copy(update={"environment": "production"})
    with pytest.raises(DataStoreError, match="identity_mismatch"):
        data_store.list_records(forged, "notes")
    data_store.delete(owner, "notes", str(row["id"]), 2)
    assert data_store.list_records(owner, "notes") == []


def test_keyed_create_is_atomic_and_lookup_recovers_the_original_row(data_store):
    owner = actor()
    prepare(data_store, owner)
    barrier = Barrier(2)

    def create(value):
        barrier.wait(timeout=10)
        try:
            return data_store.write(owner, "items", {"value": value}, record_key="same-key")
        except DataStoreError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ["first", "second"]))
    created = [result for result in results if isinstance(result, dict)]
    assert len(created) == 1
    assert results.count("data_record_conflict") == 1
    assert data_store.read_by_key(owner, "items", "same-key") == created[0]
    assert data_store.list_records(owner, "items") == created
    # Conflicting input never replaces the original payload or version.
    with pytest.raises(DataStoreError, match="data_record_conflict"):
        data_store.write(owner, "items", {"value": "replacement"}, record_key="same-key")
    assert data_store.read_by_key(owner, "items", "same-key")["version"] == 1


def test_record_key_is_exact_and_scoped_to_current_owner_installation_collection(data_store):
    owner = actor()
    prepare(data_store, owner)
    first = data_store.write(owner, "items", {"value": 1}, record_key="key")
    other_user = owner.model_copy(update={"user_id": "user-b"})
    with pytest.raises(DataStoreError, match="data_record_not_found"):
        data_store.read_by_key(other_user, "items", "key")
    with pytest.raises(DataStoreError, match="data_record_not_found"):
        data_store.read(other_user, "items", str(first["id"]))
    others = [
        data_store.write(other_user, "items", {"value": 2}, record_key="key"),
        data_store.write(owner, "other_items", {"value": 3}, record_key="key"),
        data_store.write(owner, "items", {"value": 4}, record_key="Key"),
        data_store.write(owner, "items", {"value": 5}, record_key=" key "),
        data_store.write(owner, "items", {"value": 6}, record_key="한글키"),
    ]
    other_installation = actor()
    prepare(data_store, other_installation)
    others.append(data_store.write(other_installation, "items", {"value": 7}, record_key="key"))
    assert len({row["id"] for row in [first, *others]}) == 7
    assert data_store.read_by_key(owner, "items", "key") == first
    for key in ("", "   ", "key\n", "\ud800", "x" * 257, "한" * 86, 7):
        with pytest.raises(DataStoreError, match="data_payload_invalid"):
            data_store.write(owner, "items", {"value": 8}, record_key=key)
    with pytest.raises(DataStoreError, match="data_payload_invalid"):
        data_store.write(
            owner,
            "items",
            {"value": 9},
            record_id=str(first["id"]),
            expected_version=1,
            record_key="key",
        )
    data_store.delete(owner, "items", str(first["id"]), 1)
    with pytest.raises(DataStoreError, match="data_record_not_found"):
        data_store.read_by_key(owner, "items", "key")
    replacement = data_store.write(owner, "items", {"value": 10}, record_key="key")
    assert replacement["id"] == first["id"] and replacement["version"] == 1


def test_migration_journal_retry_artifact_conflict_and_code_rollback_retains_data(data_store):
    identity = actor()
    request = str(uuid4())
    first = prepare(data_store, identity, request_id=request)
    assert prepare(data_store, identity, request_id=request) == first
    row = data_store.write(identity, "arbitrary_collection", {"value": 42})
    with pytest.raises(DataStoreError, match="request_conflict"):
        prepare(data_store, identity, artifact="b", request_id=request)
    prepare(data_store, identity, artifact="b")
    prepare(data_store, identity, artifact="a")  # Code rollback never downgrades schema/data.
    assert data_store.read(identity, "arbitrary_collection", str(row["id"]))["payload"] == {
        "value": 42
    }
    database, migrator, _ = data_store.names(identity.installation_id)
    with data_store._connect(database=database, role=migrator) as conn:
        assert conn.execute("SELECT count(*) FROM miy_data.migrations").fetchone() == (3,)
        assert conn.execute("SELECT DISTINCT checksum FROM miy_data.migrations").fetchone() == (
            CHECKSUM,
        )
        conn.execute("UPDATE miy_data.installation SET checksum='tampered'")
    with pytest.raises(DataStoreError, match="schema_identity_mismatch"):
        prepare(data_store, identity)


def test_dml_role_has_no_ddl_migration_or_other_database_privilege(
    data_store, isolated_data_cluster, monkeypatch
):
    connect = data_store._connect
    observed_budgets = []

    def observe_connect(**kwargs):
        conn = connect(**kwargs)
        with conn.transaction():
            statement, lock = conn.execute(
                "SELECT current_setting('statement_timeout'),current_setting('lock_timeout')"
            ).fetchone()
        observed_budgets.append((kwargs.get("provisioning", False), statement, lock))
        assert conn.info.get_parameters()["connect_timeout"] == "5"
        return conn

    monkeypatch.setattr(data_store, "_connect", observe_connect)
    first, second = actor(), actor()
    prepare(data_store, first)
    prepare(data_store, second)
    database, _, gateway = data_store.names(first.installation_id)
    other, _, _ = data_store.names(second.installation_id)
    with pytest.raises(DataStoreError, match="data_configuration_invalid"):
        data_store._connect(database=database, role=gateway, autocommit=True, provisioning=True)
    with data_store._connect(database=database, role=gateway) as conn:
        assert conn.execute(
            "SELECT has_database_privilege(current_user,%s,'CONNECT')", (other,)
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_database_privilege(current_user,'postgres','CONNECT')"
        ).fetchone() == (False,)
    for query in (
        "CREATE TABLE public.escape(id int)",
        "SELECT * FROM miy_data.migrations",
        "ALTER TABLE miy_data.records DISABLE ROW LEVEL SECURITY",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with data_store._connect(database=database, role=gateway) as conn:
                conn.execute(query)
    with pytest.raises(psycopg.OperationalError, match="CONNECT privilege"):
        with data_store._connect(database=other, role=gateway):
            pass
    wrong_key = PostgresAppData(isolated_data_cluster, "changed-key-is-not-a-rotation-" + "y" * 32)
    with pytest.raises(DataStoreError, match="provision_unavailable"):
        prepare(wrong_key, first)
    assert data_store.list_records(first, "notes") == []
    assert observed_budgets.count((True, "30s", "3s")) == 2
    assert all(
        budget == (True, "30s", "3s") or budget == (False, "5s", "3s")
        for budget in observed_budgets
    )
    assert (False, "5s", "3s") in observed_budgets


def test_provisioning_timeout_is_private_and_never_retries_or_removes_marked_roles(
    data_store, monkeypatch
):
    owner = actor()
    database, migrator, gateway = data_store.names(owner.installation_id)
    execute = psycopg.Connection.execute
    create_attempts = []

    def cancel_create(conn, query, *args, **kwargs):
        if isinstance(query, sql.Composable):
            statement = query.as_string(conn)
            if statement.startswith("CREATE DATABASE "):
                assert statement.startswith(f'CREATE DATABASE "{database}" ')
                create_attempts.append(database)
                raise psycopg.errors.QueryCanceled("synthetic-private-provisioning-failure")
        return execute(conn, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", cancel_create)
    with pytest.raises(DataStoreError) as failed:
        prepare(data_store, owner)
    assert failed.value.code == "data_provision_unavailable"
    assert str(failed.value) == "data_provision_unavailable"
    assert isinstance(failed.value.__cause__, psycopg.errors.QueryCanceled)
    assert create_attempts == [database]
    with data_store._connect(autocommit=True) as conn:
        assert (
            conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone()
            is None
        )
        marker = f"miy-independent-data-v1:{owner.installation_id}:{owner.app_id}:development"
        roles = conn.execute(
            "SELECT rolname,shobj_description(oid,'pg_authid') FROM pg_roles "
            "WHERE rolname IN (%s,%s) ORDER BY rolname",
            (migrator, gateway),
        ).fetchall()
        assert roles == sorted([(migrator, marker), (gateway, marker)])


def test_request_bounds_and_rls_without_actor(data_store):
    identity = actor()
    prepare(data_store, identity)
    row = data_store.write(identity, "items", {"x": 1})
    database, _, gateway = data_store.names(identity.installation_id)
    with data_store._connect(database=database, role=gateway) as conn:
        assert conn.execute("SELECT count(*) FROM miy_data.records").fetchone() == (0,)
    with pytest.raises(DataStoreError, match="collection_invalid"):
        data_store.list_records(identity, "items; SELECT")
    with pytest.raises(DataStoreError, match="payload_invalid"):
        data_store.write(identity, "items", {"text": "x" * 16384})
    assert data_store.read(identity, "items", str(row["id"]))["payload"] == {"x": 1}


def test_key_gateway_schema_permission_and_routing_with_explicit_identity_override(data_store):
    # This proves routing, input and permission behavior, not native login/exchange.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from miy_api.app import localized_http_exception_handler
    from miy_api.domains.independent_apps import data_api

    owner = actor()
    prepare(data_store, owner)
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.include_router(data_api.router)
    app.dependency_overrides[data_api.identity] = lambda: owner
    app.dependency_overrides[data_api.get_store] = lambda: data_store
    with TestClient(app) as gateway:
        path = "/_data/items"
        lookup = path + "/by-key"
        created = gateway.post(path, json={"payload": {"value": 1}, "record_key": "key"})
        assert created.status_code == 201
        assert gateway.get(lookup, params={"record_key": "key"}).json() == created.json()
        assert (
            gateway.post(path, json={"payload": {"value": 2}, "record_key": "key"}).status_code
            == 409
        )
        assert gateway.get(lookup, params={"record_key": "absent"}).status_code == 404
        assert gateway.post(lookup, params={"record_key": "key"}, json={}).status_code == 405
        assert gateway.get(lookup + "/extra", params={"record_key": "key"}).status_code == 404
        for key in ("", "key\n", "x" * 257, "한" * 86, 7):
            assert gateway.post(path, json={"payload": {}, "record_key": key}).status_code == 422
        for key in ("", "key\n", "x" * 257, "한" * 86):
            assert gateway.get(lookup, params={"record_key": key}).status_code == 422
        assert (
            gateway.put(
                f"{path}/{created.json()['id']}",
                json={"payload": {}, "expected_version": 1, "record_key": "changed"},
            ).status_code
            == 422
        )
        app.dependency_overrides[data_api.identity] = lambda: owner.model_copy(
            update={"permissions": ["data:write"]}
        )
        assert gateway.get(lookup, params={"record_key": "key"}).status_code == 403
        assert gateway.post(path, json={"payload": {}, "record_key": "key"}).status_code == 409
        app.dependency_overrides[data_api.identity] = lambda: owner.model_copy(
            update={"permissions": ["data:read"]}
        )
        assert gateway.post(path, json={"payload": {}, "record_key": "other"}).status_code == 403
        assert gateway.get(lookup, params={"record_key": "key"}).json() == created.json()


def test_gateway_introspects_every_request_and_never_accepts_caller_owner(
    client, monkeypatch, data_store
):
    from miy_api.core.db import get_session_factory
    from miy_api.core.settings import get_settings
    from miy_api.domains.auth.models import AuthSession
    from miy_api.domains.independent_apps.data_api import get_store
    from miy_api.domains.independent_apps.models import AppInstallationRecord
    from sqlalchemy import select
    from test_independent_apps import setup_app, launch, exchange
    from test_independent_app_delivery import build_release

    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    admin, headers, definition, installation, installation_data = setup_app(client)
    manifest = definition["definition"] | {
        "runtime_profile": "web-api-postgres-v1",
        "requested_permissions": ["identity:read", "data:read", "data:write"],
    }
    updated = client.put(
        "/api/v1/independent-apps/definitions",
        headers=headers,
        json={
            "definition": manifest,
            "source_revision": "a" * 40,
            "expected_digest": definition["definition_digest"],
            "expected_source_revision": "a" * 40,
        },
    )
    assert updated.status_code == 200, updated.text
    configured = client.put(
        f"/api/v1/independent-apps/sample-independent/installations/{installation['id']}",
        headers=headers,
        json=installation_data
        | {
            "granted_permissions": manifest["requested_permissions"],
        },
    )
    assert configured.status_code == 200, configured.text
    installation = configured.json()
    release = build_release(updated.json())
    with get_session_factory()() as db:
        item = db.get(AppInstallationRecord, installation["id"])
        item.release_id = release
        item.state = "ready"
        db.commit()
    prepare(
        data_store, actor(installation["id"], user=admin["user"]["id"], app="sample-independent")
    )
    token = exchange(client, launch(client, headers, installation)).json()["token"]
    bearer = {"Authorization": "Bearer " + token}
    params = {"installation_id": installation["id"], "audience": installation["origin"]}
    client.app.dependency_overrides[get_store] = lambda: data_store
    path = "/api/v1/independent-apps/_data/notes"
    try:
        assert client.get(path, params=params, headers=headers).status_code == 401
        key_path = path + "/by-key"
        key_params = params | {"record_key": "same-key"}
        assert client.get(key_path, params=key_params, headers=headers).status_code == 401
        created = client.post(
            path, params=params, headers=bearer, json={"payload": {"text": "private"}}
        )
        assert created.status_code == 201, created.text
        assert (
            client.get(path, params=params, headers=bearer).json()["items"][0]["id"]
            == created.json()["id"]
        )
        keyed = client.post(
            path,
            params=params,
            headers=bearer,
            json={"payload": {"text": "original"}, "record_key": "same-key"},
        )
        assert keyed.status_code == 201
        observed = client.get(key_path, params=key_params, headers=bearer)
        assert observed.status_code == 200 and observed.json() == keyed.json()
        duplicate = client.post(
            path,
            params=params,
            headers=bearer,
            json={"payload": {"text": "changed"}, "record_key": "same-key"},
        )
        assert duplicate.status_code == 409
        assert client.get(key_path, params=key_params, headers=bearer).json() == keyed.json()
        assert (
            client.get(
                key_path, params=params | {"record_key": "absent"}, headers=bearer
            ).status_code
            == 404
        )
        assert client.post(key_path, params=key_params, headers=bearer, json={}).status_code == 405
        for key in ("", "key\n", "x" * 257, "한" * 86, 7):
            assert (
                client.post(
                    path,
                    params=params,
                    headers=bearer,
                    json={"payload": {}, "record_key": key},
                ).status_code
                == 422
            )
        assert (
            client.put(
                f"{path}/{keyed.json()['id']}",
                params=params,
                headers=bearer,
                json={"payload": {}, "expected_version": 1, "record_key": "changed-key"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                path,
                params=params,
                headers=bearer,
                json={
                    "payload": {"text": "forged"},
                    "owner_id": "someone-else",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                path,
                params=params,
                headers=bearer,
                json={
                    "payload": {"text": "x" * 21000},
                },
            ).status_code
            == 413
        )
        assert (
            client.get(
                path, params=params | {"installation_id": str(uuid4())}, headers=bearer
            ).status_code
            == 401
        )
        with get_session_factory()() as db:
            db.get(AppInstallationRecord, installation["id"]).granted_permissions = [
                "identity:read",
                "data:read",
            ]
            db.commit()
        assert (
            client.post(
                path, params=params, headers=bearer, json={"payload": {"text": "denied"}}
            ).status_code
            == 403
        )
        assert client.get(path, params=params, headers=bearer).status_code == 200
        with get_session_factory()() as db:
            db.get(AppInstallationRecord, installation["id"]).granted_permissions = [
                "identity:read",
                "data:write",
            ]
            db.commit()
        assert client.get(key_path, params=key_params, headers=bearer).status_code == 403
        assert (
            client.post(
                path,
                params=params,
                headers=bearer,
                json={"payload": {"text": "no read access"}, "record_key": "same-key"},
            ).status_code
            == 409
        )
        with get_session_factory()() as db:
            for source in db.scalars(
                select(AuthSession).where(AuthSession.user_id == admin["user"]["id"])
            ):
                source.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        assert client.get(path, params=params, headers=bearer).status_code == 401
        assert client.get(key_path, params=key_params, headers=bearer).status_code == 401
    finally:
        client.app.dependency_overrides.pop(get_store, None)
        get_settings.cache_clear()
