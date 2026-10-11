"""Explicit inactive two-table Whiteboard service profile; no old-role upgrades.

Core supplies fresh LOGIN/NOLOGIN roles and original catalog owner OIDs. These
operations use its existing admin/CAS transaction; they create no credentials,
factory, service, role guard, or user authority. Exact replay is mutation-free.
"""

from dataclasses import dataclass
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import (
    ROLE_GUARD,
    RuntimePrincipal,
    _guard_privileges,
    _identifier,
    _lock,
    _role,
    _source_guard,
)

PROFILE = "whiteboard_source_service_admission_v1"
CAPABILITY = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
SOURCE_GUARD = "public.miy_guard_official_source_writer_by_role()"
PRINCIPAL_GUARD = "public.miy_immutable_official_writer_principal()"
SOURCE_READ_COLUMNS = {
    "whiteboards": ("id", "trashed_at"),
    "whiteboard_collab_documents": (
        "id",
        "whiteboard_id",
        "room_key",
        "yjs_state",
        "updated_at",
        "writer_scope",
    ),
}
SOURCE_UPDATE_COLUMNS = {
    "whiteboards": ("writer_scope",),
    "whiteboard_collab_documents": ("yjs_state", "updated_at", "writer_scope"),
}
PRODUCER_BODY_SHA256 = "14f6b158322d8020ec6ebe2a1bfc728ff1f1091351b33ec5f1dd7874cc0d1617"
SOURCE_GUARD_BODY_SHA256 = "b571f2cc52f5c51cc2dadfd8451ef78406f7c37f724eb6c3f0e8facfee2abcfc"
PRINCIPAL_GUARD_BODY_SHA256 = "e9ec4aba118c8c6aafebe63b0b4a7763e510339874b416a33dc2fd2523f1cf3d"
# Frozen from this slice's additive migration, not discovered from the database.
CAPABILITY_BODY_SHA256 = "ec03287cc2dc8fbe39858a39c7cc6231a8aa77f772b5137eafd18073c6d3e851"
_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)


