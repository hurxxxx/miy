"""Actual restricted Files readers in owned PostgreSQL; no shared role grants."""

from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from test_official_writer_roles import (
    ACTIVE,
    BASE,
    PASSWORD,
    role_template as role_template,
    sa_dsn,
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
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import prepare_principal
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


@pytest.mark.parametrize("external", [False, True])
def test_actual_reader_constructs_projection_with_column_only_closure(world, external):
    from miy_api.domains.files.core_projection import (
        load_ready_file_rag_projection,
        prepared_core_file_projection,
    )

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


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE file_manager_files SET extraction_status='failed' WHERE false",
        "INSERT INTO file_manager_files(id) SELECT 'synthetic' WHERE false",
        "DELETE FROM file_manager_files WHERE false",
        "SELECT id FROM file_manager_files FOR SHARE",
        "SELECT id FROM file_manager_corpora FOR SHARE",
        "SELECT password_hash FROM users",
        "SELECT email FROM users",
        "SELECT login_id FROM users",
        "SELECT status FROM users",
        "SELECT source_uri FROM file_manager_file_source_metadata",
        "SELECT raw_metadata FROM file_manager_file_source_metadata",
        "SELECT external_id FROM file_manager_file_source_metadata",
        "SELECT source_id FROM file_manager_file_source_metadata",
        "SELECT * FROM retrieval_partitions",
        "SELECT * FROM auth_sessions",
        "SELECT * FROM audit_logs",
        "SELECT * FROM official_runtime_ownership",
        "UPDATE retrieval_projection_heads SET projection_version=projection_version WHERE false",
        "INSERT INTO search_index_jobs(id) SELECT 'synthetic' WHERE false",
        "SELECT public.miy_read_official_company_partition('docs',NULL)",
        "SELECT public.miy_lock_official_projection_partition(gen_random_uuid(),'docs')",
    ],
)
def test_actual_reader_denies_source_dml_locks_credentials_and_core_authority(world, statement):
    name = world.role()
    prepare(world, name)
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            conn.execute(statement)
        assert caught.value.sqlstate == "42501"


def test_actual_reader_cannot_copy_source(world):
    name = world.role()
    prepare(world, name)
    with world.connect(name) as conn:
        with pytest.raises(Exception) as caught:
            with conn.cursor().copy("COPY file_manager_files (id) FROM STDIN"):
                pass
        assert caught.value.sqlstate == "42501"


def test_reader_exact_replay_does_not_grant_or_audit(world):
    name = world.role()
    first = prepare(world, name)
    before = grants(world, name), audit_count(world)
    assert prepare(world, name) == first
    assert (grants(world, name), audit_count(world)) == before


@pytest.mark.parametrize(
    "hazard",
    [
        "credential_column",
        "private_metadata",
        "source_update_column",
        "partial_profile",
        "public_table",
        "public_column",
        "membership",
        "grant_option",
        "sequence",
        "definer",
        "create",
        "attributes",
    ],
)
def test_reader_preparation_refuses_ambient_or_partial_profile_without_expansion(world, hazard):
    name = world.role()
    with world.connect() as conn:
        commands = {
            "credential_column": sql.SQL("GRANT SELECT(password_hash) ON users TO {}"),
            "private_metadata": sql.SQL(
                "GRANT SELECT(raw_metadata) ON file_manager_file_source_metadata TO {}"
            ),
            "source_update_column": sql.SQL(
                "GRANT UPDATE(extraction_status) ON file_manager_files TO {}"
            ),
            "partial_profile": sql.SQL("GRANT SELECT ON file_manager_files TO {}"),
            "grant_option": sql.SQL("GRANT SELECT(id) ON users TO {} WITH GRANT OPTION"),
            "sequence": sql.SQL(
                "GRANT USAGE ON SEQUENCE retrieval_projection_events_event_sequence_seq TO {}"
            ),
            "create": sql.SQL("GRANT CREATE ON SCHEMA public TO {}"),
            "attributes": sql.SQL("ALTER ROLE {} INHERIT"),
        }
        if hazard in commands:
            conn.execute(commands[hazard].format(sql.Identifier(name)))
        elif hazard == "public_table":
            conn.execute("GRANT SELECT ON retrieval_projection_heads TO PUBLIC")
        elif hazard == "public_column":
            conn.execute("GRANT SELECT(id) ON users TO PUBLIC")
        elif hazard == "membership":
            group = world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(name))
            )
        else:
            conn.execute(
                "CREATE FUNCTION public.synthetic_reader_definer() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
            )
            conn.execute("REVOKE ALL ON FUNCTION public.synthetic_reader_definer() FROM PUBLIC")
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION public.synthetic_reader_definer() TO {}").format(
                    sql.Identifier(name)
                )
            )
    before = grants(world, name), audit_count(world)
    with pytest.raises(WriterControlError):
        prepare(world, name)
    assert (grants(world, name), audit_count(world)) == before


def test_existing_source_principal_is_never_expanded_into_reader(world):
    name = world.role()
    with Session(world.engine) as db:
        prepare_principal(
            db, world.actor, role_name=name, identity=ACTIVE, expected=BASE, expected_state="active"
        )
        db.commit()
    before = grants(world, name), audit_count(world)
    with pytest.raises(WriterControlError, match="source_identity_forbidden"):
        prepare(world, name)
    assert (grants(world, name), audit_count(world)) == before


def test_wrong_expected_ownership_grants_nothing(world):
    name = world.role()
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="compare_and_swap_conflict"):
            prepare_file_projection_reader(
                db, world.actor, role_name=name, expected=ACTIVE, expected_state="active"
            )
        db.rollback()
    assert grants(world, name) == []
    assert audit_count(world) == 0


def test_current_admin_revocation_refuses_preparation(world):
    name = world.role()
    with Session(world.engine) as db:
        db.execute(
            text("DELETE FROM user_system_roles WHERE user_id=:user"), {"user": world.user_id}
        )
        db.commit()
    with pytest.raises(WriterControlError, match="writer_admin_required"):
        prepare(world, name)
    assert grants(world, name) == []
    assert audit_count(world) == 0
