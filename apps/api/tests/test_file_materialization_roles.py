"""Actual strict Files accepted-output reader privileges on owned PostgreSQL."""

from dataclasses import fields
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.orm import Session

from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    world as world,
    role_template as role_template,
    denied as denied,
)
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import (
    file_core_prepared as file_core_prepared,
    snapshot as snapshot,
)
from test_file_projection_roles import reader_engine as reader_engine
from test_prepared_files_ingress import (
    c as c,
    publications as publications,
    events as events,
    extract as extract,
    consume as consume,
    append as append,
)

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


def test_actual_strict_pair_from_genuine_source_result_and_core_acceptance(strict):
    external = True
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
