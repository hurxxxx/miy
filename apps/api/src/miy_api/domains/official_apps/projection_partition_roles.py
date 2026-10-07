"""Explicit private company-default reader preparation; never service activation.

Source receives one fixed UUID read/SHARE capability, without any Core table
read or write privilege. The supplied NOLOGIN owner holds only the metadata lock
authority needed by that function and the existing private principal admission.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin

READ_COMPANY_PARTITION = "public.miy_read_official_company_partition(text,uuid)"
LOCK_CORE_PARTITION = "public.miy_lock_official_projection_partition(uuid,text)"
_PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
_CAPABILITIES = (READ_COMPANY_PARTITION, LOCK_CORE_PARTITION)
# Exact PL/pgSQL bodies frozen by the owned official_partition_20261007 migration.
# A same-header function from another schema/code version is not this capability.
_CAPABILITY_BODY_SHA256 = {
    READ_COMPANY_PARTITION: "72087c051b2b49fd78d6740dce6b26bee9b1c544f4e4168ff2fc3c783956ad86",
    LOCK_CORE_PARTITION: "2096c8c74e2022ca688b14a5ca229f76cf362f86f4ec2c2e47c5bf05d553cd4d",
}
_CORE_READ_TABLES = (
    "docs_native_docs",
    "pms_tasks",
    "meetings",
    "official_projection_outbox",
    "retrieval_partitions",
)
_CORE_APPEND_TABLES = ("official_projection_receipts", "retrieval_projection_events")
_CORE_MUTABLE_TABLES = ("retrieval_projection_heads", "search_index_jobs", "rag_sync_jobs")
_CORE_EVENT_SEQUENCE = "public.retrieval_projection_events_event_sequence_seq"


def _function_contract(db: Session, signature: str = READ_COMPANY_PARTITION) -> int:
    row = db.execute(
        text("""
        SELECT p.proowner::bigint,p.prosecdef,p.proconfig,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
            COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
          pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
          pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE p.oid=pg_catalog.to_regprocedure(:signature)
        """),
        {"signature": signature},
    ).one_or_none()
    if row is None or tuple(row[1:]) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        False,
        "uuid",
        1 if signature == READ_COMPANY_PARTITION else 0,
        "plpgsql",
        _CAPABILITY_BODY_SHA256[signature],
    ):
        raise WriterControlError("official_projection_partition_function_invalid")
    return row[0]


def _reader_privileges(db: Session, name: str) -> None:
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
        {"name": name},
    ):
        raise WriterControlError("official_projection_partition_owner_create_forbidden")
    for schema, table, oid in db.execute(
        text("""
        SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND c.relkind IN ('r','p','v','m','f')
        """)
    ):
        forbidden = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if schema == "public" and table == "official_writer_principals":
            forbidden = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        elif schema == "public" and table == "retrieval_partitions":
            forbidden = "INSERT,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("official_projection_partition_owner_privilege_forbidden")
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
          JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND ((p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
                AND p.oid NOT IN (pg_catalog.to_regprocedure(:reader),pg_catalog.to_regprocedure(:core)))
              OR (p.prosecdef
                AND p.oid NOT IN (pg_catalog.to_regprocedure(:reader),pg_catalog.to_regprocedure(:core),pg_catalog.to_regprocedure(:admit))
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
              OR (p.oid NOT IN (pg_catalog.to_regprocedure(:reader),pg_catalog.to_regprocedure(:core))
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION'))))
        """),
        {
            "name": name,
            "reader": READ_COMPANY_PARTITION,
            "core": LOCK_CORE_PARTITION,
            "admit": _PRODUCER_ADMISSION,
        },
    ):
        raise WriterControlError("official_projection_partition_owner_function_forbidden")
    _sequence_privileges(db, name)


def company_partition_capability_contract(db: Session) -> None:
    """Attest the migrated function and its separately prepared minimal owner."""
    from miy_api.domains.official_apps.recording_roles import guard_contract
    from miy_api.domains.official_apps.writer_roles import _role

    guard_contract(db)
    owner_oid = _function_contract(db)
    if _function_contract(db, LOCK_CORE_PARTITION) != owner_oid:
        raise WriterControlError("official_projection_partition_owner_mismatch")
    owner_name = db.scalar(
        text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": owner_oid}
    )
    if owner_name is None or _role(db, owner_name, login=False) != owner_oid:
        raise WriterControlError("official_projection_partition_owner_invalid")
    _reader_privileges(db, owner_name)
    if not db.scalar(
        text("""
        SELECT pg_catalog.has_table_privilege(:name,'public.official_writer_principals','SELECT')
          AND pg_catalog.has_table_privilege(:name,'public.retrieval_partitions','SELECT')
          AND pg_catalog.has_table_privilege(:name,'public.retrieval_partitions','UPDATE')
          AND pg_catalog.has_function_privilege(:name,:admit,'EXECUTE')
        """),
        {"name": owner_name, "admit": _PRODUCER_ADMISSION},
    ):
        raise WriterControlError("official_projection_partition_owner_unprepared")