def _oid(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 4294967295:
        raise WriterControlError("whiteboard_source_writer_owner_invalid")


def _identity(identity: WriterIdentity) -> None:
    if (
        type(identity) is not WriterIdentity
        or identity.scope != SUITE_SCOPE
        or identity.owner != "legacy"
        or identity.artifact is None
    ):
        raise WriterControlError("whiteboard_source_writer_identity_unavailable")


@dataclass(frozen=True)
class WhiteboardSourceWriterProfile:
    role_oid: int
    role_name: str
    identity: WriterIdentity
    capability_owner_oid: int
    producer_owner_oid: int
    source_guard_owner_oid: int

    def __post_init__(self):
        for value in (
            self.role_oid,
            self.capability_owner_oid,
            self.producer_owner_oid,
            self.source_guard_owner_oid,
        ):
            _oid(value)
        if not isinstance(self.role_name, str):
            raise WriterControlError("whiteboard_source_writer_role_name_invalid")
        _identifier(self.role_name)
        _identity(self.identity)


@dataclass(frozen=True)
class WhiteboardSourceWriterPreparation:
    principal: RuntimePrincipal
    writer: WhiteboardSourceWriterProfile
    profile_prepared: bool = True


def _restricted_role(db: Session, name: str, *, login: bool) -> int:
    """Supplement the protected base check with literal system namespaces."""
    oid = _role(db, name, login=login)
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace
          WHERE nspowner=:oid AND nspname !~ '^pg_' AND nspname<>'information_schema')
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relowner=:oid AND n.nspname !~ '^pg_'
              AND n.nspname<>'information_schema')
    """),
        {"oid": oid},
    ):
        raise WriterControlError("whiteboard_source_writer_ownership_forbidden")
    return oid


def _function_contract(
    db: Session,
    signature: str,
    *,
    body: str,
    owner_oid: int,
    result: str = "void",
    definer: bool = True,
) -> int:
    _oid(owner_oid)
    row = db.execute(
        text("""
        SELECT p.oid::bigint,p.proowner::bigint,p.prosecdef,p.proconfig,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
            COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
          pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
          pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
          p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prokind,
          (SELECT count(*) FROM pg_catalog.pg_proc q
            WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname)
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE p.oid=pg_catalog.to_regprocedure(:signature)
    """),
        {"signature": signature},
    ).one_or_none()
    if row is None or tuple(row[1:]) != (
        owner_oid,
        definer,
        ["search_path=pg_catalog, pg_temp"],
        False,
        result,
        0,
        "plpgsql",
        body,
        "v",
        False,
        False,
        "u",
        "f",
        1,
    ):
        raise WriterControlError("whiteboard_source_writer_function_invalid")
    return row[0]


def _schema_ceiling(db: Session, name: str) -> None:
    if db.scalar(
        text("""
        SELECT pg_catalog.has_database_privilege(:name,pg_catalog.current_database(),
          'CREATE,CONNECT WITH GRANT OPTION,TEMPORARY WITH GRANT OPTION')
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace n
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
              AND (pg_catalog.has_schema_privilege(:name,n.oid,
                'CREATE,USAGE WITH GRANT OPTION')
                OR (n.nspname<>'public'
                  AND pg_catalog.has_schema_privilege(:name,n.oid,'USAGE'))))
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
              AND c.relkind='S'
              AND CASE WHEN c.relkind='S'
                THEN pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,USAGE,UPDATE')
                ELSE false END)
    """),
        {"name": name},
    ):
        raise WriterControlError("whiteboard_source_writer_ambient_privilege_forbidden")


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    """Return only required grant flags; refuse any authority outside the ceiling.

    Empty flags admit a supplied fresh role, never a partially prepared binding.
    Ordinary invoker functions are not authority-granting capabilities; executable
    definers, owned functions and all function grant options are checked explicitly.
    """
    oid = _restricted_role(db, name, login=not owner)
    _schema_ceiling(db, name)
    flags = []
    required = set()
    rows = db.execute(
        text("""
        SELECT n.nspname,c.relname,a.attname,
          pg_catalog.has_table_privilege(:name,c.oid,:table_privileges)
            OR pg_catalog.has_table_privilege(:name,c.oid,:table_grants) AS table_forbidden,
          CASE WHEN a.attnum IS NULL THEN false
            ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'SELECT') END AS reads,
          CASE WHEN a.attnum IS NULL THEN false
            ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'UPDATE') END AS updates,
          CASE WHEN a.attnum IS NULL THEN false
            ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'INSERT,REFERENCES')
              OR pg_catalog.has_column_privilege(:name,c.oid,a.attnum,
                'SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION,REFERENCES WITH GRANT OPTION')
          END AS column_forbidden
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
            AND a.attnum>0 AND NOT a.attisdropped
        WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
          AND c.relkind IN ('r','p','v','m','f')
    """),
        {
            "name": name,
            "table_privileges": ",".join(_TABLE_PRIVILEGES),
            "table_grants": ",".join(p + " WITH GRANT OPTION" for p in _TABLE_PRIVILEGES),
        },
    ).all()
    for schema, table, column, table_forbidden, reads, updates, column_forbidden in rows:
        if table_forbidden or column_forbidden:
            raise WriterControlError("whiteboard_source_writer_table_privilege_forbidden")
        if column is None:
            continue
        for privilege, granted in (("SELECT", reads), ("UPDATE", updates)):
            allowed = (
                not owner
                and schema == "public"
                and column
                in (
                    SOURCE_READ_COLUMNS.get(table, ())
                    if privilege == "SELECT"
                    else SOURCE_UPDATE_COLUMNS.get(table, ())
                )
            )
            if granted and not allowed:
                raise WriterControlError("whiteboard_source_writer_column_privilege_forbidden")
            if allowed:
                required.add((table, column, privilege))
                flags.append(bool(granted))
    expected = (
        set()
        if owner
        else {
            (table, column, privilege)
            for manifest, privilege in (
                (SOURCE_READ_COLUMNS, "SELECT"),
                (SOURCE_UPDATE_COLUMNS, "UPDATE"),
            )
            for table, columns in manifest.items()
            for column in columns
        }
    )
    if required != expected:
        raise WriterControlError("whiteboard_source_writer_schema_invalid")
    functions = db.execute(
        text("""
        SELECT p.oid::bigint,p.proowner::bigint,p.prosecdef,
          pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'),
          pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION'),
          p.oid=pg_catalog.to_regprocedure(:cap),
          p.oid=pg_catalog.to_regprocedure(:producer)
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
    """),
        {"name": name, "cap": CAPABILITY, "producer": PRODUCER_ADMISSION},
    ).all()
    for _, function_owner, definer, execute, grantable, cap, producer in functions:
        owns_cap = owner and cap and function_owner == oid
        allowed = cap or (owner and producer)
        if (
            (function_owner == oid and not owns_cap)
            or (grantable and not owns_cap)
            or (definer and execute and not allowed)
        ):
            raise WriterControlError("whiteboard_source_writer_function_privilege_forbidden")
    flags.append(
        bool(
            db.scalar(
                text("SELECT pg_catalog.has_function_privilege(:name,:signature,'EXECUTE')"),
                {"name": name, "signature": PRODUCER_ADMISSION if owner else CAPABILITY},
            )
        )
    )
    if owner:
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:signature,'EXECUTE')"),
                    {"name": name, "signature": CAPABILITY},
                )
            )
        )
    return tuple(flags)


def _guards(db: Session, *, producer_owner_oid: int, source_guard_owner_oid: int) -> None:
    if _source_guard(db) != ROLE_GUARD:
        raise WriterControlError("whiteboard_source_writer_requires_role_guard")
    _function_contract(
        db,
        SOURCE_GUARD,
        body=SOURCE_GUARD_BODY_SHA256,
        owner_oid=source_guard_owner_oid,
        result="trigger",
    )
    name = db.scalar(
        text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"),
        {"oid": source_guard_owner_oid},
    )
    if name is None or _restricted_role(db, name, login=False) != source_guard_owner_oid:
        raise WriterControlError("whiteboard_source_writer_source_guard_owner_invalid")
    _guard_privileges(db, name)
    _schema_ceiling(db, name)
    # The protected broad guard checker uses LIKE 'pg_%'; close that namespace gap
    # locally without replacing its accepted control-table owner contract.
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
            AND c.relkind IN ('r','p','v','m','f')
            AND (pg_catalog.has_table_privilege(:name,c.oid,'MAINTAIN')
              OR (n.nspname LIKE 'pg_%' AND (pg_catalog.has_table_privilege(:name,c.oid,
                'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                OR pg_catalog.has_any_column_privilege(:name,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))))
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
              AND p.oid<>pg_catalog.to_regprocedure(:guard)
              AND (p.proowner=:oid OR (p.prosecdef
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))
                OR pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')))
    """),
        {"name": name, "oid": source_guard_owner_oid, "guard": SOURCE_GUARD},
    ):
        raise WriterControlError("whiteboard_source_writer_source_guard_owner_invalid")
    _function_contract(
        db, PRODUCER_ADMISSION, body=PRODUCER_BODY_SHA256, owner_oid=producer_owner_oid
    )
    _function_contract(
        db,
        PRINCIPAL_GUARD,
        body=PRINCIPAL_GUARD_BODY_SHA256,
        owner_oid=producer_owner_oid,
        result="trigger",
        definer=False,
    )
    row = db.execute(
        text("""
        SELECT n.nspname,c.relname,t.tgenabled,t.tgtype,t.tgnargs,t.tgfoid::bigint
        FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE t.tgname='miy_official_principal_immutable'
    """)
    ).all()
    expected_oid = db.scalar(
        text("SELECT pg_catalog.to_regprocedure(:guard)::bigint"), {"guard": PRINCIPAL_GUARD}
    )
    if len(row) != 1 or tuple(row[0]) != (
        "public",
        "official_writer_principals",
        "O",
        27,
        0,
        expected_oid,
    ):
        raise WriterControlError("whiteboard_source_writer_principal_guard_invalid")


