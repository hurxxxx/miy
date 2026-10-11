"""Fresh strict Files materialization SELECT profile, without effect authority."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.file_extraction_roles import (
    _create_forbidden,
    _public_relations_forbidden,
    _relations,
    file_extraction_guard_contract,
)
from miy_api.domains.official_apps.file_projection_core_roles import _column_flags
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_roles import (
    ROLE_GUARD,
    _guard_contract,
    _identifier,
    _lock,
    _role,
    _sequence_privileges,
    _source_guard,
    _table_privilege_forbidden,
)

FILE_MATERIALIZATION_READ_COLUMNS = {
    "file_manager_files": (
        "id",
        "owner_id",
        "filename",
        "folder_id",
        "corpus_id",
        "content_type",
        "size_bytes",
        "visibility",
        "updated_at",
        "retrieval_partition_id",
        "deleted_at",
        "extraction_status",
        "extraction_content_checksum",
        "extraction_text",
        "extraction_blocks",
        "extraction_metadata",
        "extracted_at",
    ),
    "users": ("id", "display_name", "full_name"),
    "file_manager_corpora": ("id", "access_scope_kind", "retrieval_partition_id"),
    "file_manager_file_source_metadata": (
        "file_id",
        "corpus_id",
        "source_kind",
        "title",
        "author",
        "authored_at",
        "department",
        "document_type",
        "source_updated_at",
        "content_checksum",
    ),
    "official_projection_outbox": (
        "event_id",
        "resource_type",
        "resource_id",
        "source_revision",
        "payload_digest",
    ),
    "official_projection_receipts": (
        "event_id",
        "resource_type",
        "resource_id",
        "source_revision",
        "payload_digest",
        "status",
        "core_event_sequence",
    ),
    "retrieval_projection_events": (
        "event_sequence",
        "resource_type",
        "resource_id",
        "projection_version",
        "retrieval_partition_id",
        "change_kind",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    ),
    "retrieval_projection_heads": (
        "resource_type",
        "resource_id",
        "projection_version",
        "retrieval_partition_id",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    ),
    "official_writer_principals": ("role_oid", "role_name"),
}
_ALL = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


@dataclass(frozen=True)
class FileMaterializationReaderPreparation:
    role_oid: int
    role_name: str
    profile_prepared: bool


def _read_profile(db: Session, name: str) -> tuple[bool, ...]:
    _create_forbidden(db, name)
    flags = []
    for schema, table, oid in _relations(db):
        columns = FILE_MATERIALIZATION_READ_COLUMNS.get(table, ()) if schema == "public" else ()
        forbidden = ",".join(p for p in _ALL if p != "SELECT" or not columns)
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("file_materialization_reader_privilege_forbidden")
        _public_relations_forbidden(db, oid)
        if columns:
            flags.extend(_column_flags(db, name, oid, columns, "SELECT"))
    _function_grants(db, name)
    _sequence_privileges(db, name)
    if len(flags) != sum(map(len, FILE_MATERIALIZATION_READ_COLUMNS.values())):
        raise WriterControlError("file_materialization_reader_schema_invalid")
    return tuple(flags)


def _function_grants(db: Session, name: str, *, permitted: tuple[str, ...] = ()) -> None:
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
          JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
              OR (p.prosecdef AND p.oid<>ALL(CAST(:permitted AS regprocedure[]))
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
              OR pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')
              OR (p.oid<>ALL(CAST(:permitted AS regprocedure[])) AND EXISTS(
                SELECT 1 FROM pg_catalog.aclexplode(p.proacl) a
                WHERE a.grantee=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
                  AND a.privilege_type='EXECUTE'))))
        """),
        {"name": name, "permitted": list(permitted)},
    ):
        raise WriterControlError("file_materialization_reader_function_forbidden")


def _old_exact_profile(db: Session, name: str) -> bool:
    """Recognize complete previously reviewed roles without adding grants."""
    from miy_api.domains.official_apps.file_projection_roles import _read_profile as old_reader
    from miy_api.domains.official_apps.file_projection_core_roles import (
        LOCK_FILE_PARTITION,
        _profile as old_core,
        file_projection_partition_contract,
    )

    if db.scalar(
        text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
        {"name": name, "cap": LOCK_FILE_PARTITION},
    ):
        _function_grants(db, name, permitted=(LOCK_FILE_PARTITION,))
        file_projection_partition_contract(db)
        if not all(old_core(db, name)):
            raise WriterControlError("file_materialization_reader_old_profile_incomplete")
        return True
    if db.scalar(
        text("SELECT pg_catalog.has_table_privilege(:name,'public.file_manager_files','SELECT')"),
        {"name": name},
    ):
        _function_grants(db, name)
        if not all(old_reader(db, name)):
            raise WriterControlError("file_materialization_reader_old_profile_incomplete")
        return True
    return False


def prepare_file_materialization_reader(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> FileMaterializationReaderPreparation:
    """Prepare a supplied fresh role; caller owns grants/audit and COMMIT."""
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        if db.scalar(
            text("""
            SELECT EXISTS(SELECT 1 FROM public.official_writer_principals
              WHERE role_oid=:oid OR role_name=:name)
            """),
            {"oid": oid, "name": role_name},
        ):
            raise WriterControlError("file_materialization_reader_source_identity_forbidden")
        if _source_guard(db) != ROLE_GUARD:
            raise WriterControlError("file_materialization_reader_requires_role_guard")
        _guard_contract(db)
        file_extraction_guard_contract(db)
        if _old_exact_profile(db, role_name):
            return FileMaterializationReaderPreparation(oid, role_name, False)
        flags = _read_profile(db, role_name)
        if all(flags):
            return FileMaterializationReaderPreparation(oid, role_name, True)
        if any(flags):
            raise WriterControlError("file_materialization_reader_existing_profile_forbidden")
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table, columns in FILE_MATERIALIZATION_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            if not all(_read_profile(db, role_name)):
                raise WriterControlError("file_materialization_reader_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_materialization_reader.prepare",
                entity_kind="official_projection_file_materialization_reader",
                entity_id=str(oid),
                summary="Strict read-only accepted Files output reader prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return FileMaterializationReaderPreparation(oid, role_name, True)