def install_company_partition_reader(
    db: Session,
    actor: AuthContext,
    *,
    reader_owner: str,
    expected: WriterIdentity,
) -> None:
    """Prepare a supplied NOLOGIN function owner during explicit hardened drain.

    Does not create roles, grant a Source principal, reopen writes or activate a
    runtime. The Core caller commits function ownership/grants/audit together.
    """
    from miy_api.domains.official_apps.recording_roles import guard_contract
    from miy_api.domains.official_apps.writer_roles import (
        ROLE_GUARD,
        _guard_contract,
        _identifier,
        _lock,
        _role,
        _source_guard,
    )

    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        if _source_guard(db) != ROLE_GUARD:
            raise WriterControlError("official_projection_partition_requires_role_guard")
        _guard_contract(db)
        guard_contract(db)
        oid = _role(db, reader_owner, login=False)
        _reader_privileges(db, reader_owner)
        if _function_contract(db) == oid and _function_contract(db, LOCK_CORE_PARTITION) == oid:
            company_partition_capability_contract(db)
            return
        role = _identifier(reader_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            db.execute(text(f"GRANT SELECT ON public.official_writer_principals TO {role}"))
            db.execute(text(f"GRANT SELECT,UPDATE ON public.retrieval_partitions TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {_PRODUCER_ADMISSION} TO {role}"))
            for signature in _CAPABILITIES:
                db.execute(text(f"ALTER FUNCTION {signature} OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            for signature in _CAPABILITIES:
                db.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))
            company_partition_capability_contract(db)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.partition_reader.install",
                entity_kind="official_writer_scope",
                entity_id=expected.scope,
                summary="Private locked company partition reader prepared during drain",
                payload={"reader_owner_oid": oid, "reader_owner": reader_owner},
            )


def _core_privileges(db: Session, role_name: str) -> None:
    from miy_api.domains.official_apps.writer_roles import _table_privilege_forbidden

    if db.scalar(
        text("""
        SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE')
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace
            WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'
            AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))
        """),
        {"name": role_name},
    ):
        raise WriterControlError("official_projection_core_create_forbidden")
    for schema, table, oid in db.execute(
        text("""
        SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND c.relkind IN ('r','p','v','m','f')
        """)
    ):
        forbidden = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if schema == "public" and table in _CORE_READ_TABLES:
            forbidden = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        elif schema == "public" and table in _CORE_APPEND_TABLES:
            forbidden = "UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        elif schema == "public" and table in _CORE_MUTABLE_TABLES:
            forbidden = "DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if _table_privilege_forbidden(db, role_name, oid, forbidden):
            raise WriterControlError("official_projection_core_privilege_forbidden")
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND CASE WHEN c.relkind='S' THEN
              CASE WHEN c.oid=pg_catalog.to_regclass(:sequence)
                THEN pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,UPDATE,USAGE WITH GRANT OPTION')
                ELSE pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,USAGE,UPDATE') END
              ELSE false END)
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
              AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
                OR (p.prosecdef AND p.oid<>pg_catalog.to_regprocedure(:capability)
                  AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
                OR pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')))
        """),
        {"name": role_name, "sequence": _CORE_EVENT_SEQUENCE, "capability": LOCK_CORE_PARTITION},
    ):
        raise WriterControlError("official_projection_core_function_sequence_forbidden")


def prepare_company_projection_core(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> dict[str, int | str]:
    """Explicit fixed Core staging profile; source rows remain SELECT-only.

    Does not bind a Source identity or grant arbitrary partition UPDATE. Current
    actor/role/function/guard validation and all grants share the caller transaction.
    """
    from miy_api.domains.official_apps.writer_roles import (
        ROLE_GUARD,
        _guard_contract,
        _identifier,
        _lock,
        _role,
        _source_guard,
    )

    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        _core_privileges(db, role_name)
        if db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.official_writer_principals WHERE role_oid=:oid OR role_name=:name)"
            ),
            {"oid": oid, "name": role_name},
        ):
            raise WriterControlError("official_projection_core_source_identity_forbidden")
        if _source_guard(db) != ROLE_GUARD:
            raise WriterControlError("official_projection_partition_requires_role_guard")
        _guard_contract(db)
        company_partition_capability_contract(db)
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for tables, privileges in (
                (_CORE_READ_TABLES, "SELECT"),
                (_CORE_APPEND_TABLES, "SELECT,INSERT"),
                (_CORE_MUTABLE_TABLES, "SELECT,INSERT,UPDATE"),
            ):
                for table in tables:
                    db.execute(text(f"GRANT {privileges} ON public.{table} TO {role}"))
            db.execute(text(f"GRANT USAGE ON SEQUENCE {_CORE_EVENT_SEQUENCE} TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {LOCK_CORE_PARTITION} TO {role}"))
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.core_principal.prepare",
                entity_kind="official_projection_core_principal",
                entity_id=str(oid),
                summary="Restricted company projection Core staging principal prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return {"role_oid": oid, "role_name": role_name}
