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
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import snapshot
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied,
    move,
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


@pytest.mark.parametrize("version", [0, -1, 1, 2])
def test_default_rejects_managed_or_invalid_version(world, file_source_prepared, version):
    with world.connect(file_source_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            read(conn, file_source_prepared.partition, version)
        assert error.value.sqlstate == "55000"


@pytest.mark.parametrize(
    "change", ["managed", "wrong_version", "namespace", "inactive", "personal", "missing", "null"]
)
def test_fixed_managed_predicate_and_current_descriptor(world, file_source_prepared, change):
    identifier = str(uuid4())
    if change not in {"missing", "null"}:
        with world.connect() as conn:
            conn.execute(
                """INSERT INTO retrieval_partitions
                (id,source_namespace,candidate_scope_kind,candidate_user_id,state,is_default_ingest,metadata_version,created_at,updated_at)
                VALUES (%s::uuid,%s,'company',NULL,%s,false,3,clock_timestamp(),clock_timestamp())""",
                (
                    identifier,
                    "docs" if change == "namespace" else "files",
                    "retired" if change == "inactive" else "active",
                ),
            )
            if change == "personal":
                conn.execute(
                    "UPDATE retrieval_partitions SET candidate_scope_kind='personal',candidate_user_id=%s WHERE id=%s::uuid",
                    (world.actor.user.id, identifier),
                )
    with world.connect(file_source_prepared.source) as conn:
        if change == "managed":
            assert read(conn, identifier, 3) == identifier
            with pytest.raises(psycopg.Error) as error:
                read(conn, identifier)
            assert error.value.sqlstate == "55000"
        else:
            with pytest.raises(psycopg.Error) as error:
                read(
                    conn,
                    None if change == "null" else identifier,
                    2 if change == "wrong_version" else 3,
                )
            assert error.value.sqlstate == "55000"


@pytest.mark.parametrize("column", ["state", "metadata_version"])
def test_actual_source_share_holds_core_change_through_commit(world, file_source_prepared, column):
    p = file_source_prepared
    producer = world.connect(p.source)
    updater = world.connect()
    try:
        assert read(producer, p.partition) == p.partition
        pid = updater.info.backend_pid
        value = (
            "UPDATE retrieval_partitions SET state='retired',is_default_ingest=false WHERE id=%s::uuid"
            if column == "state"
            else "UPDATE retrieval_partitions SET metadata_version=metadata_version+1 WHERE id=%s::uuid"
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(updater.execute, value, (p.partition,))
            try:
                wait_for_exact_blocker(world, pid, producer.info.backend_pid)
                assert not future.done()
            finally:
                producer.commit()
                future.result(timeout=5)
        updater.commit()
        if column == "state":
            with pytest.raises(psycopg.Error) as error:
                read(producer, p.partition)
            assert error.value.sqlstate == "55000"
        else:
            assert read(producer, p.partition) == p.partition
    finally:
        producer.close()
        updater.close()


@pytest.mark.parametrize("mode", ["replay", "rollback", "partial"])
def test_new_profile_replay_and_caller_rollback(world, file_source_prepared, mode):
    p = file_source_prepared
    name = p.source if mode == "replay" else world.role()
    if mode == "partial":
        with world.connect() as conn:
            conn.execute(sql.SQL("GRANT SELECT(id) ON users TO {}").format(sql.Identifier(name)))
    before = snapshot(world, name)
    with Session(world.engine) as db:
        if mode == "partial":
            with pytest.raises(WriterControlError):
                prepare_file_source_partition_principal(
                    db,
                    world.actor,
                    role_name=name,
                    identity=p.identity,
                    expected=p.identity,
                    expected_state="active",
                )
        else:
            assert prepare_file_source_partition_principal(
                db,
                world.actor,
                role_name=name,
                identity=p.identity,
                expected=p.identity,
                expected_state="active",
            ).profile_prepared
            db.commit() if mode == "replay" else db.rollback()
    assert snapshot(world, name) == before


def test_old_extraction_principal_replay_does_not_expand(world, file_source_prepared):
    p = file_source_prepared
    before = snapshot(world, p.old_source)
    with Session(world.engine) as db:
        result = prepare_file_source_partition_principal(
            db,
            world.actor,
            role_name=p.old_source,
            identity=p.old_identity,
            expected=p.identity,
            expected_state="active",
        )
        assert not result.profile_prepared
        db.commit()
    assert snapshot(world, p.old_source) == before
    with world.connect(p.old_source) as conn:
        denied(conn, "SELECT public.miy_read_file_source_partition(NULL,NULL)")


@pytest.mark.parametrize("kind", ["base", "company"])
def test_old_base_company_replay_does_not_expand(world, extraction_prepared, kind):
    from miy_api.domains.official_apps.writer_roles import prepare_principal
    from miy_api.domains.official_apps.projection_partition_roles import (
        install_company_partition_reader,
    )

    p = extraction_prepared
    drain = move(world, p.identity, "active", state="draining", artifact=p.identity.artifact)
    name = world.role()
    owner = world.role(login=False)
    newowner = world.role(login=False)
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "9" * 64)
    with Session(world.engine) as db:
        if kind == "company":
            install_company_partition_reader(db, world.actor, reader_owner=owner, expected=drain)
        prepare_principal(
            db,
            world.actor,
            role_name=name,
            identity=identity,
            expected=drain,
            expected_state="draining",
            company_projection=kind == "company",
        )
        install_file_source_partition_guard(db, world.actor, guard_owner=newowner, expected=drain)
        db.commit()
    before = snapshot(world, name)
    with Session(world.engine) as db:
        result = prepare_file_source_partition_principal(
            db,
            world.actor,
            role_name=name,
            identity=identity,
            expected=drain,
            expected_state="draining",
        )
        assert not result.profile_prepared
        db.commit()
    assert snapshot(world, name) == before


@pytest.mark.parametrize(
    "drift",
    [
        "body",
        "public",
        "invoker",
        "stable",
        "strict",
        "parallel",
        "login",
        "whole_update",
        "extra_owner_column",
        "disabled_guard",
    ],
)
def test_fixed_drift_refuses_before_fresh_grant_or_audit(world, file_source_prepared, drift):
    p = file_source_prepared
    with world.connect() as conn:
        if drift == "body":
            conn.execute(
                "CREATE OR REPLACE FUNCTION public.miy_read_file_source_partition(partition_id uuid,managed_metadata_version integer) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS 'BEGIN RETURN partition_id; END'"
            )
        elif drift == "public":
            conn.execute(
                "GRANT EXECUTE ON FUNCTION public.miy_read_file_source_partition(uuid,integer) TO PUBLIC"
            )
        elif drift in {"invoker", "stable", "strict", "parallel"}:
            suffix = {
                "invoker": "SECURITY INVOKER",
                "stable": "STABLE",
                "strict": "STRICT",
                "parallel": "PARALLEL SAFE",
            }[drift]
            conn.execute(
                "ALTER FUNCTION public.miy_read_file_source_partition(uuid,integer) " + suffix
            )
        elif drift == "login":
            conn.execute(sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(p.owner)))
        elif drift == "whole_update":
            conn.execute(
                sql.SQL("GRANT UPDATE ON retrieval_partitions TO {}").format(
                    sql.Identifier(p.owner)
                )
            )
        elif drift == "extra_owner_column":
            conn.execute(
                sql.SQL("GRANT SELECT(updated_at) ON retrieval_partitions TO {}").format(
                    sql.Identifier(p.owner)
                )
            )
        else:
            conn.execute(
                "ALTER TABLE file_manager_files DISABLE TRIGGER miy_official_source_writer"
            )
    name = world.role()
    before = snapshot(world, name)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            prepare_file_source_partition_principal(
                db,
                world.actor,
                role_name=name,
                identity=p.identity,
                expected=p.identity,
                expected_state="active",
            )
    assert snapshot(world, name) == before


