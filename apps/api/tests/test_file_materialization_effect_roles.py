"""Fixed Files effect identities and lifecycle on owned restricted PostgreSQL."""

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
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from test_alembic_migrations import _migration_config as _migration_config
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_materialization_roles import accepted as accepted
from test_file_projection_core_roles import (
    file_core_prepared as file_core_prepared,
    snapshot as snapshot,
)
from test_file_projection_roles import reader_engine as reader_engine
from test_file_source_partition_roles import wait_for_exact_blocker as wait_for_exact_blocker
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied as denied,
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
    before = snapshot(p.world, p.role)
    assert prepare(p.c, p.role, commit=True).profile_prepared
    assert snapshot(p.world, p.role) == before
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


@pytest.mark.parametrize("nested", [False])
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


def test_new_preparation_rollback_leaves_no_profile(file_effect_prepared):
    p = file_effect_prepared
    role = p.world.role()
    before = snapshot(p.world, role)
    assert prepare(p.c, role, commit=False).profile_prepared
    assert snapshot(p.world, role) == before


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


@pytest.mark.parametrize("phase,after_commit", [("arm", True), ("complete", True)])
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
