"""Fixed Files effect identities and lifecycle on owned restricted PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from types import SimpleNamespace
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from test_alembic_migrations import _migration_config
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_materialization_roles import accepted, prepare as prepare_read
from test_file_projection_core_roles import file_core_prepared as file_core_prepared, snapshot
from test_file_projection_roles import reader_engine
from test_file_source_partition_roles import wait_for_exact_blocker
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied,
    role_template as role_template,
    world as current_head_world,  # noqa: F401
)
from test_prepared_files_ingress import c as c, publications as publications

from miy_api.domains.files.core_projection import prepared_core_file_projection
from miy_api.domains.files.materialization_source import load_prepared_file_materialization
from miy_api.domains.official_apps.file_materialization_effect_roles import (
    FILE_EFFECT_COLUMNS,
    FILE_EFFECT_INPUT_COLUMNS,
    FILE_EFFECT_READ_COLUMNS,
    FILE_EFFECT_TABLE,
    LOCK_FILE_MATERIALIZATION,
    file_materialization_effect_contract,
    install_file_materialization_effect_guard,
    prepare_file_materialization_effect_principal,
)
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.retrieval.projection_generations import (
    create_projection_generation,
    mark_generation_baselining,
)


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    return migration_revision_world(
        current_head_world,
        request,
        tmp_path,
        monkeypatch,
        expected_revision="file_effect_20261007",
        config_alias_module=__name__,
    )


def prepare(c, role, *, commit=True):
    with Session(c.world.engine) as db:
        result = prepare_file_materialization_effect_principal(
            db,
            c.world.actor,
            role_name=role,
            expected=c.roles.identity,
            expected_state="active",
        )
        db.commit() if commit else db.rollback()
        return result


@pytest.fixture
def file_effect_prepared(c):
    ref = accepted(c)
    owner, role = c.world.role(login=False), c.world.role()
    with Session(c.world.engine) as db:
        install_file_materialization_effect_guard(
            db,
            c.world.actor,
            owner_role_name=owner,
            expected=c.roles.identity,
            expected_state="active",
        )
        key = "effect_" + uuid4().hex[:12]
        gens = []
        for backend, schema in (("opensearch", 3), ("qdrant", 1)):
            generation = create_projection_generation(
                db,
                backend=backend,
                generation_key=key,
                physical_name=backend + "_" + key,
                alias_name=backend + "_alias",
                schema_version=schema,
            )
            mark_generation_baselining(db, generation_id=generation.id)
            gens.append((generation.id, generation.physical_name, generation.schema_version))
        db.commit()
    assert prepare(c, role).profile_prepared
    engine = reader_engine(c.world, role)
    with Session(engine) as db:
        with prepared_core_file_projection(db, projection_event=ref):
            output = load_prepared_file_materialization(db, projection_event=ref)
        descriptor_version = db.scalar(
            text("SELECT metadata_version FROM public.retrieval_partitions WHERE id=:id"),
            {"id": ref.retrieval_partition_id},
        )
    with c.world.connect() as conn:
        stamp = conn.execute(
            "SELECT extracted_at FROM public.file_manager_files WHERE id=%s", (ref.resource_id,)
        ).fetchone()[0]
    header = {
        "operation_id": str(uuid4()),
        **{f.name: getattr(ref, f.name) for f in fields(ref)},
        "partition_metadata_version": descriptor_version,
        "source_event_id": output.witness.source_event_id,
        "source_revision": output.witness.source_revision,
        "source_payload_digest": output.witness.payload_digest,
        "source_extracted_at": stamp,
        "keyword_generation_id": gens[0][0],
        "vector_generation_id": gens[1][0],
        "generation_key": key,
        "keyword_physical_name": gens[0][1],
        "vector_physical_name": gens[1][1],
        "keyword_schema_version": gens[0][2],
        "vector_schema_version": gens[1][2],
    }
    assert set(header) == set(FILE_EFFECT_INPUT_COLUMNS)
    try:
        yield SimpleNamespace(
            c=c,
            world=c.world,
            owner=owner,
            role=role,
            engine=engine,
            ref=ref,
            keyword=gens[0][0],
            vector=gens[1][0],
            header=header,
        )
    finally:
        engine.dispose()


def lock(conn, p, header=None):
    h = header or p.header
    return str(
        conn.execute(
            "SELECT public.miy_lock_file_materialization(%s,%s::uuid,%s::uuid,%s)",
            (
                h["event_sequence"],
                h["keyword_generation_id"],
                h["vector_generation_id"],
                h["partition_metadata_version"],
            ),
        ).fetchone()[0]
    )


def arm(conn, p, header=None):
    h = header or p.header
    assert lock(conn, p, h) == h["retrieval_partition_id"]
    return conn.execute(
        sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) RETURNING to_jsonb({})").format(
            sql.Identifier(FILE_EFFECT_TABLE),
            sql.SQL(",").join(map(sql.Identifier, FILE_EFFECT_INPUT_COLUMNS)),
            sql.SQL(",").join(sql.Placeholder() for _ in FILE_EFFECT_INPUT_COLUMNS),
            sql.Identifier(FILE_EFFECT_TABLE),
        ),
        tuple(h[c] for c in FILE_EFFECT_INPUT_COLUMNS),
    ).fetchone()[0]


def complete(conn, p):
    lock(conn, p)
    return conn.execute(
        "UPDATE public.core_file_materialization_operations SET state='complete' "
        "WHERE operation_id=%s::uuid RETURNING to_jsonb(core_file_materialization_operations)",
        (p.header["operation_id"],),
    ).fetchone()[0]


def test_genuine_arm_complete_and_immutable_history(file_effect_prepared):
    p = file_effect_prepared
    with Session(p.world.engine) as db:
        file_materialization_effect_contract(db)
    with p.world.connect(p.role) as conn:
        original = arm(conn, p)
        assert set(original) == set(FILE_EFFECT_COLUMNS)
        assert conn.execute(
            "SELECT pg_catalog.has_function_privilege(current_user,%s,'EXECUTE')",
            (LOCK_FILE_MATERIALIZATION,),
        ).fetchone()[0]
        assert original["state"] == "armed" and original["completed_at"] is None
        assert original["issuer_role_name"] == p.role and original["issuer_role_oid"] > 0
        assert len(original["header_digest"]) == 64 and original["armed_xact_id"].isdigit()
        conn.commit()
        final = complete(conn, p)
        conn.commit()
        assert final["state"] == "complete" and final["completed_at"] is not None
        assert {k: v for k, v in original.items() if k not in {"state", "completed_at"}} == {
            k: v for k, v in final.items() if k not in {"state", "completed_at"}
        }
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                complete(conn, p)
        assert caught.value.sqlstate == "55000"
        for query in (
            "DELETE FROM core_file_materialization_operations WHERE false",
            "TRUNCATE core_file_materialization_operations",
            "UPDATE core_file_materialization_operations SET header_digest=header_digest WHERE false",
        ):
            denied(conn, query)


def test_actual_minimal_effect_profile_and_no_source_authority(file_effect_prepared):
    p = file_effect_prepared
    assert sum(map(len, FILE_EFFECT_READ_COLUMNS.values())) == 125
    with p.world.connect(p.role) as conn:
        lock(conn, p)
        for query in (
            "SELECT storage_key FROM file_manager_files",
            "SELECT extraction_error_code FROM file_manager_files",
            "SELECT password_hash FROM users",
            "SELECT token_hash FROM auth_sessions",
            "SELECT source_uri FROM file_manager_file_source_metadata",
            "SELECT raw_metadata FROM file_manager_file_source_metadata",
            "SELECT * FROM official_writer_principals",
            "SELECT * FROM file_extraction_requests",
            "SELECT alias_name FROM retrieval_projection_generations",
            "SELECT trace_context FROM search_index_jobs",
            "SELECT last_error FROM rag_sync_jobs",
            "SELECT id FROM file_manager_files FOR SHARE",
            "SELECT id FROM file_manager_corpora FOR SHARE",
            "SELECT id FROM retrieval_partitions FOR SHARE",
            "SELECT id FROM retrieval_projection_generations FOR SHARE",
            "SELECT resource_id FROM retrieval_projection_heads FOR SHARE",
            "UPDATE file_manager_files SET filename=filename WHERE false",
            "UPDATE retrieval_projection_heads SET projection_version=projection_version WHERE false",
            "UPDATE retrieval_projection_generations SET state=state WHERE false",
            "INSERT INTO retrieval_projection_events SELECT * FROM retrieval_projection_events WHERE false",
            "SELECT public.miy_lock_file_projection_partition(NULL)",
            "SELECT public.miy_file_extraction_admit(NULL)",
        ):
            denied(conn, query)
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                with conn.cursor().copy("COPY file_manager_files(id) FROM STDIN"):
                    pass
        assert caught.value.sqlstate == "42501"
    with p.world.connect(p.c.roles.source) as conn:
        denied(conn, "SELECT public.miy_lock_file_materialization(1,NULL,NULL,1)")
        denied(conn, "SELECT operation_id FROM core_file_materialization_operations")


def test_private_owner_has_only_three_operation_columns(file_effect_prepared):
    p = file_effect_prepared
    with p.world.connect() as conn:
        allowed = conn.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid='core_file_materialization_operations'::regclass "
            "AND attnum>0 AND NOT attisdropped AND has_column_privilege(%s,attrelid,attname,'SELECT') ORDER BY attname",
            (p.owner,),
        ).fetchall()
        assert allowed == [("keyword_generation_id",), ("state",), ("vector_generation_id",)]
        assert not conn.execute(
            "SELECT has_column_privilege(%s,'core_file_materialization_operations','header_digest','SELECT') "
            "OR has_column_privilege(%s,'core_file_materialization_operations','source_event_id','SELECT')",
            (p.owner, p.owner),
        ).fetchone()[0]
        conn.execute(
            sql.SQL(
                "GRANT SELECT(header_digest) ON core_file_materialization_operations TO {}"
            ).format(sql.Identifier(p.owner))
        )
    role = p.world.role()
    before = snapshot(p.world, role)
    with pytest.raises(WriterControlError):
        prepare(p.c, role)
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize("nested", [False, True])
def test_arm_cannot_complete_in_same_top_transaction(file_effect_prepared, nested):
    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                if nested:
                    with conn.transaction():
                        arm(conn, p)
                else:
                    arm(conn, p)
                complete(conn, p)
        assert caught.value.sqlstate == "55000"
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "field",
    [
        "resource_id",
        "source_event_id",
        "source_revision",
        "source_payload_digest",
        "source_extracted_at",
        "keyword_physical_name",
        "generation_key",
        "visibility_checksum",
    ],
)
def test_fabricated_header_refuses_without_history(file_effect_prepared, field):
    p = file_effect_prepared
    h = dict(p.header)
    h[field] = (
        str(uuid4())
        if field.endswith("_id")
        else 999
        if field == "source_revision"
        else None
        if field == "source_extracted_at"
        else "synthetic-wrong"
    )
    with p.world.connect(p.role) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                arm(conn, p, h)
        assert caught.value.sqlstate == "55000"
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("mode", ["replay", "rollback", "partial"])
def test_new_preparation_replay_and_atomic_rollback(file_effect_prepared, mode):
    p = file_effect_prepared
    role = p.role if mode == "replay" else p.world.role()
    if mode == "partial":
        with p.world.connect() as conn:
            conn.execute(sql.SQL("GRANT SELECT(id) ON users TO {}").format(sql.Identifier(role)))
    before = snapshot(p.world, role)
    if mode == "partial":
        with pytest.raises(WriterControlError):
            prepare(p.c, role)
    else:
        assert prepare(p.c, role, commit=mode == "replay").profile_prepared
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize("kind", ["strict", "f3", "source"])
def test_old_profiles_never_gain_effect_grants(file_effect_prepared, kind):
    p = file_effect_prepared
    role = (
        p.world.role() if kind == "strict" else p.c.roles.core if kind == "f3" else p.c.roles.source
    )
    if kind == "strict":
        assert prepare_read(p.c, role).profile_prepared
    before = snapshot(p.world, role)
    if kind == "source":
        with pytest.raises(WriterControlError, match="source_identity_forbidden"):
            prepare(p.c, role)
    else:
        assert not prepare(p.c, role).profile_prepared
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize(
    "column", ["state", "physical_name", "metadata_version", "projection_version"]
)
def test_actual_lifecycle_and_head_updates_wait_through_commit(file_effect_prepared, column):
    p = file_effect_prepared
    admitted, updater = p.world.connect(p.role), p.world.connect()
    try:
        lock(admitted, p)
        if column in {"state", "physical_name"}:
            query = (
                "UPDATE retrieval_projection_generations SET "
                + column
                + ("='validating'" if column == "state" else "=physical_name||'_changed'")
                + " WHERE id=%s::uuid"
            )
            identifier = p.keyword
        elif column == "metadata_version":
            query, identifier = (
                "UPDATE retrieval_partitions SET metadata_version=metadata_version+1 WHERE id=%s::uuid",
                p.ref.retrieval_partition_id,
            )
        else:
            query, identifier = (
                "UPDATE retrieval_projection_heads SET projection_version=projection_version+1 WHERE resource_type='file_manager_file' AND resource_id=%s",
                p.ref.resource_id,
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(updater.execute, query, (identifier,))
            try:
                wait_for_exact_blocker(p.world, updater.info.backend_pid, admitted.info.backend_pid)
                assert not future.done()
            finally:
                admitted.commit()
                future.result(timeout=5)
        updater.commit()
        with pytest.raises(psycopg.Error) as caught:
            arm(admitted, p)
        assert caught.value.sqlstate == "55000"
    finally:
        admitted.close()
        updater.close()


@pytest.mark.parametrize("change", ["phase", "key", "physical", "schema", "baseline", "replay"])
def test_durable_armed_holds_all_generation_progress(file_effect_prepared, change):
    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        arm(conn, p)
    expression = {
        "phase": "state='replaying'",
        "key": "generation_key=generation_key||'_changed'",
        "physical": "physical_name=physical_name||'_changed'",
        "schema": "schema_version=schema_version+1",
        "baseline": "baseline_event_sequence=baseline_event_sequence+1,replay_event_sequence=replay_event_sequence+1",
        "replay": "replay_event_sequence=replay_event_sequence+1",
    }[change]
    with p.world.connect() as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "UPDATE retrieval_projection_generations SET "
                    + expression
                    + " WHERE id=%s::uuid",
                    (p.keyword,),
                )
        assert caught.value.sqlstate == "55000"
        assert caught.value.diag.message_primary == "file_materialization_effect_generation_armed"
        conn.execute(
            "UPDATE retrieval_projection_generations SET state=state,replay_event_sequence=replay_event_sequence WHERE id=%s::uuid",
            (p.keyword,),
        )
    with p.world.connect(p.role) as conn:
        complete(conn, p)
    with p.world.connect() as conn:
        conn.execute(
            "UPDATE retrieval_projection_generations SET state='replaying' WHERE id=%s::uuid",
            (p.keyword,),
        )


def test_waiting_generation_update_sees_arm_committed_after_statement_start(file_effect_prepared):
    p = file_effect_prepared
    admitted, updater = p.world.connect(p.role), p.world.connect()
    try:
        lock(admitted, p)

        def transition():
            try:
                updater.execute(
                    "UPDATE retrieval_projection_generations SET state='replaying' WHERE id=%s::uuid",
                    (p.keyword,),
                )
                updater.commit()
                return None
            except psycopg.Error as error:
                updater.rollback()
                return error.sqlstate, error.diag.message_primary

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(transition)
            try:
                wait_for_exact_blocker(p.world, updater.info.backend_pid, admitted.info.backend_pid)
                arm(admitted, p)
            finally:
                admitted.commit()
            assert future.result(timeout=5) == (
                "55000",
                "file_materialization_effect_generation_armed",
            )
        assert (
            updater.execute(
                "SELECT state FROM retrieval_projection_generations WHERE id=%s::uuid", (p.keyword,)
            ).fetchone()[0]
            == "baselining"
        )
    finally:
        admitted.close()
        updater.close()


def test_effect_fixture_restore_failure_preserves_history_and_guards(
    file_effect_prepared, tmp_path
):
    import conftest

    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        original = arm(conn, p)
    target = tmp_path / "must-not-exist.dump"
    with pytest.raises(RuntimeError, match="protocol fixture baseline must be empty"):
        conftest._capture_application_postgres_state(
            p.world.engine.url.render_as_string(hide_password=False), target
        )
    assert not target.exists()
    with p.world.connect() as conn:
        guards = conn.execute(
            "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='core_file_materialization_operations'::regclass ORDER BY tgname"
        ).fetchall()
    with pytest.raises(SQLAlchemyError):
        with p.world.engine.begin() as connection:
            reset = conftest._truncate_test_database_statements(connection)
            disables = [
                s for s in reset if "core_file_materialization_operations DISABLE TRIGGER" in s
            ]
            assert len(disables) == 1 and "miy_file_materialization_effect_writer" in disables[0]
            connection.exec_driver_sql(disables[0])
            connection.exec_driver_sql("TRUNCATE public.core_file_materialization_operations")
            connection.exec_driver_sql("SELECT public.synthetic_effect_restore_failure()")
    with p.world.connect(p.role) as conn:
        assert (
            conn.execute(
                "SELECT to_jsonb(o) FROM core_file_materialization_operations o"
            ).fetchone()[0]
            == original
        )
    with p.world.connect() as conn:
        assert (
            conn.execute(
                "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='core_file_materialization_operations'::regclass ORDER BY tgname"
            ).fetchall()
            == guards
        )


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_new_effect_schema_history_and_explicit_retirement_gate(file_effect_prepared):
    p = file_effect_prepared
    config = _migration_config(p.world.engine.url.render_as_string(hide_password=False))
    module = ScriptDirectory.from_config(config).get_revision("file_effect_20261007").module
    with pytest.raises(RuntimeError, match="requires_draining"):
        with p.world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.downgrade()
    with p.world.connect(p.role) as conn:
        arm(conn, p)
    from test_official_writer_roles import move

    move(
        p.world,
        p.c.roles.identity,
        "active",
        state="draining",
        artifact=p.c.roles.identity.artifact,
    )
    with pytest.raises(RuntimeError, match="history_retirement_required"):
        with p.world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.downgrade()
    with p.world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "drift", ["body", "disabled", "wrong_columns", "private_exec", "index", "expression", "include"]
)
def test_fixed_function_trigger_and_hold_index_drift_refuses_before_grant(
    file_effect_prepared, drift
):
    p = file_effect_prepared
    with p.world.connect() as conn:
        if drift == "body":
            conn.execute(
                "CREATE OR REPLACE FUNCTION public.miy_lock_file_materialization(event_sequence bigint,keyword_generation_id uuid,vector_generation_id uuid,expected_partition_metadata_version integer) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN RETURN NULL; END $$"
            )
        elif drift == "disabled":
            conn.execute(
                "ALTER TABLE retrieval_projection_generations DISABLE TRIGGER miy_file_materialization_generation"
            )
        elif drift == "wrong_columns":
            conn.execute(
                "DROP TRIGGER miy_file_materialization_generation ON retrieval_projection_generations"
            )
            conn.execute(
                "CREATE TRIGGER miy_file_materialization_generation BEFORE UPDATE OF state ON retrieval_projection_generations FOR EACH ROW EXECUTE FUNCTION public.miy_guard_file_materialization_generation()"
            )
        elif drift == "private_exec":
            conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.miy_guard_file_materialization_effect_row() TO {}"
                ).format(sql.Identifier(p.role))
            )
        else:
            conn.execute("DROP INDEX uq_core_file_materialization_armed_keyword")
            if drift == "expression":
                conn.execute(
                    "CREATE UNIQUE INDEX uq_core_file_materialization_armed_keyword ON "
                    "public.core_file_materialization_operations "
                    "(resource_id,keyword_generation_id,(source_event_id::text)) WHERE state='armed'"
                )
            elif drift == "include":
                conn.execute(
                    "CREATE UNIQUE INDEX uq_core_file_materialization_armed_keyword ON "
                    "public.core_file_materialization_operations "
                    "(resource_id,keyword_generation_id) INCLUDE(source_event_id) WHERE state='armed'"
                )
    role = p.world.role()
    before = snapshot(p.world, role)
    with pytest.raises(WriterControlError):
        prepare(p.c, role)
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize(
    "extra",
    [
        "GRANT SELECT(storage_key) ON file_manager_files TO {role}",
        "GRANT UPDATE(filename) ON file_manager_files TO {role}",
        "GRANT SELECT(token_hash) ON auth_sessions TO {role}",
        "GRANT SELECT(source_uri) ON file_manager_file_source_metadata TO {role}",
        "GRANT SELECT(generation) ON official_writer_principals TO {role}",
        "GRANT SELECT(alias_name) ON retrieval_projection_generations TO {role}",
        "GRANT UPDATE(state) ON retrieval_partitions TO {role}",
        "GRANT UPDATE(projection_version) ON retrieval_projection_heads TO {role}",
        "GRANT INSERT ON official_projection_receipts TO {role}",
        "GRANT UPDATE(header_digest) ON core_file_materialization_operations TO {role}",
        "GRANT SELECT(trace_context) ON search_index_jobs TO {role}",
        "GRANT SELECT(last_error) ON rag_sync_jobs TO {role}",
        "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_result_digest(uuid,text) TO {role}",
        "GRANT USAGE ON SEQUENCE retrieval_projection_events_event_sequence_seq TO {role}",
        "GRANT CREATE ON SCHEMA public TO {role}",
        "ALTER ROLE {role} INHERIT",
    ],
)
def test_unreviewed_role_extras_refuse_atomic_preparation(file_effect_prepared, extra):
    p = file_effect_prepared
    role = p.world.role()
    with p.world.connect() as conn:
        conn.execute(sql.SQL(extra).format(role=sql.Identifier(role)))
    before = snapshot(p.world, role)
    with pytest.raises(WriterControlError):
        prepare(p.c, role)
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize("mode", ["actual", "renamed_oid", "retained_name"])
def test_actual_source_oid_or_retained_name_cannot_invoke_capability(file_effect_prepared, mode):
    p = file_effect_prepared
    original, caller = p.c.roles.source, p.c.roles.source
    if mode != "actual":
        renamed = "source_renamed_" + uuid4().hex[:16]
        with p.world.connect() as conn:
            conn.execute(
                sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                    sql.Identifier(original), sql.Identifier(renamed)
                )
            )
        p.world.roles.remove(original)
        p.world.roles.append(renamed)
        caller = renamed
        if mode == "retained_name":
            from test_official_writer_roles import PASSWORD

            with p.world.connect() as conn:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(original), sql.Literal(PASSWORD))
                )
            p.world.roles.append(original)
            caller = original
    with p.world.connect() as conn:
        conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_lock_file_materialization(bigint,uuid,uuid,integer) TO {}"
            ).format(sql.Identifier(caller))
        )
    with p.world.connect(caller) as conn:
        conn.execute("SET LOCAL miy.writer_generation='999'")
        with pytest.raises(psycopg.Error) as caught:
            lock(conn, p)
        assert caught.value.sqlstate == "55000"
        assert caught.value.diag.message_primary == "file_materialization_effect_authority_invalid"


def test_actual_root_runner_arm_and_effect_complete_on_restricted_profile(file_effect_prepared):
    from miy_api.domains.retrieval.prepared_file_effects import (
        FileMaterializationEffectSpec,
        PreparedFileEffectRunner,
        PreparedFileGenerationPair,
    )

    p = file_effect_prepared
    pair = PreparedFileGenerationPair(
        **{name: p.header[name] for name in PreparedFileGenerationPair.__dataclass_fields__}
    )
    spec = FileMaterializationEffectSpec(
        operation_id=p.header["operation_id"],
        projection_event=p.ref,
        generation_pair=pair,
        partition_metadata_version=p.header["partition_metadata_version"],
    )
    runner = PreparedFileEffectRunner(lambda: Session(p.engine))
    permit = runner.arm(spec)
    calls = []

    def known_effect(db, materialization, require_current):
        require_current()
        calls.append(
            (
                materialization.keyword_document is not None,
                materialization.rag_projection is not None,
            )
        )
        require_current()

    receipt = runner.execute(permit, known_effect)
    assert calls == [(True, True)] and receipt.state == "complete" and not receipt.provisional
    historical = runner.observe(spec, expected_header_digest=receipt.header_digest)
    assert historical.state == "complete" and historical.historical
    with p.world.connect(p.role) as conn:
        assert (
            conn.execute("SELECT state FROM core_file_materialization_operations").fetchone()[0]
            == "complete"
        )


def _root_spec(p):
    from miy_api.domains.retrieval.prepared_file_effects import (
        FileMaterializationEffectSpec,
        PreparedFileGenerationPair,
    )

    pair = PreparedFileGenerationPair(
        **{name: p.header[name] for name in PreparedFileGenerationPair.__dataclass_fields__}
    )
    return FileMaterializationEffectSpec(
        p.header["operation_id"], p.ref, pair, p.header["partition_metadata_version"]
    )


def _current_header(p, ref):
    with Session(p.engine) as db:
        with prepared_core_file_projection(db, projection_event=ref):
            output = load_prepared_file_materialization(db, projection_event=ref)
    with p.world.connect() as conn:
        stamp = conn.execute(
            "SELECT extracted_at FROM public.file_manager_files WHERE id=%s", (ref.resource_id,)
        ).fetchone()[0]
    return {
        **p.header,
        "operation_id": str(uuid4()),
        **{f.name: getattr(ref, f.name) for f in fields(ref)},
        "source_event_id": output.witness.source_event_id,
        "source_revision": output.witness.source_revision,
        "source_payload_digest": output.witness.payload_digest,
        "source_extracted_at": stamp,
    }


def test_exact_f1_old_reader_replay_has_no_effect_grants(file_effect_prepared):
    from miy_api.domains.official_apps.file_projection_roles import prepare_file_projection_reader

    p = file_effect_prepared
    role = p.world.role()
    with Session(p.world.engine) as db:
        prepared = prepare_file_projection_reader(
            db, p.world.actor, role_name=role, expected=p.c.roles.identity, expected_state="active"
        )
        assert prepared["role_name"] == role and prepared["role_oid"] > 0
        db.commit()
    before = snapshot(p.world, role)
    assert not prepare(p.c, role).profile_prepared
    assert snapshot(p.world, role) == before


@pytest.mark.parametrize("watermark", [False, True])
def test_repeatable_read_generation_mutation_denied_even_without_armed(
    file_effect_prepared, watermark
):
    p = file_effect_prepared
    with p.world.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        conn.execute(
            "UPDATE retrieval_projection_generations SET state=state WHERE id=%s::uuid",
            (p.keyword,),
        )
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "UPDATE retrieval_projection_generations SET "
                    + (
                        "replay_event_sequence=replay_event_sequence+1"
                        if watermark
                        else "state='replaying'"
                    )
                    + " WHERE id=%s::uuid",
                    (p.keyword,),
                )
        assert caught.value.sqlstate == "55000"
        assert (
            caught.value.diag.message_primary
            == "file_materialization_effect_requires_read_committed"
        )
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 0
        )


def test_pair_controller_and_cap_share_with_opposite_uuid_order(file_effect_prepared):
    from miy_api.domains.retrieval import projection_generations as control

    p = file_effect_prepared
    ids = ("ffffffff-ffff-4fff-8fff-fffffffffff1", "00000000-0000-4000-8000-000000000001")
    with p.world.connect() as conn:
        for before, after in zip((p.keyword, p.vector), ids, strict=True):
            conn.execute(
                "UPDATE retrieval_projection_generations SET id=%s::uuid WHERE id=%s::uuid",
                (after, before),
            )
    p.keyword, p.vector = ids
    p.header.update(keyword_generation_id=ids[0], vector_generation_id=ids[1])
    admitted = p.world.connect(p.role)
    controller = Session(p.world.engine)
    try:
        assert lock(admitted, p) == p.ref.retrieval_partition_id
        pid = controller.scalar(text("SELECT pg_backend_pid()"))

        def pair_update():
            control._lock_pair_control_plane(controller)
            pair = control._locked_pair(
                controller, opensearch_generation_id=p.keyword, qdrant_generation_id=p.vector
            )
            result = (pair.opensearch.id, pair.qdrant.id)
            controller.commit()
            return result

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(pair_update)
            try:
                wait_for_exact_blocker(p.world, pid, admitted.info.backend_pid)
                assert not future.done()
            finally:
                admitted.commit()
            assert future.result(timeout=5) == ids
    finally:
        admitted.close()
        controller.close()


def test_standalone_generation_row_then_backend_gate_does_not_cycle(file_effect_prepared):
    from threading import Event
    from miy_api.domains.retrieval import projection_generations as control

    p = file_effect_prepared
    blocker, admitted = p.world.connect(), p.world.connect(p.role)
    standalone = Session(p.world.engine)
    row_locked = Event()
    try:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('retrieval-projection-generation:qdrant',0))"
        )
        pid = standalone.scalar(text("SELECT pg_backend_pid()"))

        def row_then_backend():
            control._locked_generation(standalone, generation_id=p.vector)
            row_locked.set()
            control._lock_backend_control_plane(standalone, "qdrant")
            standalone.commit()
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(row_then_backend)
            try:
                assert row_locked.wait(timeout=5)
                wait_for_exact_blocker(p.world, pid, blocker.info.backend_pid)
                new = pool.submit(lock, admitted, p)
                wait_for_exact_blocker(p.world, admitted.info.backend_pid, pid)
            finally:
                blocker.commit()
            assert old.result(timeout=5)
            assert new.result(timeout=5) == p.ref.retrieval_partition_id
            admitted.commit()
    finally:
        blocker.close()
        admitted.close()
        standalone.close()


def test_distinct_files_can_hold_same_generation_pair_concurrently(file_effect_prepared):
    import json
    from test_file_extraction_authority import seeded_request
    from miy_api.domains.files.extraction_contracts import (
        FileExtractionInput,
        FileExtractionRequestSpec,
    )

    p = file_effect_prepared
    second = SimpleNamespace(**vars(p.c))
    values = seeded_request(p.world, p.c.roles)
    payload = json.loads(values["request_payload"])
    second.spec = FileExtractionRequestSpec(
        request_id=values["request_id"],
        result_id=values["result_id"],
        event_id=values["event_id"],
        file_id=values["file_id"],
        actor_user_id=p.world.user_id,
        execution_ref=p.world.session_id,
        expected_input=FileExtractionInput.model_validate_json(payload["input_canonical"]),
    )
    second.token = uuid4()
    ref = accepted(second)
    h = _current_header(p, ref)
    first, other = p.world.connect(p.role), p.world.connect(p.role)
    try:
        arm(first, p)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(arm, other, p, h)
            try:
                assert future.result(timeout=5)["resource_id"] == ref.resource_id
            finally:
                first.commit()
                other.commit()
        assert (
            first.execute(
                "SELECT count(*) FROM core_file_materialization_operations WHERE state='armed'"
            ).fetchone()[0]
            == 2
        )
    finally:
        first.close()
        other.close()


@pytest.mark.parametrize("remaining", ["keyword", "vector"])
def test_each_armed_target_index_blocks_genuine_later_event(file_effect_prepared, remaining):
    from test_prepared_files_ingress import append, consume
    from miy_api.domains.retrieval.models import RetrievalProjectionEvent
    from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef

    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        original = arm(conn, p)
    next_source = append(p.c, checksum=p.ref.content_checksum)
    receipt = consume(p.c, next_source)
    with Session(p.world.engine) as db:
        row = db.get(RetrievalProjectionEvent, receipt.core_event_sequence)
        ref = ProjectionEventRef(
            **{f.name: getattr(row, f.name) for f in fields(ProjectionEventRef)}
        )
    h = _current_header(p, ref)
    # Isolate each persisted uniqueness rule in a privileged disposable fixture.
    # The missing peer index would forbid new preparation; no new role is prepared.
    retired = "vector" if remaining == "keyword" else "keyword"
    with p.world.connect() as conn:
        conn.execute(
            sql.SQL("DROP INDEX {}").format(
                sql.Identifier("uq_core_file_materialization_armed_" + retired)
            )
        )
    with p.world.connect(p.role) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                arm(conn, p, h)
        assert caught.value.sqlstate == "23505"
        assert (
            caught.value.diag.constraint_name == "uq_core_file_materialization_armed_" + remaining
        )
        assert (
            conn.execute(
                "SELECT to_jsonb(o) FROM core_file_materialization_operations o"
            ).fetchone()[0]
            == original
        )


@pytest.mark.parametrize("history_state", ["armed", "complete"])
def test_root_historical_observer_does_not_require_current_source_head(
    file_effect_prepared, history_state
):
    from test_prepared_files_ingress import append, consume
    from miy_api.domains.retrieval.prepared_file_effects import PreparedFileEffectRunner

    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        original = arm(conn, p)
    if history_state == "complete":
        with p.world.connect(p.role) as conn:
            original = complete(conn, p)
    with p.c.source() as db:
        db.execute(
            text("UPDATE file_manager_files SET deleted_at=clock_timestamp() WHERE id=:id"),
            {"id": p.ref.resource_id},
        )
        db.commit()
    deletion = consume(p.c, append(p.c, state="deleted"))
    assert deletion.core_event_sequence != p.ref.event_sequence
    with p.world.connect() as conn:
        assert conn.execute(
            "SELECT desired_state,projection_version FROM retrieval_projection_heads "
            "WHERE resource_type='file_manager_file' AND resource_id=%s",
            (p.ref.resource_id,),
        ).fetchone() == ("deleted", p.ref.projection_version + 1)
    runner = PreparedFileEffectRunner(lambda: Session(p.engine))
    history = runner.observe(_root_spec(p), expected_header_digest=original["header_digest"])
    assert history.historical and history.state == history_state and not history.provisional
    assert runner.arm(_root_spec(p)).historical


@pytest.mark.parametrize("binding", ["connection", "mapper", "clause"])
def test_actual_root_runner_borrowed_routes_preserve_caller_without_sql(
    file_effect_prepared, binding
):
    from sqlalchemy import event
    from miy_api.domains.files.models import FileManagerFile
    from miy_api.domains.retrieval.prepared_file_effects import (
        FileMaterializationRefused,
        PreparedFileEffectRunner,
    )

    p = file_effect_prepared
    caller = p.engine.connect()
    tx = caller.begin()
    caller.execute(
        text("UPDATE search_index_jobs SET attempts=7 WHERE entity_id=:id"),
        {"id": p.ref.resource_id},
    )
    alternate = p.engine.execution_options()
    if binding == "connection":
        db = Session(caller)
    elif binding == "mapper":
        db = Session(p.engine, binds={FileManagerFile: caller})
    else:

        class Routed(Session):
            def get_bind(self, mapper=None, *, clause=None, **kw):
                if (
                    clause is not None
                    and getattr(clause, "get_final_froms", None)
                    and clause.get_final_froms() == [FileManagerFile.__table__]
                ):
                    return alternate
                return super().get_bind(mapper, clause=clause, **kw)

        db = Routed(p.engine)
    sql_calls, controls = [], []

    def before_cursor(*_args):
        sql_calls.append("sql")

    original_close, original_rollback = db.close, db.rollback
    db.close = lambda: controls.append("close")
    db.rollback = lambda: controls.append("rollback")
    event.listen(p.engine, "before_cursor_execute", before_cursor)
    try:
        with pytest.raises(FileMaterializationRefused):
            PreparedFileEffectRunner(lambda: db).arm(_root_spec(p))
        assert not sql_calls and not controls and tx.is_active
        assert (
            caller.scalar(
                text("SELECT attempts FROM search_index_jobs WHERE entity_id=:id"),
                {"id": p.ref.resource_id},
            )
            == 7
        )
    finally:
        event.remove(p.engine, "before_cursor_execute", before_cursor)
        db.close, db.rollback = original_close, original_rollback
        db.close()
        tx.rollback()
        caller.close()


def _materializer(p, calls):
    from miy_api.domains.rag.contracts import RagSyncOperation, RagSyncResult
    from miy_api.domains.retrieval.prepared_file_materializer import (
        PreparedFilesCachedProjectionMaterializer,
    )

    class Keyword:
        def upsert_partitioned_document(self, document):
            calls.append("keyword")
            assert document["projection_version"] == p.ref.projection_version
            return "upserted"

        def delete_partitioned_document(self, **_kwargs):
            raise AssertionError("active result cannot delete")

        def refresh_partitioned_index(self):
            calls.append("refresh")

    class Rag:
        def sync_projection_with_fence(self, projection, *, collection, before_vector_write):
            calls.append("bounded-compute")
            before_vector_write()
            calls.append("vector")
            return RagSyncResult(
                collection=collection,
                operation=RagSyncOperation.UPSERT,
                chunk_count=len(projection.chunks),
            )

    return PreparedFilesCachedProjectionMaterializer(
        session_factory=lambda: Session(p.engine),
        settings=SimpleNamespace(),
        generation_pair=_root_spec(p).generation_pair,
        partition_metadata_version=p.header["partition_metadata_version"],
        keyword_client_factory=lambda _target: Keyword(),
        rag_service_factory=lambda _target: Rag(),
        retain_operation_id=lambda _event, _pair: p.header["operation_id"],
    )


def test_actual_root_materializer_completes_exact_jobs_and_acknowledged_history(
    file_effect_prepared,
):
    from miy_api.domains.retrieval.files_generation_runner import FilesGenerationPairSpec

    p = file_effect_prepared
    pair = _root_spec(p).generation_pair
    calls = []
    materializer = _materializer(p, calls)
    spec = FilesGenerationPairSpec(
        pair.generation_key,
        pair.keyword_physical_name,
        "synthetic-keyword-alias",
        pair.vector_physical_name,
        "synthetic-vector-alias",
    )
    result = materializer.materialize_batch(
        spec=spec, after_event_sequence=0, through_event_sequence=p.ref.event_sequence, limit=100
    )
    assert calls == ["bounded-compute", "keyword", "vector", "refresh"]
    assert result.keyword_succeeded == result.vector_succeeded == 1 and result.caught_up
    with p.world.connect(p.role) as conn:
        assert (
            conn.execute("SELECT state FROM core_file_materialization_operations").fetchone()[0]
            == "complete"
        )
        for table in ("search_index_jobs", "rag_sync_jobs"):
            assert conn.execute(
                sql.SQL("SELECT status,attempts FROM {} WHERE projection_event_sequence=%s").format(
                    sql.Identifier(table)
                ),
                (p.ref.event_sequence,),
            ).fetchone() == ("succeeded", 1)
    materializer.materialize_batch(
        spec=spec, after_event_sequence=0, through_event_sequence=p.ref.event_sequence, limit=100
    )
    assert calls == ["bounded-compute", "keyword", "vector", "refresh"]


def test_actual_empty_reconciliation_preserves_armed_without_source_or_live_jobs(
    file_effect_prepared,
):
    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        arm(conn, p)
        for table in ("search_index_jobs", "rag_sync_jobs"):
            conn.execute(sql.SQL("UPDATE {} SET status='failed'").format(sql.Identifier(table)))
    with p.c.source() as db:
        db.execute(
            text("UPDATE file_manager_files SET deleted_at=clock_timestamp() WHERE id=:id"),
            {"id": p.ref.resource_id},
        )
        db.commit()
    calls = []
    state = _materializer(p, calls).inspect_reconciliation(
        through_event_sequence=p.ref.event_sequence
    )
    assert (
        not state.caught_up and state.keyword_remaining == state.vector_remaining == 1 and not calls
    )
    with p.world.connect() as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "UPDATE retrieval_projection_generations SET state='validating' WHERE id=%s::uuid",
                    (p.keyword,),
                )
        assert caught.value.diag.message_primary == "file_materialization_effect_generation_armed"


@pytest.mark.parametrize("phase", ["arm", "complete"])
@pytest.mark.parametrize("after_commit", [False, True])
def test_real_commit_ack_loss_preserves_same_ids_and_grants_no_repeat(
    file_effect_prepared, phase, after_commit
):
    from miy_api.domains.retrieval.prepared_file_effects import (
        FileMaterializationEffectUnknown,
        FileMaterializationRefused,
        PreparedFileEffectRunner,
    )

    p = file_effect_prepared
    created = []

    class Fault(Session):
        def commit(self):
            target = 1 if phase == "arm" else 2
            if len(created) == target:
                if after_commit:
                    super().commit()
                raise RuntimeError("synthetic acknowledged commit uncertainty")
            return super().commit()

    def factory():
        db = Fault(p.engine)
        created.append(db)
        return db

    runner = PreparedFileEffectRunner(factory)
    calls = []
    if phase == "arm":
        with pytest.raises(FileMaterializationEffectUnknown) as caught:
            runner.arm(_root_spec(p))
    else:
        permit = runner.arm(_root_spec(p))

        def effect(_db, _materialization, fence):
            fence()
            calls.append("bounded-effect")
            fence()

        with pytest.raises(FileMaterializationEffectUnknown) as caught:
            runner.execute(permit, effect)
        with pytest.raises(FileMaterializationRefused, match="permit_consumed"):
            runner.execute(permit, effect)
        assert calls == ["bounded-effect"]
    receipt = caught.value.receipt
    assert receipt.spec == _root_spec(p) and receipt.provisional
    observed = runner.observe(_root_spec(p), expected_header_digest=receipt.header_digest)
    if phase == "arm" and not after_commit:
        assert observed is None
    else:
        expected = "complete" if phase == "complete" and after_commit else "armed"
        assert observed.historical and observed.state == expected and not observed.provisional
        assert runner.arm(_root_spec(p)).historical
    with p.world.connect(p.role) as conn:
        row = conn.execute(
            "SELECT operation_id,header_digest,state FROM core_file_materialization_operations"
        ).fetchone()
        if observed is None:
            assert row is None
        else:
            assert (
                str(row[0]) == p.header["operation_id"]
                and row[1] == receipt.header_digest
                and row[2] == observed.state
            )


def test_root_history_namespace_rejects_temp_false_complete(file_effect_prepared):
    from miy_api.domains.retrieval.prepared_file_effects import PreparedFileEffectRunner

    p = file_effect_prepared
    with p.world.connect(p.role) as conn:
        original = arm(conn, p)
    with p.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TEMP TABLE core_file_materialization_operations AS SELECT * FROM public.core_file_materialization_operations"
            )
        )
        connection.execute(
            text(
                "UPDATE pg_temp.core_file_materialization_operations SET state='complete',completed_at=clock_timestamp()"
            )
        )
        assert (
            connection.scalar(text("SELECT state FROM core_file_materialization_operations"))
            == "complete"
        )
    try:
        history = PreparedFileEffectRunner(lambda: Session(p.engine)).observe(
            _root_spec(p), expected_header_digest=original["header_digest"]
        )
        assert history.historical and history.state == "armed"
        with p.engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT state FROM public.core_file_materialization_operations")
                )
                == "armed"
            )
            assert (
                connection.scalar(
                    text("SELECT state FROM pg_temp.core_file_materialization_operations")
                )
                == "complete"
            )
    finally:
        with p.engine.begin() as connection:
            connection.execute(text("DROP TABLE pg_temp.core_file_materialization_operations"))


def test_private_owner_cannot_read_operation_header(file_effect_prepared):
    p = file_effect_prepared
    with p.world.connect() as conn:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(p.owner)))
        assert (
            conn.execute(
                "SELECT state,keyword_generation_id,vector_generation_id FROM public.core_file_materialization_operations"
            ).fetchall()
            == []
        )
        denied(conn, "SELECT header_digest FROM public.core_file_materialization_operations")
        denied(conn, "SELECT source_event_id FROM public.core_file_materialization_operations")


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_fresh_schema_roundtrip_without_history_or_grants(world):
    from alembic import command

    config = _migration_config(world.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, "file_source_partition_20261007")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_source_partition_20261007"
        )
        assert (
            conn.execute(
                "SELECT to_regclass('public.core_file_materialization_operations')"
            ).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
    command.upgrade(config, "head")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )


def test_empty_effect_schema_requires_exact_cap_grant_retirement(file_effect_prepared):
    from test_official_writer_roles import move

    p = file_effect_prepared
    config = _migration_config(p.world.engine.url.render_as_string(hide_password=False))
    module = ScriptDirectory.from_config(config).get_revision("file_effect_20261007").module
    move(
        p.world,
        p.c.roles.identity,
        "active",
        state="draining",
        artifact=p.c.roles.identity.artifact,
    )
    with pytest.raises(
        RuntimeError, match="file_materialization_effect_requires_explicit_retirement"
    ):
        with p.world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.downgrade()
    with p.world.connect() as conn:
        assert (
            conn.execute("SELECT count(*) FROM core_file_materialization_operations").fetchone()[0]
            == 0
        )
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (p.role, LOCK_FILE_MATERIALIZATION)
        ).fetchone()[0]


def test_extra_new_table_row_trigger_refuses_before_grant(file_effect_prepared):
    p = file_effect_prepared
    with p.world.connect() as conn:
        conn.execute(
            "CREATE FUNCTION public.synthetic_effect_late_row() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.source_payload_digest=repeat('b',64); RETURN NEW; END $$"
        )
        conn.execute(
            "CREATE TRIGGER zz_synthetic_effect_late_row BEFORE INSERT ON public.core_file_materialization_operations FOR EACH ROW EXECUTE FUNCTION public.synthetic_effect_late_row()"
        )
    role = p.world.role()
    before = snapshot(p.world, role)
    with pytest.raises(WriterControlError, match="file_materialization_effect_trigger_invalid"):
        prepare(p.c, role)
    assert snapshot(p.world, role) == before
