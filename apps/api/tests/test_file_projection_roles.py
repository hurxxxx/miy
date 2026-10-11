"""Actual restricted Files readers in owned PostgreSQL; no shared role grants."""

from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from test_official_writer_roles import (
    ACTIVE as ACTIVE,
    BASE as BASE,
    PASSWORD as PASSWORD,
    role_template as role_template,
    sa_dsn as sa_dsn,
    world as world,
)
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from miy_api.domains.auth.models import AuditLog
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.official_apps.file_projection_roles import (
    FILE_PROJECTION_READ_COLUMNS,
    FILE_PROJECTION_READ_TABLES,
    prepare_file_projection_reader,
)
from miy_api.domains.retrieval.models import RetrievalProjectionEvent, RetrievalProjectionHead
from miy_api.domains.retrieval.partitioning import ensure_default_partition
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef


def prepare(world, name):
    with Session(world.engine) as db:
        result = prepare_file_projection_reader(
            db,
            world.actor,
            role_name=name,
            expected=BASE,
            expected_state="active",
        )
        db.commit()
        return result


def reader_engine(world, name):
    from psycopg.conninfo import make_conninfo

    return create_engine(sa_dsn(make_conninfo(world.dsn, user=name, password=PASSWORD)))


def grants(world, name):
    with world.connect() as conn:
        return conn.execute(
            "SELECT c.relname,a.privilege_type,a.is_grantable,0::int AS column_number "
            "FROM pg_class c, LATERAL aclexplode(c.relacl) a "
            "WHERE a.grantee=(SELECT oid FROM pg_roles WHERE rolname=%s) "
            "UNION ALL SELECT c.relname,a.privilege_type,a.is_grantable,p.attnum "
            "FROM pg_attribute p JOIN pg_class c ON c.oid=p.attrelid, "
            "LATERAL aclexplode(p.attacl) a "
            "WHERE a.grantee=(SELECT oid FROM pg_roles WHERE rolname=%s) "
            "ORDER BY 1,2,3,4",
            (name, name),
        ).fetchall()


def audit_count(world):
    with Session(world.engine) as db:
        return db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "official_projection.file_reader.prepare")
        )


def seed(world, *, external):
    identifier = str(uuid4())
    checksum = sha256(b"synthetic immutable source bytes").hexdigest()
    with Session(world.engine) as db:
        partition = ensure_default_partition(
            db, source_namespace="files", candidate_scope_kind="company"
        )
        corpus = None
        if external:
            corpus = FileManagerCorpus(
                id=str(uuid4()),
                name="Synthetic corpus",
                access_scope_kind="company",
                retrieval_partition_id=str(partition.id),
                created_by_id=world.user_id,
            )
            db.add(corpus)
            db.flush()
        file = FileManagerFile(
            id=identifier,
            owner_id=world.user_id,
            filename="Synthetic bounded file.txt",
            content_type="text/plain",
            size_bytes=32,
            storage_key="synthetic-internal-object/" + identifier,
            visibility="private",
            corpus_id=corpus.id if corpus else None,
            retrieval_partition_id=str(partition.id),
            extraction_status="ready",
            extraction_content_checksum=checksum,
            extraction_text="Synthetic canonical extracted text.",
            extraction_blocks=[
                EvidenceBlock(
                    document_id=identifier,
                    block_id=identifier + ":1",
                    locator_kind="paragraph",
                    locator_label="Paragraph 1",
                    section_path="Synthetic",
                    block_kind="paragraph",
                    text="Synthetic canonical extracted text.",
                ).to_dict()
            ],
            extraction_metadata={"parser_version": "files-retrieval-v2"},
        )
        db.add(file)
        db.flush()
        if external:
            db.add(
                FileManagerFileSourceMetadata(
                    file_id=identifier,
                    corpus_id=corpus.id,
                    external_id="synthetic-private-external-id",
                    external_id_sha256="a" * 64,
                    source_kind="synthetic_external",
                    source_id="synthetic-private-source-id",
                    source_id_sha256="b" * 64,
                    source_uri="https://private.invalid/synthetic",
                    source_version="synthetic-version",
                    title="Synthetic searchable title",
                    author="Synthetic author",
                    content_checksum=checksum,
                    raw_metadata={"synthetic_private": "not a projected field"},
                )
            )
        event = RetrievalProjectionEvent(
            resource_type="file_manager_file",
            resource_id=identifier,
            projection_version=1,
            retrieval_partition_id=str(partition.id),
            change_kind="content",
            desired_state="active",
            content_checksum=checksum,
        )
        db.add_all(
            [
                event,
                RetrievalProjectionHead(
                    resource_type=event.resource_type,
                    resource_id=identifier,
                    projection_version=1,
                    retrieval_partition_id=str(partition.id),
                    desired_state="active",
                    content_checksum=checksum,
                ),
            ]
        )
        db.flush()
        ref = ProjectionEventRef(
            event_sequence=event.event_sequence,
            resource_type=event.resource_type,
            resource_id=identifier,
            projection_version=1,
            retrieval_partition_id=str(partition.id),
            change_kind="content",
            desired_state="active",
            content_checksum=checksum,
            visibility_checksum=None,
        )
        db.commit()
    return SimpleNamespace(file_id=identifier, checksum=checksum, event=ref)


def test_actual_reader_constructs_projection_with_column_only_closure(world):
    from miy_api.domains.files.core_projection import (
        load_ready_file_rag_projection,
        prepared_core_file_projection,
    )

    external = True
    context = seed(world, external=external)
    name = world.role()
    prepare(world, name)
    engine = reader_engine(world, name)
    try:
        with Session(engine) as db:
            with prepared_core_file_projection(db, projection_event=context.event):
                projection = load_ready_file_rag_projection(db, file_id=context.file_id)
            assert projection.resource_id == context.file_id
            assert projection.metadata["content_checksum"] == context.checksum
            assert projection.owner_label == "Role fixture"
            if external:
                assert projection.title == "Synthetic searchable title"
                assert projection.metadata["author"] == "Synthetic author"
                assert "source_uri" not in projection.metadata
                assert "raw_metadata" not in projection.metadata
            assert not db.new and not db.dirty and not db.deleted
    finally:
        engine.dispose()
    with world.connect(name) as conn:
        for table in FILE_PROJECTION_READ_TABLES:
            assert conn.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT')", (table,)
            ).fetchone()[0]
        for table, columns in FILE_PROJECTION_READ_COLUMNS.items():
            assert not conn.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT')", (table,)
            ).fetchone()[0]
            for column in columns:
                assert conn.execute(
                    "SELECT has_column_privilege(current_user,%s,%s,'SELECT')", (table, column)
                ).fetchone()[0]
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            conn.execute("SELECT password_hash FROM users")
        assert caught.value.sqlstate == "42501"
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            conn.execute(
                "UPDATE file_manager_files SET extraction_status=extraction_status WHERE false"
            )
        assert caught.value.sqlstate == "42501"
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            conn.execute("SELECT id FROM file_manager_files FOR SHARE")
        assert caught.value.sqlstate == "42501"
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            conn.execute(
                "SELECT public.miy_lock_official_projection_partition(gen_random_uuid(),'docs')"
            )
        assert caught.value.sqlstate == "42501"
