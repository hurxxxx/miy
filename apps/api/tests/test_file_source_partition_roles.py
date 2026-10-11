"""Restricted Files Source UUID admission and actual retained descriptor SHARE."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
import time
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from miy_api.domains.official_apps.file_source_partition_roles import (
    file_source_partition_contract,
    install_file_source_partition_guard,
    prepare_file_source_partition_principal,
)
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import snapshot as snapshot
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied as denied,
    move as move,
    role_template as role_template,
    world as current_head_world,  # noqa: F401
)


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    return migration_revision_world(
        current_head_world,
        request,
        tmp_path,
        monkeypatch,
        expected_revision="file_effect_20261007",
    )


@pytest.fixture
def file_source_prepared(world, extraction_prepared):
    drain = move(
        world,
        extraction_prepared.identity,
        "active",
        state="draining",
        artifact=extraction_prepared.identity.artifact,
    )
    owner = world.role(login=False)
    with Session(world.engine) as db:
        install_file_source_partition_guard(db, world.actor, guard_owner=owner, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "f" * 64)
    with Session(world.engine) as db:
        prepared = prepare_file_source_partition_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
        )
        assert prepared.profile_prepared
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    return SimpleNamespace(
        source=source,
        owner=owner,
        identity=identity,
        partition=extraction_prepared.partition,
        old_source=extraction_prepared.source,
        old_identity=extraction_prepared.identity,
    )


def read(conn, partition, version=None):
    value = conn.execute(
        "SELECT public.miy_read_file_source_partition(%s::uuid,%s::integer)", (partition, version)
    ).fetchone()[0]
    return str(value)


def wait_for_exact_blocker(world, waiter, blocker, *, observer=None):
    """Poll with an owned default connection or a caller-owned preopened observer."""
    deadline = time.monotonic() + 4
    with world.connect(autocommit=True) if observer is None else nullcontext(observer) as observer:
        while time.monotonic() < deadline:
            if observer.execute(
                "SELECT %s=ANY(pg_blocking_pids(%s))", (blocker, waiter)
            ).fetchone()[0]:
                return
            time.sleep(0.02)
    raise AssertionError("actual waiter did not block on admitted Source transaction")


def test_actual_uuid_only_read_without_core_or_private_grants(world, file_source_prepared):
    p = file_source_prepared
    with Session(world.engine) as db:
        file_source_partition_contract(db)
    with world.connect(p.source) as conn:
        assert read(conn, p.partition) == p.partition
        for query in (
            "SELECT id FROM retrieval_partitions",
            "SELECT id FROM retrieval_partitions FOR SHARE",
            "UPDATE retrieval_partitions SET state=state WHERE false",
            "INSERT INTO retrieval_partitions SELECT * FROM retrieval_partitions WHERE false",
            "SELECT token_hash FROM auth_sessions",
            "SELECT password_hash FROM users",
            "SELECT public.miy_lock_file_projection_partition(NULL)",
            "SELECT public.miy_read_official_company_partition('docs',NULL)",
        ):
            denied(conn, query)
        assert conn.execute("SELECT id,status,login_blocked FROM users").fetchall()
        assert conn.execute(
            "SELECT id,user_id,expires_at,revoked_at,impersonator_user_id FROM auth_sessions"
        ).fetchall()
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                with conn.cursor().copy("COPY retrieval_partitions(id) FROM STDIN"):
                    pass
        assert error.value.sqlstate == "42501"


def test_managed_version_update_waits_then_old_bound_version_refuses(world, file_source_prepared):
    identifier = str(uuid4())
    with world.connect() as conn:
        conn.execute(
            """INSERT INTO retrieval_partitions
          (id,source_namespace,candidate_scope_kind,state,is_default_ingest,metadata_version,created_at,updated_at)
          VALUES (%s::uuid,'files','company','active',false,3,clock_timestamp(),clock_timestamp())""",
            (identifier,),
        )
    producer, updater = world.connect(file_source_prepared.source), world.connect()
    try:
        assert read(producer, identifier, 3) == identifier
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                updater.execute,
                "UPDATE retrieval_partitions SET metadata_version=4 WHERE id=%s::uuid",
                (identifier,),
            )
            try:
                wait_for_exact_blocker(world, updater.info.backend_pid, producer.info.backend_pid)
                assert not future.done()
            finally:
                producer.commit()
                future.result(timeout=5)
        updater.commit()
        with pytest.raises(psycopg.Error) as error:
            read(producer, identifier, 3)
        assert error.value.sqlstate == "55000"
    finally:
        producer.close()
        updater.close()


def test_new_capability_downgrade_requires_explicit_retirement(world, file_source_prepared):
    from alembic import command
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import sa_dsn

    config = _migration_config(sa_dsn(world.dsn))
    module = (
        ScriptDirectory.from_config(config).get_revision("file_source_partition_20261007").module
    )
    with pytest.raises(RuntimeError, match="file_source_partition_requires_draining"):
        with world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.downgrade()
    move(
        world,
        file_source_prepared.identity,
        "active",
        state="draining",
        artifact=file_source_prepared.identity.artifact,
    )
    with pytest.raises(RuntimeError, match="file_source_partition_requires_explicit_retirement"):
        command.downgrade(config, "file_projection_20261007")
    with world.connect() as conn:
        conn.execute(
            sql.SQL(
                "REVOKE EXECUTE ON FUNCTION public.miy_read_file_source_partition(uuid,integer) FROM {}"
            ).format(sql.Identifier(file_source_prepared.source))
        )
    command.downgrade(config, "file_projection_20261007")
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT to_regprocedure('public.miy_read_file_source_partition(uuid,integer)')"
            ).fetchone()[0]
            is None
        )
        assert conn.execute(
            "SELECT to_regprocedure('public.miy_lock_file_projection_partition(uuid)')"
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'miy_file_extraction_%'"
            ).fetchone()[0]
            == 8
        )