def whiteboard_source_writer_contract(
    db: Session,
    *,
    capability_owner_oid: int,
    producer_owner_oid: int,
    source_guard_owner_oid: int,
) -> None:
    for value in (capability_owner_oid, producer_owner_oid, source_guard_owner_oid):
        _oid(value)
    _guards(
        db, producer_owner_oid=producer_owner_oid, source_guard_owner_oid=source_guard_owner_oid
    )
    _function_contract(db, CAPABILITY, body=CAPABILITY_BODY_SHA256, owner_oid=capability_owner_oid)
    name = db.scalar(
        text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"),
        {"oid": capability_owner_oid},
    )
    if name is None or not all(_profile(db, name, owner=True)):
        raise WriterControlError("whiteboard_source_writer_capability_owner_invalid")
    if not db.scalar(
        text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"), {"name": name}
    ):
        raise WriterControlError("whiteboard_source_writer_schema_usage_required")


def install_whiteboard_source_writer_guard(
    db: Session,
    actor: AuthContext,
    *,
    guard_owner: str,
    expected: WriterIdentity,
    expected_migration_owner_oid: int,
    expected_producer_owner_oid: int,
    expected_source_guard_owner_oid: int,
) -> None:
    for value in (
        expected_migration_owner_oid,
        expected_producer_owner_oid,
        expected_source_guard_owner_oid,
    ):
        _oid(value)
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        _guards(
            db,
            producer_owner_oid=expected_producer_owner_oid,
            source_guard_owner_oid=expected_source_guard_owner_oid,
        )
        owner_oid = _restricted_role(db, guard_owner, login=False)
        actual = db.scalar(
            text(
                "SELECT proowner::bigint FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure(:cap)"
            ),
            {"cap": CAPABILITY},
        )
        if actual == owner_oid:
            whiteboard_source_writer_contract(
                db,
                capability_owner_oid=owner_oid,
                producer_owner_oid=expected_producer_owner_oid,
                source_guard_owner_oid=expected_source_guard_owner_oid,
            )
            return
        if owner_oid == expected_migration_owner_oid:
            raise WriterControlError("whiteboard_source_writer_fresh_owner_required")
        _function_contract(
            db, CAPABILITY, body=CAPABILITY_BODY_SHA256, owner_oid=expected_migration_owner_oid
        )
        if any(_profile(db, guard_owner, owner=True)):
            raise WriterControlError("whiteboard_source_writer_existing_owner_profile_forbidden")
        role = _identifier(guard_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {PRODUCER_ADMISSION} TO {role}"))
            db.execute(text(f"ALTER FUNCTION {CAPABILITY} OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            whiteboard_source_writer_contract(
                db,
                capability_owner_oid=owner_oid,
                producer_owner_oid=expected_producer_owner_oid,
                source_guard_owner_oid=expected_source_guard_owner_oid,
            )
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_source_writer.guard.install",
                entity_kind="official_whiteboard_source_writer_guard",
                entity_id=str(owner_oid),
                summary="Private inactive Whiteboard service admission owner prepared",
                payload={"role": guard_owner, "role_oid": owner_oid, "profile": PROFILE},
            )


def prepare_whiteboard_source_writer_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    identity: WriterIdentity,
    expected: WriterIdentity,
    expected_state: str,
    capability_owner_oid: int,
    producer_owner_oid: int,
    source_guard_owner_oid: int,
) -> WhiteboardSourceWriterPreparation:
    _identity(identity)
    for value in (capability_owner_oid, producer_owner_oid, source_guard_owner_oid):
        _oid(value)
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        whiteboard_source_writer_contract(
            db,
            capability_owner_oid=capability_owner_oid,
            producer_owner_oid=producer_owner_oid,
            source_guard_owner_oid=source_guard_owner_oid,
        )
        oid = _restricted_role(db, role_name, login=True)
        writer = WhiteboardSourceWriterProfile(
            oid,
            role_name,
            identity,
            capability_owner_oid,
            producer_owner_oid,
            source_guard_owner_oid,
        )
        existing = db.scalar(
            select(RuntimePrincipal)
            .where((RuntimePrincipal.role_oid == oid) | (RuntimePrincipal.role_name == role_name))
            .execution_options(populate_existing=True)
        )
        flags = _profile(db, role_name)
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
                raise WriterControlError("whiteboard_source_writer_identity_immutable")
            if not all(flags):
                raise WriterControlError("whiteboard_source_writer_existing_profile_forbidden")
            if not db.scalar(
                text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                {"name": role_name},
            ):
                raise WriterControlError("whiteboard_source_writer_schema_usage_required")
            return WhiteboardSourceWriterPreparation(existing, writer)
        if any(flags):
            raise WriterControlError("whiteboard_source_writer_fresh_principal_required")
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
            for privilege, manifest in (
                ("SELECT", SOURCE_READ_COLUMNS),
                ("UPDATE", SOURCE_UPDATE_COLUMNS),
            ):
                for table, columns in manifest.items():
                    db.execute(
                        text(f"GRANT {privilege} ({','.join(columns)}) ON public.{table} TO {role}")
                    )
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {CAPABILITY} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("whiteboard_source_writer_profile_incomplete")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_source_writer.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Fresh inactive two-table Whiteboard service principal prepared",
                payload={
                    "role": role_name,
                    "generation": identity.generation,
                    "artifact": identity.artifact,
                    "profile": PROFILE,
                },
            )
        return WhiteboardSourceWriterPreparation(principal, writer)
