"""Explicit fresh extraction Source profile and fixed private guard owner.

No existing principal is upgraded, no role is created and no runtime is started.
Only the caller's Core administrative transaction owns preparation and audit.
"""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
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

REQUEST_TABLE = "file_extraction_requests"
ADMIT = "public.miy_file_extraction_admit(uuid)"
RESULT_DIGEST = "public.miy_file_extraction_result_digest(uuid,text)"
_PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
_FUNCTIONS = (
    ADMIT,
    RESULT_DIGEST,
    "public.miy_file_extraction_request_guard()",
    "public.miy_file_extraction_keep_history()",
    "public.miy_file_extraction_seal_terminal()",
)
_TERMINAL_TRIGGER_DEFINITION = (
    "CREATE CONSTRAINT TRIGGER miy_file_extraction_terminal AFTER UPDATE ON "
    "public.file_extraction_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
    "WHEN (((new.state)::text = ANY ((ARRAY['ready'::character varying, "
    "'unsupported'::character varying, 'failed'::character varying])::text[]))) "
    "EXECUTE FUNCTION miy_file_extraction_request_guard()"
)
POLICY_READ_COLUMNS = {
    "users": (
        "id",
        "status",
        "login_blocked",
        "must_change_password",
        "primary_organization_unit_id",
        "display_name",
        "full_name",
    ),
    "user_system_roles": ("user_id", "role"),
    "company_app_controls": ("app_id", "enabled"),
    "app_access_policies": ("app_id", "audience"),
    "app_user_grants": ("app_id", "user_id"),
    "app_group_grants": ("app_id", "group_id"),
    "groups": ("id", "source", "active"),
    "group_members": ("group_id", "user_id"),
    "auth_sessions": ("id", "user_id", "expires_at", "revoked_at", "impersonator_user_id"),
}
_OWNER_READ_TABLES = (
    REQUEST_TABLE,
    "official_writer_principals",
    "file_manager_files",
    "official_projection_outbox",
)
_OWNER_READ_COLUMNS = {
    "file_manager_corpora": ("id", "retrieval_partition_id", "access_scope_kind"),
    "file_manager_file_source_metadata": ("file_id", "source_version", "content_checksum"),
}
# Filled from the fixed owned append migration, never from a mutable old migration.
_BODY_SHA256 = {
    "public.miy_file_extraction_result_digest(uuid,text)": "0c2e69a2fe5d88cf73fad7aab190082c8d0d65236316498d8df36ca1993fc248",
    "public.miy_file_extraction_admit(uuid)": "c35e2c86740756dd69355897e364305366bd485c3d062c94b1de20ae693ef78d",
    "public.miy_file_extraction_request_guard()": "28717702dbb3e7fdd8e014e1bc365fc50147bc1e1479c5d0000fdaea7a14a965",
    "public.miy_file_extraction_keep_history()": "d82b3deae876f69c503812363e6d11b6593ab77d468b5f853595dd928f2b6e83",
    "public.miy_file_extraction_seal_terminal()": "9c6ead78e719252e5121fb16a8c32d9bbecd2cb481debcbd5379b2f02786f588",
}


@dataclass(frozen=True)
class FileExtractionPrincipalPreparation:
    principal: RuntimePrincipal
    profile_prepared: bool


def _create_forbidden(db: Session, name: str) -> None:
    if db.scalar(
        text("""
      SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%'
        AND nspname<>'information_schema' AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))
    """),
        {"name": name},
    ):
        raise WriterControlError("file_extraction_create_forbidden")


def _relations(db: Session):
    return db.execute(
        text("""
      SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
       AND c.relkind IN ('r','p','v','m','f') ORDER BY n.nspname,c.relname
    """)
    )


def _column_profile(db: Session, name: str, oid: int, allowed: tuple[str, ...]) -> tuple[bool, ...]:
    if db.scalar(
        text("SELECT pg_catalog.has_table_privilege(:name,:oid,'SELECT')"),
        {"name": name, "oid": oid},
    ):
        raise WriterControlError("file_extraction_policy_table_select_forbidden")
    flags = []
    for column, granted in db.execute(
        text("""
      SELECT attname,pg_catalog.has_column_privilege(:name,:oid,attnum,'SELECT')
      FROM pg_catalog.pg_attribute WHERE attrelid=:oid AND attnum>0 AND NOT attisdropped
    """),
        {"name": name, "oid": oid},
    ):
        if column in allowed:
            flags.append(bool(granted))
        elif granted:
            raise WriterControlError("file_extraction_policy_column_forbidden")
    if len(flags) != len(allowed):
        raise WriterControlError("file_extraction_policy_schema_invalid")
    return tuple(flags)


