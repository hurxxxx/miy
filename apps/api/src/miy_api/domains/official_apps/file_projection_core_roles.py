"""Explicit fresh Files-only Core staging and one private partition SHARE.

Source rows are column-read-only. Preparation is caller-transactional and never
upgrades an existing company Core role or starts a service/consumer/worker.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_roles import (
    ROLE_GUARD,
    _guard_contract,
    _identifier,
    _lock,
    _role,
    _source_guard,
    _table_privilege_forbidden,
)

LOCK_FILE_PARTITION = "public.miy_lock_file_projection_partition(uuid)"
_BODY_SHA256 = "a06f419ac180a70810baa2dfcae8d372b9601c4c10c3a8e76eb5dc2e664c8c2e"
CORE_FILE_READ_COLUMNS = {
    "file_manager_files": (
        "id",
        "retrieval_partition_id",
        "corpus_id",
        "deleted_at",
        "extraction_status",
        "extraction_content_checksum",
    ),
    "file_manager_corpora": ("id", "retrieval_partition_id", "access_scope_kind"),
    "file_manager_file_source_metadata": ("file_id", "corpus_id", "content_checksum"),
}
_READ_TABLES = ("official_projection_outbox", "retrieval_partitions")
_APPEND_TABLES = ("official_projection_receipts", "retrieval_projection_events")
_MUTABLE_TABLES = ("retrieval_projection_heads", "search_index_jobs", "rag_sync_jobs")
_EVENT_SEQUENCE = "public.retrieval_projection_events_event_sequence_seq"
_OWNER_COLUMNS = {
    "official_writer_principals": ("role_oid", "role_name"),
    "retrieval_partitions": (
        "id",
        "source_namespace",
        "candidate_scope_kind",
        "candidate_user_id",
        "state",
        "metadata_version",
    ),
}
_ALL_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


@dataclass(frozen=True)
class FileProjectionCorePreparation:
    role_oid: int
    role_name: str
    profile_prepared: bool


def _function_contract(db: Session) -> int:
    row = db.execute(
        text("""
      SELECT p.proowner::bigint,p.prosecdef,p.proconfig,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
        pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
        pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
        p.provolatile,p.proisstrict,p.proleakproof,p.proparallel
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
      WHERE p.oid=pg_catalog.to_regprocedure(:signature)
    """),
        {"signature": LOCK_FILE_PARTITION},
    ).one_or_none()
    if row is None or tuple(row[1:]) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        False,
        "uuid",
        0,
        "plpgsql",
        _BODY_SHA256,
        "v",
        False,
        False,
        "u",
    ):
        raise WriterControlError("file_projection_partition_function_invalid")
    return row[0]


def _column_flags(db: Session, name: str, oid: int, allowed: tuple[str, ...], privilege: str):
    if db.scalar(
        text("SELECT pg_catalog.has_table_privilege(:name,:oid,:privilege)"),
        {"name": name, "oid": oid, "privilege": privilege},
    ):
        raise WriterControlError("file_projection_core_table_privilege_forbidden")
    flags = []
    for column, granted in db.execute(
        text("""
      SELECT attname,pg_catalog.has_column_privilege(:name,:oid,attnum,:privilege)
      FROM pg_catalog.pg_attribute WHERE attrelid=:oid AND attnum>0 AND NOT attisdropped
      ORDER BY attnum
    """),
        {"name": name, "oid": oid, "privilege": privilege},
    ):
        if column in allowed:
            flags.append(bool(granted))
        elif granted:
            raise WriterControlError("file_projection_core_column_forbidden")
    if len(flags) != len(allowed):
        raise WriterControlError("file_projection_core_schema_invalid")
    return flags


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    if db.scalar(
        text("""
      SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE')
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%'
          AND nspname<>'information_schema' AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))
    """),
        {"name": name},
    ):
        raise WriterControlError("file_projection_core_create_forbidden")
    flags = []
    columns = _OWNER_COLUMNS if owner else CORE_FILE_READ_COLUMNS
    for schema, table, oid in db.execute(
        text("""
      SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
        AND c.relkind IN ('r','p','v','m','f') ORDER BY n.nspname,c.relname
    """)
    ):
        allowed = set()
        if schema == "public":
            if table in columns or (
                not owner and table in (*_READ_TABLES, *_APPEND_TABLES, *_MUTABLE_TABLES)
            ):
                allowed.add("SELECT")
            if not owner and table in (*_APPEND_TABLES, *_MUTABLE_TABLES):
                allowed.add("INSERT")
            if (owner and table == "retrieval_partitions") or (
                not owner and table in _MUTABLE_TABLES
            ):
                allowed.add("UPDATE")
        forbidden = ",".join(p for p in _ALL_PRIVILEGES if p not in allowed)
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("file_projection_core_privilege_forbidden")
        if db.scalar(
            text("""
          SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c,
            LATERAL pg_catalog.aclexplode(COALESCE(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
            WHERE c.oid=:oid AND a.grantee=0)
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute p,LATERAL pg_catalog.aclexplode(p.attacl) a
              WHERE p.attrelid=:oid AND p.attnum>0 AND NOT p.attisdropped AND a.grantee=0)
        """),
            {"oid": oid},
        ):
            raise WriterControlError("file_projection_core_public_privilege_forbidden")
        if schema == "public" and table in columns:
            flags.extend(_column_flags(db, name, oid, columns[table], "SELECT"))
            if owner and table == "retrieval_partitions":
                flags.extend(_column_flags(db, name, oid, ("state",), "UPDATE"))
        elif allowed:
            for privilege in sorted(allowed):
                flags.append(
                    bool(
                        db.scalar(
                            text("SELECT pg_catalog.has_table_privilege(:name,:oid,:privilege)"),
                            {"name": name, "oid": oid, "privilege": privilege},
                        )
                    )
                )
    if db.scalar(
        text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND ((p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
                AND (NOT :owner OR p.oid<>pg_catalog.to_regprocedure(:cap)))
            OR (p.prosecdef AND p.oid<>pg_catalog.to_regprocedure(:cap)
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
            OR (pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')
                AND (NOT :owner OR p.oid<>pg_catalog.to_regprocedure(:cap)))))
    """),
        {"name": name, "cap": LOCK_FILE_PARTITION, "owner": owner},
    ):
        raise WriterControlError("file_projection_core_function_forbidden")
    if db.scalar(
        text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND CASE WHEN c.relkind='S' THEN (CASE WHEN NOT :owner AND c.oid=pg_catalog.to_regclass(:sequence)
            THEN pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,UPDATE,USAGE WITH GRANT OPTION')
            ELSE pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,UPDATE,USAGE') END) ELSE false END)
    """),
        {"name": name, "sequence": _EVENT_SEQUENCE, "owner": owner},
    ):
        raise WriterControlError("file_projection_core_sequence_forbidden")
    if not owner:
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_sequence_privilege(:name,:sequence,'USAGE')"),
                    {"name": name, "sequence": _EVENT_SEQUENCE},
                )
            )
        )
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
                    {"name": name, "cap": LOCK_FILE_PARTITION},
                )
            )
        )
    expected = 9 if owner else sum(map(len, CORE_FILE_READ_COLUMNS.values())) + 2 + 4 + 9 + 2
    if len(flags) != expected:
        raise WriterControlError("file_projection_core_schema_invalid")
    return tuple(flags)


def _guards(db: Session) -> None:
    from miy_api.domains.official_apps.file_extraction_roles import file_extraction_guard_contract

    if _source_guard(db) != ROLE_GUARD:
        raise WriterControlError("file_projection_requires_role_guard")
    _guard_contract(db)
    file_extraction_guard_contract(db)


def file_projection_partition_contract(db: Session) -> None:
    _guards(db)
    oid = _function_contract(db)
    name = db.scalar(text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": oid})
    if (
        name is None
        or _role(db, name, login=False) != oid
        or not all(_profile(db, name, owner=True))
    ):
        raise WriterControlError("file_projection_partition_owner_invalid")


def install_file_projection_partition_guard(
    db: Session,
    actor: AuthContext,
    *,
    guard_owner: str,
    expected: WriterIdentity,
) -> None:
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        _guards(db)
        oid = _role(db, guard_owner, login=False)
        _profile(db, guard_owner, owner=True)
        if _function_contract(db) == oid:
            file_projection_partition_contract(db)
            return
        role = _identifier(guard_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            for table, columns in _OWNER_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            db.execute(text(f"GRANT UPDATE (state) ON public.retrieval_partitions TO {role}"))
            db.execute(text(f"ALTER FUNCTION {LOCK_FILE_PARTITION} OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            db.execute(text(f"REVOKE ALL ON FUNCTION {LOCK_FILE_PARTITION} FROM PUBLIC"))
            file_projection_partition_contract(db)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_partition_guard.install",
                entity_kind="official_projection_file_partition_guard",
                entity_id=str(oid),
                summary="Private Files Core partition lock owner prepared",
                payload={"role": guard_owner, "role_oid": oid},
            )


def _old_company_profile(db: Session, name: str) -> bool:
    from miy_api.domains.official_apps.projection_partition_roles import (
        LOCK_CORE_PARTITION,
        _CORE_READ_TABLES,
        _CORE_APPEND_TABLES,
        _CORE_MUTABLE_TABLES,
        _core_privileges,
        company_partition_capability_contract,
    )

    if not db.scalar(
        text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
        {"name": name, "cap": LOCK_CORE_PARTITION},
    ):
        return False
    _core_privileges(db, name)
    company_partition_capability_contract(db)
    complete = all(
        db.scalar(
            text("SELECT pg_catalog.has_table_privilege(:name,:table,:privilege)"),
            {"name": name, "table": "public." + table, "privilege": privilege},
        )
        for tables, privileges in (
            (_CORE_READ_TABLES, ("SELECT",)),
            (_CORE_APPEND_TABLES, ("SELECT", "INSERT")),
            (_CORE_MUTABLE_TABLES, ("SELECT", "INSERT", "UPDATE")),
        )
        for table in tables
        for privilege in privileges
    )
    if not complete or not db.scalar(
        text("SELECT pg_catalog.has_sequence_privilege(:name,:sequence,'USAGE')"),
        {"name": name, "sequence": _EVENT_SEQUENCE},
    ):
        raise WriterControlError("file_projection_core_existing_profile_forbidden")
    return True


def prepare_file_projection_core(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> FileProjectionCorePreparation:
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        if db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.official_writer_principals WHERE role_oid=:oid OR role_name=:name)"
            ),
            {"oid": oid, "name": role_name},
        ):
            raise WriterControlError("file_projection_core_source_identity_forbidden")
        file_projection_partition_contract(db)
        if _old_company_profile(db, role_name):
            return FileProjectionCorePreparation(oid, role_name, False)
        flags = _profile(db, role_name)
        if all(flags):
            return FileProjectionCorePreparation(oid, role_name, True)
        if any(flags):
            raise WriterControlError("file_projection_core_existing_profile_forbidden")
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table, columns in CORE_FILE_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            for tables, privileges in (
                (_READ_TABLES, "SELECT"),
                (_APPEND_TABLES, "SELECT,INSERT"),
                (_MUTABLE_TABLES, "SELECT,INSERT,UPDATE"),
            ):
                for table in tables:
                    db.execute(text(f"GRANT {privileges} ON public.{table} TO {role}"))
            db.execute(text(f"GRANT USAGE ON SEQUENCE {_EVENT_SEQUENCE} TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {LOCK_FILE_PARTITION} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("file_projection_core_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_core_principal.prepare",
                entity_kind="official_projection_file_core_principal",
                entity_id=str(oid),
                summary="Restricted Files Core staging principal prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return FileProjectionCorePreparation(oid, role_name, True)
