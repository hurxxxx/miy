"""Explicit fresh Files Source UUID/SHARE profile; never expands an old role."""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.file_extraction_roles import (
    ADMIT,
    POLICY_READ_COLUMNS,
    REQUEST_TABLE,
    RESULT_DIGEST,
    _create_forbidden,
    _profile as _extraction_profile,
    _public_relations_forbidden,
    _relations,
    file_extraction_guard_contract,
)
from miy_api.domains.official_apps.file_projection_core_roles import _column_flags
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_contracts import (
    COVERED_SOURCE_TABLES,
    MUTABLE_TRANSPORT_TABLES,
    WRITER_READ_TABLES,
    WRITER_TRANSPORT_TABLES,
)
from miy_api.domains.official_apps.writer_roles import (
    ROLE_GUARD,
    RuntimePrincipal,
    _guard_contract,
    _identifier,
    _lock,
    _role,
    _runtime_privileges,
    _sequence_privileges,
    _source_guard,
    _table_privilege_forbidden,
)

READ_FILE_SOURCE_PARTITION = "public.miy_read_file_source_partition(uuid,integer)"
_PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
_BODY_SHA256 = "eac5f2fc75492cf51bc3135e27459686075b3faa20597c85a825d6574e9f8b4a"
_OWNER_COLUMNS = {
    "official_writer_principals": ("role_oid", "role_name", "generation", "artifact"),
    "retrieval_partitions": (
        "id",
        "source_namespace",
        "candidate_scope_kind",
        "candidate_user_id",
        "state",
        "is_default_ingest",
        "metadata_version",
    ),
}
_ALL = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