def _public_relations_forbidden(db: Session, oid: int) -> None:
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
        raise WriterControlError("file_extraction_public_privilege_forbidden")


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    _create_forbidden(db, name)
    flags = []
    for schema, table, oid in _relations(db):
        allowed = ()
        columns = ()
        if schema == "public":
            if owner:
                if table in _OWNER_READ_TABLES:
                    allowed = ("SELECT",)
                columns = _OWNER_READ_COLUMNS.get(table, ())
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
        forbidden = ",".join(
            p
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
            if p not in allowed and not (p == "SELECT" and columns)
        )
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("file_extraction_existing_privilege_forbidden")
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
            flags.extend(_column_profile(db, name, oid, columns))
    permitted = (*_FUNCTIONS, _PRODUCER_ADMISSION) if owner else (ADMIT, RESULT_DIGEST)
    if db.scalar(
        text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
       WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
        AND ((p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
               AND NOT (:owner AND p.oid=ANY(CAST(:functions AS regprocedure[]))))
         OR (p.prosecdef AND p.oid<>ALL(CAST(:permitted AS regprocedure[]))
               AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
         OR (NOT (:owner AND p.oid=ANY(CAST(:functions AS regprocedure[])))
               AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION'))))
    """),
        {"name": name, "owner": owner, "functions": list(_FUNCTIONS), "permitted": list(permitted)},
    ):
        raise WriterControlError("file_extraction_function_forbidden")
    for signature in (_PRODUCER_ADMISSION,) if owner else (ADMIT, RESULT_DIGEST):
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
        len(_OWNER_READ_TABLES) + sum(map(len, _OWNER_READ_COLUMNS.values())) + 1
        if owner
        else 4 * len(COVERED_SOURCE_TABLES)
        + sum(3 if t in MUTABLE_TRANSPORT_TABLES else 2 for t in WRITER_TRANSPORT_TABLES)
        + len(WRITER_READ_TABLES)
        + 3
        + sum(map(len, POLICY_READ_COLUMNS.values()))
        + 2
    )
    if len(flags) != expected:
        raise WriterControlError("file_extraction_profile_schema_invalid")
    return tuple(flags)


def _functions_contract(db: Session) -> int:
    owners = set()
    for signature in _FUNCTIONS:
        row = db.execute(
            text("""
          SELECT p.proowner::bigint,p.prosecdef,p.proconfig,p.pronargdefaults,l.lanname,
           pg_catalog.pg_get_function_result(p.oid),
           pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
           EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
          WHERE p.oid=pg_catalog.to_regprocedure(:signature)
        """),
            {"signature": signature},
        ).one_or_none()
        expected = (
            signature in (ADMIT, _FUNCTIONS[2], _FUNCTIONS[4]),
            ["search_path=pg_catalog, pg_temp"],
            1 if signature == ADMIT else 0,
            "sql" if signature == RESULT_DIGEST else "plpgsql",
            "void" if signature == ADMIT else "text" if signature == RESULT_DIGEST else "trigger",
            _BODY_SHA256[signature],
            False,
        )
        if row is None or tuple(row[1:]) != expected:
            raise WriterControlError("file_extraction_function_contract_invalid")
        owners.add(row[0])
    if len(owners) != 1:
        raise WriterControlError("file_extraction_owner_mismatch")
    return owners.pop()


def file_extraction_guard_contract(db: Session) -> None:
    if _source_guard(db) != ROLE_GUARD:
        raise WriterControlError("file_extraction_requires_role_guard")
    _guard_contract(db)
    rows = db.execute(
        text("""
      SELECT n.nspname,c.relname,t.tgname,pn.nspname,p.proname,t.tgenabled,t.tgtype,t.tgnargs,t.tgargs,
       t.tgdeferrable,t.tginitdeferred,
       CASE WHEN t.tgname='miy_file_extraction_terminal' THEN
        t.tgconstraint<>0 AND k.contype='t' AND k.conname=t.tgname
        AND k.conrelid=t.tgrelid AND k.confrelid=0
        AND k.condeferrable AND k.condeferred
       ELSE t.tgconstraint=0 END,
       CASE WHEN t.tgname='miy_file_extraction_terminal' THEN pg_catalog.pg_get_triggerdef(t.oid)
        ELSE pg_catalog.pg_get_expr(t.tgqual,t.tgrelid) END
      FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
      LEFT JOIN pg_catalog.pg_constraint k ON k.oid=t.tgconstraint
      WHERE NOT t.tgisinternal AND (t.tgrelid=pg_catalog.to_regclass('public.file_extraction_requests')
       OR t.tgname IN ('miy_file_extraction_writer','miy_file_extraction_request','miy_file_extraction_history','miy_file_extraction_terminal','miy_file_extraction_seal_file','miy_file_extraction_seal_outbox','miy_file_extraction_seal_metadata','miy_file_extraction_seal_corpus'))
    """)
    ).all()
    expected = {
        (
            "public",
            REQUEST_TABLE,
            "miy_file_extraction_writer",
            "public",
            ROLE_GUARD,
            "O",
            62,
            1,
            b"official.suite\0",
        ),
        (
            "public",
            REQUEST_TABLE,
            "miy_file_extraction_request",
            "public",
            "miy_file_extraction_request_guard",
            "O",
            23,
            0,
            b"",
        ),
        (
            "public",
            REQUEST_TABLE,
            "miy_file_extraction_terminal",
            "public",
            "miy_file_extraction_request_guard",
            "O",
            17,
            0,
            b"",
        ),
        (
            "public",
            REQUEST_TABLE,
            "miy_file_extraction_history",
            "public",
            "miy_file_extraction_keep_history",
            "O",
            42,
            0,
            b"",
        ),
    }
    expected.update(
        ("public", table, trigger, "public", "miy_file_extraction_seal_terminal", "O", kind, 0, b"")
        for table, trigger, kind in (
            ("file_manager_files", "miy_file_extraction_seal_file", 27),
            ("official_projection_outbox", "miy_file_extraction_seal_outbox", 7),
            ("file_manager_file_source_metadata", "miy_file_extraction_seal_metadata", 31),
            ("file_manager_corpora", "miy_file_extraction_seal_corpus", 27),
        )
    )
    expected = {
        (*r, True, True, True, _TERMINAL_TRIGGER_DEFINITION)
        if r[2] == "miy_file_extraction_terminal"
        else (*r, False, False, True, None)
        for r in expected
    }
    if {tuple(r) for r in rows} != expected:
        raise WriterControlError("file_extraction_trigger_contract_invalid")
    oid = _functions_contract(db)
    name = db.scalar(text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": oid})
    if (
        name is None
        or _role(db, name, login=False) != oid
        or not all(_profile(db, name, owner=True))
    ):
        raise WriterControlError("file_extraction_owner_unprepared")


def install_file_extraction_guard(
    db: Session, actor: AuthContext, *, guard_owner: str, expected: WriterIdentity
) -> None:
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        if _source_guard(db) != ROLE_GUARD:
            raise WriterControlError("file_extraction_requires_role_guard")
        _guard_contract(db)
        oid = _role(db, guard_owner, login=False)
        _profile(db, guard_owner, owner=True)
        if _functions_contract(db) == oid:
            file_extraction_guard_contract(db)
            return
        role = _identifier(guard_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            for table in _OWNER_READ_TABLES:
                db.execute(text(f"GRANT SELECT ON public.{table} TO {role}"))
            for table, columns in _OWNER_READ_COLUMNS.items():
                db.execute(text(f"GRANT SELECT ({','.join(columns)}) ON public.{table} TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {_PRODUCER_ADMISSION} TO {role}"))
            for signature in _FUNCTIONS:
                db.execute(text(f"ALTER FUNCTION {signature} OWNER TO {role}"))
                db.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            file_extraction_guard_contract(db)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_file_extraction.guard.install",
                entity_kind="official_writer_scope",
                entity_id=expected.scope,
                summary="Fixed Source extraction guard owner prepared during drain",
                payload={"guard_owner": guard_owner, "guard_owner_oid": oid},
            )


def prepare_file_extraction_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    identity: WriterIdentity,
    expected: WriterIdentity,
    expected_state: str,
) -> FileExtractionPrincipalPreparation:
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
            # Exact approved old profiles remain metadata-only, including the
            # earlier fixed company reader. No new table/column/function grant.
            try:
                _runtime_privileges(db, role_name, company_projection=True)
                _sequence_privileges(db, role_name)
            except WriterControlError:
                profile = _profile(db, role_name)
                if not all(profile):
                    raise WriterControlError("file_extraction_existing_profile_forbidden") from None
                file_extraction_guard_contract(db)
                return FileExtractionPrincipalPreparation(existing, True)
            return FileExtractionPrincipalPreparation(existing, False)
        profile = _profile(db, role_name)
        if any(profile):
            raise WriterControlError("file_extraction_existing_profile_forbidden")
        file_extraction_guard_contract(db)
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
            for signature in (ADMIT, RESULT_DIGEST):
                db.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("file_extraction_profile_unprepared")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_file_extraction.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Fresh restricted local Files extraction Source principal prepared",
                payload={
                    "role": role_name,
                    "generation": identity.generation,
                    "artifact": identity.artifact,
                },
            )
        return FileExtractionPrincipalPreparation(principal, True)
