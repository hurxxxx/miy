"""One explicit Core Files effect profile; old profiles never gain new rights."""

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
from miy_api.domains.official_apps.file_materialization_roles import (
    FILE_MATERIALIZATION_READ_COLUMNS,
    _old_exact_profile,
    _read_profile,
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

FILE_EFFECT_TABLE = "core_file_materialization_operations"
LOCK_FILE_MATERIALIZATION = "public.miy_lock_file_materialization(bigint,uuid,uuid,integer)"
FILE_EFFECT_INPUT_COLUMNS = (
    "operation_id",
    "event_sequence",
    "resource_type",
    "resource_id",
    "projection_version",
    "retrieval_partition_id",
    "partition_metadata_version",
    "change_kind",
    "desired_state",
    "content_checksum",
    "visibility_checksum",
    "source_event_id",
    "source_revision",
    "source_payload_digest",
    "source_extracted_at",
    "keyword_generation_id",
    "vector_generation_id",
    "generation_key",
    "keyword_physical_name",
    "vector_physical_name",
    "keyword_schema_version",
    "vector_schema_version",
)
FILE_EFFECT_COLUMNS = (
    *FILE_EFFECT_INPUT_COLUMNS,
    "issuer_role_oid",
    "issuer_role_name",
    "armed_xact_id",
    "header_digest",
    "state",
    "created_at",
    "completed_at",
)
GENERATION_READ_COLUMNS = (
    "id",
    "backend",
    "generation_key",
    "physical_name",
    "schema_version",
    "state",
)
DESCRIPTOR_READ_COLUMNS = (
    "id",
    "source_namespace",
    "candidate_scope_kind",
    "candidate_user_id",
    "state",
    "metadata_version",
)
JOB_READ_COLUMNS = {
    "search_index_jobs": (
        "id",
        "resource_type",
        "entity_type",
        "entity_id",
        "projection_version",
        "projection_event_sequence",
        "retrieval_partition_id",
        "desired_state",
        "operation",
        "status",
        "attempts",
    ),
    "rag_sync_jobs": (
        "id",
        "resource_type",
        "resource_id",
        "projection_version",
        "projection_event_sequence",
        "retrieval_partition_id",
        "desired_state",
        "operation",
        "status",
        "attempts",
    ),
}
JOB_UPDATE_COLUMNS = ("status", "attempts", "last_error", "next_retry_at", "updated_at")
FILE_EFFECT_READ_COLUMNS = {
    **FILE_MATERIALIZATION_READ_COLUMNS,
    "retrieval_projection_generations": GENERATION_READ_COLUMNS,
    "retrieval_partitions": DESCRIPTOR_READ_COLUMNS,
    FILE_EFFECT_TABLE: FILE_EFFECT_COLUMNS,
    **JOB_READ_COLUMNS,
}
FILE_EFFECT_UPDATE_COLUMNS = {
    FILE_EFFECT_TABLE: ("state",),
    **{table: JOB_UPDATE_COLUMNS for table in JOB_READ_COLUMNS},
}
_OWNER_READ_COLUMNS = {
    "file_manager_files": (
        "id",
        "corpus_id",
        "retrieval_partition_id",
        "deleted_at",
        "extraction_status",
        "extraction_content_checksum",
        "extracted_at",
    ),
    "file_manager_corpora": ("id", "access_scope_kind", "retrieval_partition_id"),
    "file_manager_file_source_metadata": ("file_id", "corpus_id", "content_checksum"),
    **{
        table: FILE_MATERIALIZATION_READ_COLUMNS[table]
        for table in (
            "retrieval_projection_events",
            "retrieval_projection_heads",
            "official_writer_principals",
            "official_projection_outbox",
            "official_projection_receipts",
        )
    },
    "retrieval_partitions": DESCRIPTOR_READ_COLUMNS,
    "retrieval_projection_generations": GENERATION_READ_COLUMNS,
    FILE_EFFECT_TABLE: ("state", "keyword_generation_id", "vector_generation_id"),
}
_OWNER_UPDATE_COLUMNS = {
    "retrieval_partitions": ("state",),
    "retrieval_projection_generations": ("state",),
    "retrieval_projection_heads": ("projection_version",),
}
_FUNCTIONS = (
    LOCK_FILE_MATERIALIZATION,
    "public.miy_guard_file_materialization_effect_writer()",
    "public.miy_guard_file_materialization_effect_row()",
    "public.miy_guard_file_materialization_generation()",
)
# Fixed hashes are filled from this owned new migration before its first freeze.
_BODY_SHA256 = {
    "public.miy_lock_file_materialization(bigint,uuid,uuid,integer)": "22bcecb3f111d7739f21bf5b2311b7da1ec3c550b01969037413f39eac90210f",
    "public.miy_guard_file_materialization_effect_writer()": "5c13adb1e7217baaf00e57c05b1676ddd4d53208d33565b2f9725dcdaaaffa70",
    "public.miy_guard_file_materialization_effect_row()": "8acb606231be5305399a364d75c5b1de2bdfa4b68ce83bf96c6ccea2be040ed5",
    "public.miy_guard_file_materialization_generation()": "9a8e3d92edde36708231955d450fd9e2f8f23147751d8ab2cde31199973b4276",
}
_TRIGGERS = (
    (FILE_EFFECT_TABLE, "miy_file_materialization_effect_writer", _FUNCTIONS[1], 62, ()),
    (FILE_EFFECT_TABLE, "miy_file_materialization_effect_row", _FUNCTIONS[2], 23, ()),
    (
        "retrieval_projection_generations",
        "miy_file_materialization_generation",
        _FUNCTIONS[3],
        19,
        (
            "id",
            "backend",
            "generation_key",
            "physical_name",
            "schema_version",
            "state",
            "baseline_event_sequence",
            "replay_event_sequence",
        ),
    ),
)
_ALL = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


@dataclass(frozen=True)
class FileMaterializationEffectPreparation:
    role_oid: int
    role_name: str
    profile_prepared: bool


@dataclass(frozen=True)
class FileMaterializationEffectGuardPreparation:
    role_oid: int
    role_name: str
    profile_prepared: bool


def _function_contract(db: Session) -> int:
    owners = set()
    for signature in _FUNCTIONS:
        row = db.execute(
            text("""
            SELECT p.proowner::bigint,p.prosecdef,p.proconfig,
              EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
                WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
              pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
              pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
              p.provolatile,p.proisstrict,p.proleakproof,p.proparallel
            FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
            WHERE p.oid=pg_catalog.to_regprocedure(:signature)
            """),
            {"signature": signature},
        ).one_or_none()
        if row is None or tuple(row[1:]) != (
            True,
            ["search_path=pg_catalog, pg_temp"],
            False,
            "uuid" if signature == LOCK_FILE_MATERIALIZATION else "trigger",
            0,
            "plpgsql",
            _BODY_SHA256.get(signature),
            "v",
            False,
            False,
            "u",
        ):
            raise WriterControlError("file_materialization_effect_function_invalid")
        owners.add(row[0])
        grants = db.execute(
            text("""
            SELECT a.grantee::bigint,a.is_grantable FROM pg_catalog.pg_proc p,
              LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,
                pg_catalog.acldefault('f',p.proowner))) a
            WHERE p.oid=pg_catalog.to_regprocedure(:signature)
              AND a.grantee<>p.proowner AND a.privilege_type='EXECUTE'
            """),
            {"signature": signature},
        ).all()
        if signature != LOCK_FILE_MATERIALIZATION and grants:
            raise WriterControlError("file_materialization_effect_private_execute_forbidden")
        for grantee, grantable in grants:
            name = db.scalar(
                text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": grantee}
            )
            if (
                grantable
                or name is None
                or _role(db, name, login=True) != grantee
                or db.scalar(
                    text("""
                    SELECT EXISTS(SELECT 1 FROM public.official_writer_principals
                      WHERE role_oid=:oid OR role_name=:name)
                    """),
                    {"oid": grantee, "name": name},
                )
                or not all(_profile(db, name))
            ):
                raise WriterControlError("file_materialization_effect_execute_profile_invalid")
    if len(owners) != 1:
        raise WriterControlError("file_materialization_effect_owner_invalid")
    if db.execute(
        text("""
        SELECT tgname FROM pg_catalog.pg_trigger
        WHERE tgrelid='public.core_file_materialization_operations'::regclass
          AND NOT tgisinternal ORDER BY tgname
        """)
    ).scalars().all() != sorted(
        trigger for table, trigger, *_ in _TRIGGERS if table == FILE_EFFECT_TABLE
    ):
        raise WriterControlError("file_materialization_effect_trigger_invalid")
    for name, columns, predicate in (
        (
            "uq_core_file_materialization_event_pair",
            ("event_sequence", "keyword_generation_id", "vector_generation_id"),
            None,
        ),
        (
            "uq_core_file_materialization_armed_keyword",
            ("resource_id", "keyword_generation_id"),
            "((state)::text = 'armed'::text)",
        ),
        (
            "uq_core_file_materialization_armed_vector",
            ("resource_id", "vector_generation_id"),
            "((state)::text = 'armed'::text)",
        ),
    ):
        row = db.execute(
            text("""
            SELECT i.indisunique,i.indisvalid,i.indisready,
              i.indexprs IS NULL,i.indnkeyatts,i.indnatts,i.indimmediate,
              i.indisexclusion,
              ARRAY(SELECT a.attname::text
                FROM unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum,position)
                JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
                ORDER BY k.position),pg_catalog.pg_get_expr(i.indpred,i.indrelid)
            FROM pg_catalog.pg_index i
            WHERE i.indexrelid=pg_catalog.to_regclass(:index)
              AND i.indrelid='public.core_file_materialization_operations'::regclass
            """),
            {"index": "public." + name},
        ).one_or_none()
        if row is None or tuple(row) != (
            True,
            True,
            True,
            True,
            len(columns),
            len(columns),
            True,
            False,
            list(columns),
            predicate,
        ):
            raise WriterControlError("file_materialization_effect_index_invalid")
    for table, trigger, signature, kind, columns in _TRIGGERS:
        row = db.execute(
            text("""
            SELECT t.tgfoid=pg_catalog.to_regprocedure(:signature),t.tgenabled,t.tgtype,
              t.tgnargs,t.tgargs=decode('','hex'),t.tgdeferrable,t.tginitdeferred,
              t.tgconstraint=0,t.tgqual IS NULL,
              ARRAY(SELECT a.attname::text FROM pg_catalog.pg_attribute a
                WHERE a.attrelid=t.tgrelid AND a.attnum=ANY(t.tgattr::smallint[])
                ORDER BY a.attname)
            FROM pg_catalog.pg_trigger t
            WHERE t.tgrelid=pg_catalog.to_regclass(:table) AND t.tgname=:trigger
            """),
            {"signature": signature, "table": "public." + table, "trigger": trigger},
        ).one_or_none()
        if row is None or tuple(row) != (
            True,
            "O",
            kind,
            0,
            True,
            False,
            False,
            True,
            True,
            sorted(columns),
        ):
            raise WriterControlError("file_materialization_effect_trigger_invalid")
    return owners.pop()


def _functions(db: Session, name: str, *, owner: bool) -> None:
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
          JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND ((p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
              AND (NOT :owner OR p.oid<>ALL(CAST(:owned AS regprocedure[]))))
            OR (p.prosecdef AND p.oid<>ALL(CAST(:permitted AS regprocedure[]))
              AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
            OR (p.oid<>ALL(CAST(:owned AS regprocedure[]))
              AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION'))
            OR (p.oid<>ALL(CAST(:permitted AS regprocedure[])) AND EXISTS(
              SELECT 1 FROM pg_catalog.aclexplode(p.proacl) a
                WHERE a.grantee=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
                  AND a.privilege_type='EXECUTE'))))
        """),
        {
            "name": name,
            "owner": owner,
            "owned": list(_FUNCTIONS) if owner else [],
            "permitted": list(_FUNCTIONS) if owner else [LOCK_FILE_MATERIALIZATION],
        },
    ):
        raise WriterControlError("file_materialization_effect_function_forbidden")


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    _create_forbidden(db, name)
    read = _OWNER_READ_COLUMNS if owner else FILE_EFFECT_READ_COLUMNS
    insert = {} if owner else {FILE_EFFECT_TABLE: FILE_EFFECT_INPUT_COLUMNS}
    update = _OWNER_UPDATE_COLUMNS if owner else FILE_EFFECT_UPDATE_COLUMNS
    flags = []
    for schema, table, oid in _relations(db):
        allowed = {
            privilege: mapping.get(table, ()) if schema == "public" else ()
            for privilege, mapping in (("SELECT", read), ("INSERT", insert), ("UPDATE", update))
        }
        forbidden = ",".join(p for p in _ALL if not allowed.get(p))
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("file_materialization_effect_privilege_forbidden")
        _public_relations_forbidden(db, oid)
        for privilege, columns in allowed.items():
            if columns:
                flags.extend(_column_flags(db, name, oid, columns, privilege))
    _functions(db, name, owner=owner)
    _sequence_privileges(db, name)
    expected = (
        sum(map(len, read.values()))
        + sum(map(len, insert.values()))
        + sum(map(len, update.values()))
    )
    if len(flags) != expected:
        raise WriterControlError("file_materialization_effect_schema_invalid")
    if not owner:
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
                    {"name": name, "cap": LOCK_FILE_MATERIALIZATION},
                )
            )
        )
    return tuple(flags)


def _guards(db: Session) -> None:
    if _source_guard(db) != ROLE_GUARD:
        raise WriterControlError("file_materialization_effect_requires_role_guard")
    _guard_contract(db)
    file_extraction_guard_contract(db)


def file_materialization_effect_contract(db: Session) -> None:
    _guards(db)
    oid = _function_contract(db)
    name = db.scalar(text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": oid})
    if (
        name is None
        or _role(db, name, login=False) != oid
        or not all(_profile(db, name, owner=True))
    ):
        raise WriterControlError("file_materialization_effect_owner_invalid")


def install_file_materialization_effect_guard(
    db: Session,
    actor: AuthContext,
    *,
    owner_role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> FileMaterializationEffectGuardPreparation:
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        _guards(db)
        previous_oid = _function_contract(db)
        oid = _role(db, owner_role_name, login=False)
        flags = _profile(db, owner_role_name, owner=True)
        if previous_oid == oid:
            if not all(flags):
                raise WriterControlError("file_materialization_effect_owner_invalid")
            return FileMaterializationEffectGuardPreparation(oid, owner_role_name, True)
        if any(flags) or db.scalar(
            text("SELECT NOT rolcanlogin FROM pg_catalog.pg_roles WHERE oid=:oid"),
            {"oid": previous_oid},
        ):
            raise WriterControlError("file_materialization_effect_owner_existing_profile")
        role = _identifier(owner_role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table, columns in _OWNER_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            for table, columns in _OWNER_UPDATE_COLUMNS.items():
                db.execute(text(f"GRANT UPDATE ({','.join(columns)}) ON public.{table} TO {role}"))
            for signature in _FUNCTIONS:
                db.execute(text(f"ALTER FUNCTION {signature} OWNER TO {role}"))
                db.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))
            file_materialization_effect_contract(db)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_materialization_effect_guard.install",
                entity_kind="official_projection_file_materialization_effect_guard",
                entity_id=str(oid),
                summary="Private Files effect lifecycle and immutable history guard installed",
                payload={"role": owner_role_name, "role_oid": oid},
            )
        return FileMaterializationEffectGuardPreparation(oid, owner_role_name, True)


def prepare_file_materialization_effect_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> FileMaterializationEffectPreparation:
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
            raise WriterControlError("file_materialization_effect_source_identity_forbidden")
        file_materialization_effect_contract(db)
        has_cap = db.scalar(
            text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
            {"name": role_name, "cap": LOCK_FILE_MATERIALIZATION},
        )
        if not has_cap:
            if _old_exact_profile(db, role_name):
                return FileMaterializationEffectPreparation(oid, role_name, False)
            try:
                old_read = _read_profile(db, role_name)
            except WriterControlError:
                old_read = ()
            if old_read and all(old_read):
                return FileMaterializationEffectPreparation(oid, role_name, False)
        flags = _profile(db, role_name)
        if all(flags):
            return FileMaterializationEffectPreparation(oid, role_name, True)
        if any(flags):
            raise WriterControlError("file_materialization_effect_existing_profile_forbidden")
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table, columns in FILE_EFFECT_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            db.execute(
                text(
                    f"GRANT INSERT ({','.join(FILE_EFFECT_INPUT_COLUMNS)}) "
                    f"ON public.{FILE_EFFECT_TABLE} TO {role}"
                )
            )
            for table, columns in FILE_EFFECT_UPDATE_COLUMNS.items():
                db.execute(text(f"GRANT UPDATE ({','.join(columns)}) ON public.{table} TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {LOCK_FILE_MATERIALIZATION} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("file_materialization_effect_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_projection.file_materialization_effect.prepare",
                entity_kind="official_projection_file_materialization_effect",
                entity_id=str(oid),
                summary="Fixed strict Files effect profile prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return FileMaterializationEffectPreparation(oid, role_name, True)