@dataclass(frozen=True)
class FileSourcePartitionPreparation:
    principal: RuntimePrincipal
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
        {"signature": READ_FILE_SOURCE_PARTITION},
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
        raise WriterControlError("file_source_partition_function_invalid")
    return row[0]


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    """Fixed independent ceiling; old F2 validator/body remain unchanged."""
    _create_forbidden(db, name)
    flags = []
    for schema, table, oid in _relations(db):
        allowed = ()
        columns = ()
        if schema == "public":
            if owner:
                columns = _OWNER_COLUMNS.get(table, ())
            elif table in COVERED_SOURCE_TABLES:
                allowed = ("SELECT", "INSERT", "UPDATE", "DELETE")
            elif table in WRITER_TRANSPORT_TABLES:
                allowed = (
                    ("SELECT", "INSERT", "UPDATE")
                    if table in MUTABLE_TRANSPORT_TABLES
                    else ("SELECT", "INSERT")
                )
            elif table in WRITER_READ_TABLES:
                allowed = ("SELECT",)
            elif table == REQUEST_TABLE:
                allowed = ("SELECT", "INSERT", "UPDATE")
            else:
                columns = POLICY_READ_COLUMNS.get(table, ())
        excluded = {"SELECT"} if columns else set()
        if owner and schema == "public" and table == "retrieval_partitions":
            excluded.add("UPDATE")
        forbidden = ",".join(p for p in _ALL if p not in allowed and p not in excluded)
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("file_source_partition_privilege_forbidden")
        _public_relations_forbidden(db, oid)
        for privilege in allowed:
            flags.append(
                bool(
                    db.scalar(
                        text("SELECT pg_catalog.has_table_privilege(:name,:oid,:privilege)"),
                        {"name": name, "oid": oid, "privilege": privilege},
                    )
                )
            )
        if columns:
            flags.extend(_column_flags(db, name, oid, columns, "SELECT"))
            if owner and table == "retrieval_partitions":
                flags.extend(_column_flags(db, name, oid, ("state",), "UPDATE"))
    permitted = (
        (READ_FILE_SOURCE_PARTITION, _PRODUCER_ADMISSION)
        if owner
        else (READ_FILE_SOURCE_PARTITION, ADMIT, RESULT_DIGEST)
    )
    if db.scalar(
        text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
       WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
        AND ((p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
          AND NOT (:owner AND p.oid=pg_catalog.to_regprocedure(:cap)))
         OR (p.prosecdef AND p.oid<>ALL(CAST(:permitted AS regprocedure[]))
          AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
         OR (pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')
          AND NOT (:owner AND p.oid=pg_catalog.to_regprocedure(:cap)))))
    """),
        {
            "name": name,
            "owner": owner,
            "cap": READ_FILE_SOURCE_PARTITION,
            "permitted": list(permitted),
        },
    ):
        raise WriterControlError("file_source_partition_function_forbidden")
    for signature in (_PRODUCER_ADMISSION,) if owner else permitted:
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:signature,'EXECUTE')"),
                    {"name": name, "signature": signature},
                )
            )
        )
    _sequence_privileges(db, name)
    expected = (
        sum(map(len, _OWNER_COLUMNS.values())) + 2
        if owner
        else 4 * len(COVERED_SOURCE_TABLES)
        + sum(3 if t in MUTABLE_TRANSPORT_TABLES else 2 for t in WRITER_TRANSPORT_TABLES)
        + len(WRITER_READ_TABLES)
        + 3
        + sum(map(len, POLICY_READ_COLUMNS.values()))
        + 3
    )
    if len(flags) != expected:
        raise WriterControlError("file_source_partition_schema_invalid")
    return tuple(flags)


def _guards(db: Session) -> None:
    if _source_guard(db) != ROLE_GUARD:
        raise WriterControlError("file_source_partition_requires_role_guard")
    _guard_contract(db)
    file_extraction_guard_contract(db)


def file_source_partition_contract(db: Session) -> None:
    _guards(db)
    oid = _function_contract(db)
    name = db.scalar(text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": oid})
    if (
        name is None
        or _role(db, name, login=False) != oid
        or not all(_profile(db, name, owner=True))
    ):
        raise WriterControlError("file_source_partition_owner_invalid")


def install_file_source_partition_guard(
    db: Session, actor: AuthContext, *, guard_owner: str, expected: WriterIdentity
) -> None:
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        _guards(db)
        oid = _role(db, guard_owner, login=False)
        _profile(db, guard_owner, owner=True)
        if _function_contract(db) == oid:
            file_source_partition_contract(db)
            return
        role = _identifier(guard_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            for table, columns in _OWNER_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            db.execute(text(f"GRANT UPDATE(state) ON public.retrieval_partitions TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {_PRODUCER_ADMISSION} TO {role}"))
            db.execute(text(f"ALTER FUNCTION {READ_FILE_SOURCE_PARTITION} OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            file_source_partition_contract(db)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_file_source_partition.guard.install",
                entity_kind="official_file_source_partition_guard",
                entity_id=str(oid),
                summary="Private Files Source descriptor SHARE owner prepared",
                payload={"role": guard_owner, "role_oid": oid},
            )


def _old_profile(db: Session, name: str) -> None:
    try:
        if all(_extraction_profile(db, name)):
            file_extraction_guard_contract(db)
            return
    except WriterControlError:
        pass
    _runtime_privileges(db, name, company_projection=True)
    _sequence_privileges(db, name)
    if not all(
        db.scalar(
            text("SELECT pg_catalog.has_table_privilege(:name,:table,:privilege)"),
            {"name": name, "table": "public." + table, "privilege": privilege},
        )
        for tables, privileges in (
            (COVERED_SOURCE_TABLES, ("SELECT", "INSERT", "UPDATE", "DELETE")),
            (
                tuple(t for t in WRITER_TRANSPORT_TABLES if t not in MUTABLE_TRANSPORT_TABLES),
                ("SELECT", "INSERT"),
            ),
            (MUTABLE_TRANSPORT_TABLES, ("SELECT", "INSERT", "UPDATE")),
            (WRITER_READ_TABLES, ("SELECT",)),
        )
        for table in tables
        for privilege in privileges
    ):
        raise WriterControlError("file_source_partition_existing_profile_forbidden")


def prepare_file_source_partition_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    identity: WriterIdentity,
    expected: WriterIdentity,
    expected_state: str,
) -> FileSourcePartitionPreparation:
    if identity.owner != "legacy" or identity.artifact is None:
        raise WriterControlError("writer_role_identity_unavailable")
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        existing = db.scalar(
            select(RuntimePrincipal)
            .where((RuntimePrincipal.role_oid == oid) | (RuntimePrincipal.role_name == role_name))
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            if (
                existing.role_oid,
                existing.role_name,
                existing.scope,
                existing.owner,
                existing.generation,
                existing.artifact,
                existing.revoked_at,
            ) != (
                oid,
                role_name,
                identity.scope,
                identity.owner,
                identity.generation,
                identity.artifact,
                None,
            ):
                raise WriterControlError("writer_role_identity_immutable")
            if db.scalar(
                text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
                {"name": role_name, "cap": READ_FILE_SOURCE_PARTITION},
            ):
                file_source_partition_contract(db)
                if not all(_profile(db, role_name)):
                    raise WriterControlError("file_source_partition_existing_profile_forbidden")
                return FileSourcePartitionPreparation(existing, True)
            _old_profile(db, role_name)
            return FileSourcePartitionPreparation(existing, False)
        if any(_profile(db, role_name)):
            raise WriterControlError("file_source_partition_existing_profile_forbidden")
        file_source_partition_contract(db)
        role = _identifier(role_name)
        with db.begin_nested():
            principal = RuntimePrincipal(
                role_oid=oid,
                role_name=role_name,
                scope=identity.scope,
                owner=identity.owner,
                generation=identity.generation,
                artifact=identity.artifact,
                approved_by_user_id=current.user.id,
                approved_by_session_id=current.session.id,
            )
            db.add(principal)
            db.flush()
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table in COVERED_SOURCE_TABLES:
                db.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {role}"))
            for table in WRITER_TRANSPORT_TABLES:
                privileges = (
                    "SELECT,INSERT,UPDATE" if table in MUTABLE_TRANSPORT_TABLES else "SELECT,INSERT"
                )
                db.execute(text(f"GRANT {privileges} ON public.{table} TO {role}"))
            for table in WRITER_READ_TABLES:
                db.execute(text(f"GRANT SELECT ON public.{table} TO {role}"))
            db.execute(text(f"GRANT SELECT,INSERT,UPDATE ON public.{REQUEST_TABLE} TO {role}"))
            for table, columns in POLICY_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            for signature in (ADMIT, RESULT_DIGEST, READ_FILE_SOURCE_PARTITION):
                db.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("file_source_partition_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_file_source_partition.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Fresh Files Source descriptor capability principal prepared",
                payload={
                    "role": role_name,
                    "generation": identity.generation,
                    "artifact": identity.artifact,
                },
            )
        return FileSourcePartitionPreparation(principal, True)
