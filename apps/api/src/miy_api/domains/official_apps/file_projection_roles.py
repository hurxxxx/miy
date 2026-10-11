"""Explicit fresh Files artifact reader; no worker or Source authority.

The supplied safe LOGIN reads canonical Files artifacts and actual Core event/head
witnesses. Public owner labels and safe external metadata are column grants; no
user credentials, provider/audit, partition, Source DML or row locks are allowed.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin

FILE_PROJECTION_READ_TABLES = (
    "file_manager_files",
    "retrieval_projection_events",
    "retrieval_projection_heads",
)
FILE_PROJECTION_READ_COLUMNS = {
    "file_manager_corpora": ("id", "access_scope_kind"),
    "users": ("id", "display_name", "full_name"),
    "file_manager_file_source_metadata": (
        "file_id",
        "source_kind",
        "title",
        "author",
        "authored_at",
        "department",
        "document_type",
        "source_updated_at",
        "content_checksum",
    ),
}


def _read_profile(db: Session, role_name: str) -> tuple[bool, ...]:
    """Reject effective expansion, including column/PUBLIC/grant-option paths."""
    from miy_api.domains.official_apps.writer_roles import (
        _sequence_privileges,
        _table_privilege_forbidden,
    )

    if db.scalar(
        text("""
        SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE')
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace
            WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'
            AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))
        """),
        {"name": role_name},
    ):
        raise WriterControlError("file_projection_reader_create_forbidden")
    flags = []
    for schema, table, oid in db.execute(
        text("""
        SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND c.relkind IN ('r','p','v','m','f')
        ORDER BY n.nspname,c.relname
        """)
    ):
        full_read = schema == "public" and table in FILE_PROJECTION_READ_TABLES
        columns = FILE_PROJECTION_READ_COLUMNS.get(table, ()) if schema == "public" else ()
        forbidden = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if not (full_read or columns):
            forbidden += ",SELECT"
        if _table_privilege_forbidden(db, role_name, oid, forbidden):
            raise WriterControlError("file_projection_reader_privilege_forbidden")
        if db.scalar(
            text("""
            SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c,
              LATERAL pg_catalog.aclexplode(COALESCE(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
              WHERE c.oid=:oid AND a.grantee=0)
              OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute p,
                LATERAL pg_catalog.aclexplode(p.attacl) a
                WHERE p.attrelid=:oid AND p.attnum>0 AND NOT p.attisdropped AND a.grantee=0)
            """),
            {"oid": oid},
        ):
            raise WriterControlError("file_projection_reader_public_privilege_forbidden")
        if full_read:
            flags.append(
                bool(
                    db.scalar(
                        text("SELECT pg_catalog.has_table_privilege(:name,:oid,'SELECT')"),
                        {"name": role_name, "oid": oid},
                    )
                )
            )
        elif columns:
            for column, allowed in db.execute(
                text("""
                SELECT a.attname,pg_catalog.has_column_privilege(:name,:oid,a.attnum,'SELECT')
                FROM pg_catalog.pg_attribute a
                WHERE a.attrelid=:oid AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """),
                {"name": role_name, "oid": oid},
            ):
                if column in columns:
                    flags.append(bool(allowed))
                elif allowed:
                    raise WriterControlError("file_projection_reader_column_forbidden")
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
          JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
              OR (p.prosecdef AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
              OR pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')))
        """),
        {"name": role_name},
    ):
        raise WriterControlError("file_projection_reader_function_forbidden")
    _sequence_privileges(db, role_name)
    expected = len(FILE_PROJECTION_READ_TABLES) + sum(
        len(columns) for columns in FILE_PROJECTION_READ_COLUMNS.values()
    )
    if len(flags) != expected:
        raise WriterControlError("file_projection_reader_schema_invalid")
    return tuple(flags)


def prepare_file_projection_reader(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> dict[str, int | str]:
    """Prepare only a pristine supplied role, or replay its exact read profile.

    No role creation, existing writer/profile expansion, schema/function change,
    implicit runtime configuration or internal COMMIT. The caller owns grants
    and their administrator audit in one transaction.
    """
    from miy_api.domains.official_apps.writer_roles import (
        _guard_contract,
        _identifier,
        _lock,
        _role,
        _source_guard,
    )

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
            raise WriterControlError("file_projection_reader_source_identity_forbidden")
        _source_guard(db)
        _guard_contract(db)
        reads = _read_profile(db, role_name)
        if all(reads):
            return {"role_oid": oid, "role_name": role_name}
        if any(reads):
            raise WriterControlError("file_projection_reader_existing_profile_forbidden")
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table in FILE_PROJECTION_READ_TABLES:
                db.execute(text(f"GRANT SELECT ON public.{table} TO {role}"))
            for table, columns in FILE_PROJECTION_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            if not all(_read_profile(db, role_name)):
                raise WriterControlError("file_projection_reader_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_reader.prepare",
                entity_kind="official_projection_file_reader",
                entity_id=str(oid),
                summary="Restricted canonical Files artifact reader prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return {"role_oid": oid, "role_name": role_name}
