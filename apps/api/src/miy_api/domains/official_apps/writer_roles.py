"""Explicit core preparation of a restricted PostgreSQL writer principal.

No credentials, role creation, endpoint, startup hook or service activation live
here. The caller supplies pre-provisioned roles and commits its core transaction.
The existing cooperative guard stays installed until an explicit draining cutover.
"""

from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.writer import (
    WriterControlError,
    WriterIdentity,
    _admin,
    snapshot,
)
from miy_api.domains.official_apps.writer_contracts import (
    COVERED_SOURCE_TABLES,
    SUITE_SCOPE,
    MUTABLE_TRANSPORT_TABLES,
    WRITER_READ_TABLES,
)
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.official_apps.projection_contracts import WRITER_TRANSPORT_TABLES

ROLE_GUARD = "miy_guard_official_source_writer_by_role"
LEGACY_GUARD = "miy_guard_official_source_writer"
CONTROL_TABLES = (
    "official_runtime_ownership",
    "official_runtime_transitions",
    "official_writer_principals",
    "audit_logs",
)


class RuntimePrincipal(Base):
    __tablename__ = "official_writer_principals"
    __table_args__ = (
        CheckConstraint("role_oid > 0", name="ck_official_principal_oid"),
        CheckConstraint("scope = 'official.suite'", name="ck_official_principal_scope"),
        CheckConstraint("owner = 'legacy'", name="ck_official_principal_owner"),
        CheckConstraint("generation >= 1", name="ck_official_principal_generation"),
        CheckConstraint(
            "artifact ~ '^sha256:[a-f0-9]{64}$'", name="ck_official_principal_artifact"
        ),
    )
    role_oid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_name: Mapped[str] = mapped_column(String(63), unique=True)
    scope: Mapped[str] = mapped_column(ForeignKey("official_runtime_ownership.scope"))
    owner: Mapped[str] = mapped_column(String(32))
    generation: Mapped[int] = mapped_column(Integer)
    artifact: Mapped[str] = mapped_column(String(71))
    approved_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def _identifier(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise WriterControlError("writer_role_name_invalid")
    return '"' + name + '"'


def _role(db: Session, name: str, *, login: bool) -> int:
    _identifier(name)
    role = db.execute(
        text("""
        SELECT oid::bigint, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
               rolreplication, rolbypassrls, rolinherit
        FROM pg_catalog.pg_roles WHERE rolname=:name
    """),
        {"name": name},
    ).one_or_none()
    if role is None or tuple(role[1:]) != (login, False, False, False, False, False, False):
        raise WriterControlError("writer_role_attributes_invalid")
    if db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=:oid OR roleid=:oid)"
        ),
        {"oid": role[0]},
    ):
        raise WriterControlError("writer_role_membership_forbidden")
    if db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datdba=:oid) OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=:oid AND nspname NOT LIKE 'pg_%') OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE c.relowner=:oid AND n.nspname NOT LIKE 'pg_%')"
        ),
        {"oid": role[0]},
    ):
        raise WriterControlError("writer_role_ownership_forbidden")
    if db.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_parameter_acl p
            WHERE pg_catalog.has_parameter_privilege(:name,p.parname,'SET,ALTER SYSTEM'))
    """),
        {"name": name},
    ):
        raise WriterControlError("writer_role_parameter_privilege_forbidden")
    return role[0]


def _runtime_privileges(db: Session, name: str, *, company_projection: bool = False) -> None:
    # Effective privileges include membership and PUBLIC; never silently revoke
    # unexpected existing authority or "repair" a shared cluster.
    if db.scalar(
        text(
            "SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE') OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))"
        ),
        {"name": name},
    ):
        raise WriterControlError("writer_role_create_forbidden")
    relations = db.execute(
        text(
            "SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND c.relkind IN ('r','p','v','m','f')"
        )
    ).all()
    for schema, table, oid in relations:
        allowed = schema == "public" and table in COVERED_SOURCE_TABLES
        forbidden = (
            "TRUNCATE,REFERENCES,TRIGGER"
            if allowed
            else "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        )
        if schema == "public" and table in WRITER_TRANSPORT_TABLES:
            forbidden = (
                "DELETE,TRUNCATE,REFERENCES,TRIGGER"
                if table in MUTABLE_TRANSPORT_TABLES
                else "UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
            )
        if schema == "public" and table in WRITER_READ_TABLES:
            forbidden = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if table in CONTROL_TABLES:
            forbidden += ",SELECT"
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("writer_role_existing_privilege_forbidden")
    from miy_api.domains.official_apps.projection_partition_roles import READ_COMPANY_PARTITION

    if db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name) OR (p.prosecdef AND p.oid<>COALESCE(pg_catalog.to_regprocedure(:reader),0::oid) AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE')) OR pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')))"
        ),
        {"name": name, "reader": READ_COMPANY_PARTITION if company_projection else None},
    ):
        raise WriterControlError("writer_role_function_privilege_forbidden")


def _guard_privileges(db: Session, name: str) -> None:
    """Reject ambient authority, including PUBLIC grants; never repair it."""
    if db.scalar(
        text(
            "SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE') OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))"
        ),
        {"name": name},
    ):
        raise WriterControlError("writer_role_create_forbidden")
    for schema, table, oid in db.execute(
        text(
            "SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND c.relkind IN ('r','p','v','m','f')"
        )
    ):
        lock_table = schema == "public" and table in {
            "official_runtime_ownership",
            "official_writer_principals",
        }
        forbidden = (
            "INSERT,DELETE,TRUNCATE,REFERENCES,TRIGGER"
            if lock_table
            else "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        )
        if _table_privilege_forbidden(db, name, oid, forbidden):
            raise WriterControlError("writer_role_existing_privilege_forbidden")
    if db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND p.oid <> 'public.miy_guard_official_source_writer_by_role()'::regprocedure AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name) OR (p.prosecdef AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))))"
        ),
        {"name": name},
    ):
        raise WriterControlError("writer_role_function_privilege_forbidden")
    _sequence_privileges(db, name)


def _table_privilege_forbidden(db: Session, name: str, oid: int, forbidden: str) -> bool:
    # Table ACL checks do not include column-only grants. Existing grant options
    # are also forbidden: a source runtime must not delegate privileges to others.
    columns = ",".join(
        privilege
        for privilege in forbidden.split(",")
        if privilege in {"SELECT", "INSERT", "UPDATE", "REFERENCES"}
    )
    return bool(
        db.scalar(
            text("""
        SELECT pg_catalog.has_table_privilege(:name,:oid,:forbidden)
            OR pg_catalog.has_any_column_privilege(:name,:oid,:columns)
            OR pg_catalog.has_table_privilege(:name,:oid,
                'SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION,DELETE WITH GRANT OPTION')
            OR pg_catalog.has_any_column_privilege(:name,:oid,
                'SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION')
    """),
            {"name": name, "oid": oid, "forbidden": forbidden, "columns": columns},
        )
    )


def _sequence_privileges(db: Session, name: str) -> None:
    if db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND CASE WHEN c.relkind='S' THEN pg_catalog.has_sequence_privilege(:name,c.oid,'SELECT,USAGE,UPDATE') ELSE false END)"
        ),
        {"name": name},
    ):
        raise WriterControlError("writer_role_sequence_privilege_forbidden")


def _guard_contract(db: Session) -> None:
    row = db.execute(
        text(
            "SELECT p.prosecdef,p.proconfig,EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') FROM pg_catalog.pg_proc p WHERE p.oid='public.miy_guard_official_source_writer_by_role()'::regprocedure"
        )
    ).one()
    if not row[0] or row[1] != ["search_path=pg_catalog, pg_temp"] or row[2]:
        raise WriterControlError("writer_role_guard_contract_invalid")


def _source_guard(db: Session) -> str:
    """Check the complete migrated source boundary while ownership is locked."""
    rows = db.execute(
        text("""
        SELECT c.relname,p.proname,pn.nspname,t.tgenabled,t.tgtype,t.tgnargs,
               t.tgargs=decode('6f6666696369616c2e737569746500','hex')
        FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
        WHERE n.nspname='public' AND t.tgname='miy_official_source_writer'
        """)
    ).all()
    guards = {row[1] for row in rows}
    if (
        {row[0] for row in rows} != set((*COVERED_SOURCE_TABLES, *WRITER_TRANSPORT_TABLES))
        or len(guards) != 1
        or not guards <= {LEGACY_GUARD, ROLE_GUARD}
        or any(tuple(row[2:]) != ("public", "O", 62, 1, True) for row in rows)
    ):
        raise WriterControlError("writer_role_trigger_inventory_invalid")
    if WRITER_TRANSPORT_TABLES:
        _transport_guard_contract(db)
    if "recording_stage_commands" in WRITER_TRANSPORT_TABLES:
        from miy_api.domains.official_apps.recording_roles import guard_contract

        guard_contract(db)
    return guards.pop()


def _transport_guard_contract(db: Session) -> None:
    rows = db.execute(
        text("""
      SELECT c.relname,t.tgname,p.proname,pn.nspname,t.tgenabled,t.tgtype,t.tgnargs,
             p.prosecdef,p.proconfig,
             EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
      FROM pg_catalog.pg_trigger t
      JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
      JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
      WHERE n.nspname='public' AND t.tgname IN ('miy_official_projection_stamp','miy_official_projection_immutable')
    """)
    ).all()
    expected = {
        (
            "official_projection_outbox",
            "miy_official_projection_stamp",
            "miy_stamp_official_projection_event",
            "public",
            "O",
            7,
            0,
            True,
            ("search_path=pg_catalog, pg_temp",),
            False,
        ),
        *(
            (
                table,
                "miy_official_projection_immutable",
                "miy_keep_official_projection_immutable",
                "public",
                "O",
                58,
                0,
                False,
                ("search_path=pg_catalog, pg_temp",),
                False,
            )
            for table in ("official_projection_outbox", "official_projection_receipts")
        ),
    }
    actual = {(*row[:8], tuple(row[8] or ()), row[9]) for row in rows}
    if actual != expected:
        raise WriterControlError("writer_transport_guard_contract_invalid")


def _lock(db: Session, actor: AuthContext, expected: WriterIdentity, state: str) -> AuthContext:
    if db.new or db.dirty or db.deleted:
        raise WriterControlError("writer_role_requires_clean_transaction")
    # Refreshing ORM objects cannot escape a REPEATABLE READ snapshot. These
    # control operations require a new snapshot for the post-wait authority read.
    if (
        db.connection().connection.driver_connection.autocommit is True
        or db.scalar(text("SHOW transaction_isolation")) != "read committed"
    ):
        raise WriterControlError("writer_role_requires_read_committed")
    _admin(db, actor)
    row = db.scalar(
        select(RuntimeOwnership)
        .where(RuntimeOwnership.scope == SUITE_SCOPE)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current = _admin(db, actor)
    if row is None or snapshot(row) != {
        "scope": expected.scope,
        "owner": expected.owner,
        "generation": expected.generation,
        "artifact": expected.artifact,
        "state": state,
    }:
        raise WriterControlError("writer_compare_and_swap_conflict")
    return current


def prepare_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    identity: WriterIdentity,
    expected: WriterIdentity,
    expected_state: str,
    company_projection: bool = False,
) -> RuntimePrincipal:
    """Bind one pre-provisioned LOGIN role once; grant only the catalogued source tables.

    This records core's asserted artifact association, not deployment approval or
    artifact attestation. Never reuse a role for another artifact/generation.
    """
    if type(company_projection) is not bool:
        raise WriterControlError("writer_role_profile_invalid")
    if identity.owner != "legacy" or identity.artifact is None:
        raise WriterControlError("writer_role_identity_unavailable")
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        _runtime_privileges(db, role_name, company_projection=company_projection)
        _sequence_privileges(db, role_name)
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
            return existing
        # A new binary must not grant its expanded source list against an older
        # schema that has not fenced those tables yet. Existing exact replay
        # above remains metadata-only and never expands historical grants.
        guard = _source_guard(db)
        if guard == ROLE_GUARD:
            _guard_contract(db)
        if company_projection:
            from miy_api.domains.official_apps.projection_partition_roles import (
                company_partition_capability_contract,
            )

            if guard != ROLE_GUARD:
                raise WriterControlError("official_projection_partition_requires_role_guard")
            company_partition_capability_contract(db)
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
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {_identifier(role_name)}"))
            for table in COVERED_SOURCE_TABLES:
                db.execute(
                    text(
                        f"GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {_identifier(role_name)}"
                    )
                )
            for table in WRITER_TRANSPORT_TABLES:
                privileges = (
                    "SELECT,INSERT,UPDATE" if table in MUTABLE_TRANSPORT_TABLES else "SELECT,INSERT"
                )
                db.execute(
                    text(f"GRANT {privileges} ON public.{table} TO {_identifier(role_name)}")
                )
            if "recording_stage_commands" in WRITER_TRANSPORT_TABLES:
                for table in WRITER_READ_TABLES:
                    db.execute(text(f"GRANT SELECT ON public.{table} TO {_identifier(role_name)}"))
            if company_projection:
                from miy_api.domains.official_apps.projection_partition_roles import (
                    READ_COMPANY_PARTITION,
                )

                db.execute(
                    text(
                        f"GRANT EXECUTE ON FUNCTION {READ_COMPANY_PARTITION} TO {_identifier(role_name)}"
                    )
                )
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_writer.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Restricted writer principal prepared",
                payload={
                    "role": role_name,
                    "generation": identity.generation,
                    "artifact": identity.artifact,
                },
            )
        return principal


def revoke_principal(
    db: Session, actor: AuthContext, *, role_oid: int, expected: WriterIdentity, expected_state: str
) -> None:
    with db.no_autoflush:
        _lock(db, actor, expected, expected_state)
        principal = db.scalar(
            select(RuntimePrincipal)
            .where(RuntimePrincipal.role_oid == role_oid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = _admin(db, actor)
        if principal is None:
            raise WriterControlError("writer_role_missing")
        if principal.revoked_at is not None:
            return
        principal.revoked_at = utcnow_naive()
        record_audit_log(
            db,
            actor_user_id=current.user.id,
            action="official_writer.principal.revoke",
            entity_kind="official_writer_principal",
            entity_id=str(role_oid),
            summary="Restricted writer principal revoked",
        )
        db.flush()


def install_role_guard(
    db: Session, actor: AuthContext, *, guard_owner: str, expected: WriterIdentity
) -> None:
    """Explicit core DDL after drain; migration alone never changes legacy traffic.

    Preparation does not reopen writes, choose the next owner, supply credentials
    or activate the official service. Existing CAS remains the only core owner API.
    """
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        owner_oid = _role(db, guard_owner, login=False)
        _guard_privileges(db, guard_owner)
        _guard_contract(db)
        role = _identifier(guard_owner)
        if _source_guard(db) == ROLE_GUARD:
            if (
                db.scalar(
                    text(
                        "SELECT proowner::bigint FROM pg_catalog.pg_proc WHERE oid='public.miy_guard_official_source_writer_by_role()'::regprocedure"
                    )
                )
                != owner_oid
            ):
                raise WriterControlError("writer_role_guard_owner_mismatch")
            return
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            db.execute(
                text(
                    f"GRANT SELECT,UPDATE ON public.official_runtime_ownership,public.official_writer_principals TO {role}"
                )
            )
            db.execute(text(f"ALTER FUNCTION public.{ROLE_GUARD}() OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            db.execute(text(f"REVOKE ALL ON FUNCTION public.{ROLE_GUARD}() FROM PUBLIC"))
            for table in (*COVERED_SOURCE_TABLES, *WRITER_TRANSPORT_TABLES):
                db.execute(text(f"DROP TRIGGER miy_official_source_writer ON public.{table}"))
                db.execute(
                    text(
                        f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.{ROLE_GUARD}('official.suite')"
                    )
                )
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_writer.role_guard.install",
                entity_kind="official_writer_scope",
                entity_id=SUITE_SCOPE,
                summary="Restricted writer role guard installed after drain",
                payload={
                    "guard_owner_oid": owner_oid,
                    "guard_owner": guard_owner,
                    "generation": expected.generation,
                },
            )
