from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import subprocess
import time
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

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
    try:
        image = docker("image", "inspect", "postgres:17-alpine", "--format", "{{.Id}}")
    except (OSError, RuntimeError):
        pytest.skip("Disposable data tests need local postgres:17-alpine image and Docker; no pull")
    name = "miy-app-data-test-" + uuid4().hex
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
            "/var/lib/postgresql/data:rw,size=256m",
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
                with psycopg.connect(dsn, connect_timeout=1):
                    break
            except psycopg.Error:
                time.sleep(0.1)
        else:
            pytest.fail("Disposable PostgreSQL failed to start")
        yield dsn
    finally:
        docker("rm", "--force", name)


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
    data_store, isolated_data_cluster
):
    first, second = actor(), actor()
    prepare(data_store, first)
    prepare(data_store, second)
    database, _, gateway = data_store.names(first.installation_id)
    other, _, _ = data_store.names(second.installation_id)
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
        created = client.post(
            path, params=params, headers=bearer, json={"payload": {"text": "private"}}
        )
        assert created.status_code == 201, created.text
        assert (
            client.get(path, params=params, headers=bearer).json()["items"][0]["id"]
            == created.json()["id"]
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
            for source in db.scalars(
                select(AuthSession).where(AuthSession.user_id == admin["user"]["id"])
            ):
                source.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        assert client.get(path, params=params, headers=bearer).status_code == 401
    finally:
        client.app.dependency_overrides.pop(get_store, None)
        get_settings.cache_clear()