@pytest.mark.parametrize(
    "change", ["generation", "revoke", "source_name", "oid_recreate", "core_caller"]
)
def test_actual_identity_and_current_owner_are_not_metadata_or_guc(
    world, file_source_prepared, change
):
    p = file_source_prepared
    name = p.source
    with world.connect() as conn:
        if change == "generation":
            conn.execute(
                "UPDATE official_runtime_ownership SET generation=generation+1 WHERE scope='official.suite'"
            )
        elif change == "revoke":
            conn.execute(
                "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_name=%s",
                (name,),
            )
        elif change == "source_name":
            name = world.role()
            conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.miy_read_file_source_partition(uuid,integer) TO {}"
                ).format(sql.Identifier(name))
            )
        elif change == "oid_recreate":
            from test_official_writer_roles import PASSWORD

            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(PASSWORD))
            )
            conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.miy_read_file_source_partition(uuid,integer) TO {}"
                ).format(sql.Identifier(name))
            )
        else:
            name = world.role()
            conn.execute(
                sql.SQL("GRANT SELECT ON retrieval_partitions TO {}").format(sql.Identifier(name))
            )
            conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.miy_read_file_source_partition(uuid,integer) TO {}"
                ).format(sql.Identifier(name))
            )
    with world.connect(name) as conn:
        conn.execute("SET LOCAL miy.writer_generation='999'")
        with pytest.raises(psycopg.Error) as error:
            read(conn, p.partition)
        assert error.value.sqlstate == "55000"


