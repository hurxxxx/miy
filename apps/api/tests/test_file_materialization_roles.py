"""Actual strict Files accepted-output reader privileges on owned PostgreSQL."""

from dataclasses import fields
from datetime import timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import world as world, role_template as role_template, denied
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import file_core_prepared as file_core_prepared, snapshot
from test_file_projection_roles import reader_engine
from test_prepared_files_ingress import (
    c as c,
    publications as publications,
    events,
    extract,
    consume,
    append,
)

from miy_api.domains.files.artifact_contract import FileArtifactInvalid, FileArtifactNotReady
from miy_api.domains.files.core_projection import prepared_core_file_projection
from miy_api.domains.files.materialization_source import (
    load_prepared_file_materialization,
    require_unchanged_file_materialization,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.official_apps.file_materialization_roles import (
    FILE_MATERIALIZATION_READ_COLUMNS,
    prepare_file_materialization_reader,
)
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.retrieval.models import RetrievalProjectionEvent
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef


def prepare(c, role, *, commit=True):
    with Session(c.world.engine) as db:
        result = prepare_file_materialization_reader(
            db,
            c.world.actor,
            role_name=role,
            expected=c.roles.identity,
            expected_state="active",
        )
        if commit:
            db.commit()
        else:
            db.rollback()
        return result


@pytest.fixture
def strict(c):
    role = c.world.role()
    assert prepare(c, role).profile_prepared
    engine = reader_engine(c.world, role)
    try:
        yield SimpleNamespace(c=c, role=role, engine=engine)
    finally:
        engine.dispose()


def accepted(c, outcome="ready"):
    extract(c, outcome)
    receipts = [consume(c, source) for source in events(c)]
    receipt = receipts[-1]
    with Session(c.world.engine) as db:
        row = db.get(RetrievalProjectionEvent, receipt.core_event_sequence)
        return ProjectionEventRef(
            **{f.name: getattr(row, f.name) for f in fields(ProjectionEventRef)}
        )


def read(strict, ref):
    with Session(strict.engine) as db:
        with prepared_core_file_projection(db, projection_event=ref):
            result = load_prepared_file_materialization(db, projection_event=ref)
            assert (
                require_unchanged_file_materialization(db, materialization=result) == result.witness
            )
            return result


@pytest.mark.parametrize("external", [False, True])
def test_actual_strict_pair_from_genuine_source_result_and_core_acceptance(strict, external):
    c = strict.c
    if external:
        with c.source() as db:
            corpus = FileManagerCorpus(
                id=str(uuid4()),
                name="Synthetic safe corpus",
                created_by_id=c.world.user_id,
                access_scope_kind="company",
                retrieval_partition_id=c.roles.partition,
                source_managed=True,
                authorization_mode="explicit_grants",
            )
            db.add(corpus)
            db.flush()
            file = db.get(FileManagerFile, c.spec.file_id)
            file.corpus_id = corpus.id
            db.add(
                FileManagerFileSourceMetadata(
                    file_id=file.id,
                    corpus_id=corpus.id,
                    external_id="synthetic-external",
                    external_id_sha256="a" * 64,
                    source_kind="synthetic",
                    source_id="synthetic-source",
                    source_id_sha256="b" * 64,
                    content_checksum=sha256(b"Synthetic text").hexdigest(),
                    acl_resolved=True,
                    title="Safe title",
                    author="Safe author",
                )
            )
            db.commit()
        c.spec = c.spec.model_copy(
            update={
                "expected_input": c.runner.capture(
                    actor_user_id=c.spec.actor_user_id,
                    execution_ref=c.spec.execution_ref,
                    file_id=c.spec.file_id,
                )
            }
        )
    ref = accepted(c)
    reads_before = list(c.reads)
    result = read(strict, ref)
    assert result.keyword_document["body"] == result.rag_projection.text_content
    assert (
        result.keyword_document["metadata"]["extracted_at"]
        == result.rag_projection.metadata["extracted_at"]
    )
    assert (
        result.keyword_document["retrieval_partition_id"]
        == result.rag_projection.retrieval_partition_id
        == ref.retrieval_partition_id
    )
    assert (
        result.keyword_document["projection_version"]
        == result.rag_projection.projection_version
        == ref.projection_version
    )
    assert result.witness.source_event_id == events(c)[-1].event_id
    assert c.reads == reads_before and c.publications == []


def test_actual_read_profile_has_no_private_or_mutation_capability(strict):
    with strict.c.world.connect(strict.role) as conn:
        for table, columns in FILE_MATERIALIZATION_READ_COLUMNS.items():
            conn.execute(f"SELECT {','.join(columns)} FROM public.{table} LIMIT 0")
        for query in (
            "SELECT * FROM file_manager_files",
            "SELECT storage_key FROM file_manager_files",
            "SELECT extraction_error_code FROM file_manager_files",
            "SELECT writer_scope FROM file_manager_files",
            "SELECT source_uri FROM file_manager_file_source_metadata",
            "SELECT source_id FROM file_manager_file_source_metadata",
            "SELECT raw_metadata FROM file_manager_file_source_metadata",
            "SELECT password_hash FROM users",
            "SELECT token_hash FROM auth_sessions",
            "SELECT id FROM auth_sessions",
            "SELECT generation FROM official_writer_principals",
            "SELECT artifact FROM official_writer_principals",
            "SELECT request_id FROM file_extraction_requests",
            "SELECT id FROM retrieval_partitions",
            "SELECT id FROM rag_sync_jobs",
            "SELECT payload FROM official_projection_outbox",
            "SELECT * FROM retrieval_projection_events",
            "SELECT id FROM file_manager_files FOR SHARE",
            "SELECT id FROM file_manager_corpora FOR SHARE",
            "SELECT file_id FROM file_manager_file_source_metadata FOR SHARE",
            "SELECT event_id FROM official_projection_outbox FOR SHARE",
            "SELECT event_id FROM official_projection_receipts FOR SHARE",
            "SELECT resource_id FROM retrieval_projection_heads FOR SHARE",
            "UPDATE file_manager_files SET filename=filename WHERE false",
            "DELETE FROM file_manager_files WHERE false",
            "INSERT INTO file_manager_files(id) SELECT id FROM file_manager_files WHERE false",
            "TRUNCATE file_manager_files",
            "UPDATE retrieval_projection_heads SET desired_state=desired_state WHERE false",
            "SELECT public.miy_lock_file_projection_partition(NULL)",
            "SELECT public.miy_read_file_source_partition(NULL,NULL)",
            "SELECT public.miy_file_extraction_admit(NULL)",
            "SELECT nextval('retrieval_projection_events_event_sequence_seq')",
        ):
            denied(conn, query)
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                with conn.cursor().copy("COPY file_manager_files(id) FROM STDIN"):
                    pass
        assert error.value.sqlstate == "42501"


@pytest.mark.parametrize("mode", ["replay", "rollback", "partial"])
def test_preparation_exact_replay_and_transaction_ownership(strict, mode):
    c = strict.c
    role = strict.role if mode == "replay" else c.world.role()
    if mode == "partial":
        with c.world.connect() as conn:
            conn.execute(
                sql.SQL("GRANT SELECT(id) ON file_manager_files TO {}").format(sql.Identifier(role))
            )
    before = snapshot(c.world, role)
    if mode == "partial":
        with pytest.raises(WriterControlError, match="existing_profile"):
            prepare(c, role)
    else:
        assert prepare(c, role, commit=mode != "rollback").profile_prepared
    assert snapshot(c.world, role) == before


@pytest.mark.parametrize("kind", ["f1_reader", "f3_staging"])
def test_old_exact_profiles_are_not_upgraded(c, kind):
    if kind == "f3_staging":
        role = c.roles.core
    else:
        from miy_api.domains.official_apps.file_projection_roles import (
            prepare_file_projection_reader,
        )

        role = c.world.role()
        with Session(c.world.engine) as db:
            prepare_file_projection_reader(
                db,
                c.world.actor,
                role_name=role,
                expected=c.roles.identity,
                expected_state="active",
            )
            db.commit()
    before = snapshot(c.world, role)
    result = prepare(c, role)
    assert not result.profile_prepared
    assert snapshot(c.world, role) == before


@pytest.mark.parametrize(
    "extra",
    [
        "file_private",
        "principal_private",
        "full_file",
        "source_update",
        "core_update",
        "credential",
        "source_request",
        "partition",
        "grant_option",
        "public_column",
        "definer",
        "invoker_capability",
        "membership",
        "schema_create",
        "sequence",
        "unsafe_attribute",
    ],
)
def test_unreviewed_effective_privilege_refuses_before_grant_or_audit(c, extra):
    role = c.world.role()
    target = sql.Identifier(role)
    commands = {
        "file_private": "GRANT SELECT(storage_key) ON file_manager_files TO {}",
        "principal_private": "GRANT SELECT(generation) ON official_writer_principals TO {}",
        "full_file": "GRANT SELECT ON file_manager_files TO {}",
        "source_update": "GRANT UPDATE(filename) ON file_manager_files TO {}",
        "core_update": "GRANT UPDATE ON retrieval_projection_heads TO {}",
        "credential": "GRANT SELECT(password_hash) ON users TO {}",
        "source_request": "GRANT SELECT(request_id) ON file_extraction_requests TO {}",
        "partition": "GRANT SELECT(id) ON retrieval_partitions TO {}",
        "grant_option": "GRANT SELECT(id) ON file_manager_files TO {} WITH GRANT OPTION",
        "public_column": "GRANT SELECT(id) ON file_manager_files TO PUBLIC",
        "definer": "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_admit(uuid) TO {}",
        "invoker_capability": "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_result_digest(uuid,text) TO {}",
        "schema_create": "GRANT CREATE ON SCHEMA public TO {}",
        "sequence": "GRANT USAGE ON SEQUENCE retrieval_projection_events_event_sequence_seq TO {}",
        "unsafe_attribute": "ALTER ROLE {} BYPASSRLS",
    }
    with c.world.connect() as conn:
        if extra == "membership":
            parent = c.world.role(login=False)
            conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(parent), target))
        else:
            template = commands[extra]
            conn.execute(sql.SQL(template).format(target))
    before = snapshot(c.world, role)
    with pytest.raises(WriterControlError):
        prepare(c, role)
    assert snapshot(c.world, role) == before


@pytest.mark.parametrize("mode", ["source_oid", "renamed_source_oid", "retained_source_name"])
def test_actual_source_identity_never_becomes_core_with_injected_read_grants(strict, mode):
    c = strict.c
    role = c.roles.source
    if mode != "source_oid":
        renamed = c.world.role()
        with c.world.connect() as conn:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(renamed)))
            conn.execute(
                sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                    sql.Identifier(role), sql.Identifier(renamed)
                )
            )
        c.world.roles.remove(role)
        if mode == "renamed_source_oid":
            role = renamed
        else:
            from test_official_writer_roles import PASSWORD

            with c.world.connect() as conn:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(PASSWORD))
                )
            c.world.roles.append(role)
    with c.world.connect() as conn:
        for table, columns in FILE_MATERIALIZATION_READ_COLUMNS.items():
            conn.execute(
                sql.SQL("GRANT SELECT ({}) ON {} TO {}").format(
                    sql.SQL(",".join(columns)), sql.Identifier(table), sql.Identifier(role)
                )
            )
    engine = reader_engine(c.world, role)
    try:
        with Session(engine) as db:
            with pytest.raises(FileArtifactInvalid) as error:
                from miy_api.domains.files.materialization_source import _require_core_identity

                _require_core_identity(db)
            assert error.value.reason == "materialization_core_identity_forbidden"
    finally:
        engine.dispose()
    before = snapshot(c.world, role)
    with pytest.raises(WriterControlError, match="source_identity"):
        prepare(c, role)
    assert snapshot(c.world, role) == before


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_actual_non_read_committed_refuses_before_source_content(strict, isolation):
    ref = accepted(strict.c)
    engine = strict.engine.execution_options(isolation_level=isolation)
    statements = []

    def seen(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", seen)
    try:
        with Session(engine) as db:
            with prepared_core_file_projection(db, projection_event=ref):
                with pytest.raises(FileArtifactInvalid) as error:
                    load_prepared_file_materialization(db, projection_event=ref)
                assert error.value.reason == "materialization_requires_read_committed"
        assert not any("file_manager_files" in statement for statement in statements)
    finally:
        event.remove(engine, "before_cursor_execute", seen)


@pytest.mark.parametrize("outcome", ["failed", "ocr_required", "unsupported"])
def test_actual_pending_controls_and_genuine_delete_are_distinct(strict, outcome):
    ref = accepted(strict.c, outcome)
    if outcome == "unsupported":
        result = read(strict, ref)
        assert result.keyword_document is None and result.rag_projection is None
        assert ref.desired_state == "deleted"
    else:
        with pytest.raises(FileArtifactNotReady):
            read(strict, ref)
        assert ref.desired_state == "active" and ref.content_checksum is None


def test_unaccepted_same_input_sha_new_source_result_holds_until_exact_acceptance(strict):
    c = strict.c
    ref = accepted(c)
    old = read(strict, ref)
    with c.source() as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        file.extracted_at += timedelta(microseconds=1)
        db.commit()
    newer = append(c, checksum=ref.content_checksum)
    with pytest.raises(FileArtifactNotReady) as error:
        read(strict, ref)
    assert error.value.reason == "source_tip_unaccepted"
    consumed = consume(c, newer)
    with Session(c.world.engine) as db:
        row = db.get(RetrievalProjectionEvent, consumed.core_event_sequence)
        new_ref = ProjectionEventRef(
            **{f.name: getattr(row, f.name) for f in fields(ProjectionEventRef)}
        )
    new = read(strict, new_ref)
    assert new.witness.source_event_id == newer.event_id
    assert new.source_identity.extracted_at != old.source_identity.extracted_at
    assert c.publications == []


def test_actual_temp_file_shadow_cannot_replace_genuine_accepted_output(strict):
    from miy_api.domains.files.artifact_contract import validate_file_extraction_artifact

    c = strict.c
    ref = accepted(c)
    with Session(strict.engine) as db:
        original_search_path = db.scalar(text("SELECT pg_catalog.current_setting('search_path')"))
        public_before = tuple(
            db.execute(
                text("""
            SELECT extraction_text,extraction_blocks,extraction_metadata,
                extraction_content_checksum,extracted_at
            FROM public.file_manager_files WHERE id=:id
        """),
                {"id": c.spec.file_id},
            ).one()
        )
        columns = ",".join(FILE_MATERIALIZATION_READ_COLUMNS["file_manager_files"])
        db.execute(
            text(
                f"CREATE TEMP TABLE file_manager_files ON COMMIT DROP AS SELECT {columns} FROM public.file_manager_files"
            )
        )
        forged = "FORGED temporary output with the genuine input SHA and result stamp"
        blocks = json.loads(json.dumps(public_before[1]))
        for block in blocks:
            block["text"] = forged
        validate_file_extraction_artifact(
            file_id=c.spec.file_id,
            content_checksum=public_before[3],
            text=forged,
            blocks=blocks,
            metadata={},
        )
        db.execute(
            text("""
            UPDATE pg_temp.file_manager_files SET extraction_text=:text,
                extraction_blocks=CAST(:blocks AS jsonb),extraction_metadata='{}'::jsonb
            WHERE id=:id
        """),
            {"text": forged, "blocks": json.dumps(blocks), "id": c.spec.file_id},
        )
        assert db.scalar(
            text(
                "SELECT pg_catalog.to_regclass('file_manager_files')<>pg_catalog.to_regclass('public.file_manager_files')"
            )
        )
        with prepared_core_file_projection(db, projection_event=ref):
            result = load_prepared_file_materialization(db, projection_event=ref)
        public_after = tuple(
            db.execute(
                text("""
            SELECT extraction_text,extraction_blocks,extraction_metadata,
                extraction_content_checksum,extracted_at
            FROM public.file_manager_files WHERE id=:id
        """),
                {"id": c.spec.file_id},
            ).one()
        )
        assert public_after == public_before
        assert (
            result.keyword_document["body"]
            == result.rag_projection.text_content
            == public_before[0]
        )
        assert "FORGED" not in result.keyword_document["body"]
        assert (
            db.scalar(text("SELECT pg_catalog.current_setting('search_path')"))
            == "pg_catalog, public, pg_temp"
        )
        db.commit()
        assert (
            db.scalar(text("SELECT pg_catalog.current_setting('search_path')"))
            == original_search_path
        )
    assert c.publications == []