@pytest.mark.parametrize("control", ["drain", "principal_revoke"])
def test_actual_source_admission_holds_current_control_through_commit(
    world, file_source_prepared, control
):
    p = file_source_prepared
    producer, updater = world.connect(p.source), world.connect()
    try:
        assert read(producer, p.partition) == p.partition
        query, args = (
            (
                "UPDATE official_runtime_ownership SET state='draining' WHERE scope='official.suite'",
                (),
            )
            if control == "drain"
            else (
                "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_name=%s",
                (p.source,),
            )
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(updater.execute, query, args)
            try:
                wait_for_exact_blocker(world, updater.info.backend_pid, producer.info.backend_pid)
                assert not future.done()
            finally:
                producer.commit()
                future.result(timeout=5)
        updater.commit()
        with pytest.raises(psycopg.Error) as error:
            read(producer, p.partition)
        assert error.value.sqlstate == "55000"
    finally:
        producer.close()
        updater.close()


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


def test_public_source_helper_uses_only_fixed_capability(world, file_source_prepared):
    from sqlalchemy import create_engine, event
    from psycopg.conninfo import make_conninfo
    from test_official_writer_roles import PASSWORD, sa_dsn
    from miy_api.domains.retrieval.prepared_file_partitions import (
        require_prepared_file_source_partition,
    )

    engine = create_engine(
        sa_dsn(make_conninfo(world.dsn, user=file_source_prepared.source, password=PASSWORD))
    )
    queries = []

    def record(connection, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as db:
            assert (
                require_prepared_file_source_partition(
                    db, partition_id=file_source_prepared.partition, managed_metadata_version=None
                )
                == file_source_prepared.partition
            )
            assert all("FROM retrieval_partitions" not in query for query in queries)
            assert any("miy_read_file_source_partition" in query for query in queries)
            db.commit()
    finally:
        event.remove(engine, "before_cursor_execute", record)
        engine.dispose()


@pytest.mark.parametrize(
    "extra", ["core_select", "credential", "group", "grant_option", "definer", "create"]
)
def test_unreviewed_role_refuses_before_grant_audit_or_principal(
    world, file_source_prepared, extra
):
    name = world.role()
    with world.connect() as conn:
        if extra == "core_select":
            query = "GRANT SELECT(id) ON retrieval_partitions TO {}"
        elif extra == "credential":
            query = "GRANT SELECT(token_hash) ON auth_sessions TO {}"
        elif extra == "grant_option":
            query = "GRANT SELECT(id) ON users TO {} WITH GRANT OPTION"
        elif extra == "create":
            query = "GRANT CREATE ON SCHEMA public TO {}"
        elif extra == "group":
            group = world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(name))
            )
            query = None
        else:
            conn.execute(
                "CREATE FUNCTION public.synthetic_file_source_extra() RETURNS integer LANGUAGE SQL SECURITY DEFINER AS 'SELECT 1'"
            )
            conn.execute("REVOKE ALL ON FUNCTION public.synthetic_file_source_extra() FROM PUBLIC")
            query = "GRANT EXECUTE ON FUNCTION public.synthetic_file_source_extra() TO {}"
        if query:
            conn.execute(sql.SQL(query).format(sql.Identifier(name)))
    before = snapshot(world, name)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            prepare_file_source_partition_principal(
                db,
                world.actor,
                role_name=name,
                identity=file_source_prepared.identity,
                expected=file_source_prepared.identity,
                expected_state="active",
            )
    assert snapshot(world, name) == before
    with world.connect() as conn:
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM official_writer_principals WHERE role_name=%s)", (name,)
        ).fetchone()[0]


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


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_fresh_append_roundtrip_is_inactive_and_old_schema_preserved(world):
    from alembic import command
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import sa_dsn

    config = _migration_config(sa_dsn(world.dsn))
    command.downgrade(config, "file_projection_20261007")
    command.upgrade(config, "head")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_proc p,LATERAL aclexplode(p.proacl) a WHERE p.oid='public.miy_read_file_source_partition(uuid,integer)'::regprocedure AND a.grantee=0)"
        ).fetchone()[0]
