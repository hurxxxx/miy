"""Inactive fixed full-edit ACL profile in the existing Core admin transaction.

The owner checker has a closed 15-table metadata ceiling. This separate adapter
owns the 24-table edit closure and private capability; it never broadens that
checker or the Source/auth profiles. Supplied roles, admin/CAS, catalog attestation
and private failure retain the existing preparation contract. No lifecycle,
credential, factory, or operational role provisioning is selected here.
"""

from dataclasses import dataclass
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_roles import RuntimePrincipal, _identifier, _lock
from miy_api.domains.official_apps.whiteboard_actor_writer_roles import _actor_role, _actor_schema
from miy_api.domains.official_apps.whiteboard_source_writer_roles import (
    CAPABILITY as SERVICE_CAPABILITY,
    _function_contract,
    _identity,
    _oid,
    whiteboard_source_writer_contract,
)

PROFILE = "whiteboard_actor_edit_v1"
CAPABILITY = "public.miy_whiteboard_lock_edit_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
CAPABILITY_BODY_SHA256 = "444fab74ce53c826b764775ba79d65595c301691e8e726a8f9653c9c20a8b070"
OWNER_READ_COLUMNS = {
    "users": (
        "id",
        "status",
        "login_blocked",
        "must_change_password",
        "primary_organization_unit_id",
    ),
    "auth_sessions": ("id", "user_id", "expires_at", "revoked_at", "impersonator_user_id"),
    "user_system_roles": ("user_id", "role"),
    "company_app_controls": ("app_id", "enabled"),
    "app_access_policies": ("app_id", "audience"),
    "app_user_grants": ("app_id", "user_id"),
    "app_group_grants": ("app_id", "group_id"),
    "groups": ("id", "source", "active"),
    "group_members": ("group_id", "user_id"),
    "independent_app_sessions": (
        "token_hash",
        "installation_id",
        "source_session_id",
        "generation",
        "permissions",
        "expires_at",
        "revoked_at",
    ),
    "independent_app_installations": (
        "id",
        "app_id",
        "environment",
        "origin",
        "enabled",
        "audience",
        "user_ids",
        "group_ids",
        "granted_permissions",
        "release_id",
        "state",
        "generation",
        "runtime_ref",
    ),
    "independent_app_releases": (
        "id",
        "app_id",
        "definition_digest",
        "definition_snapshot",
        "source_revision",
        "artifact",
        "verification_id",
        "verified_at",
    ),
    "independent_app_build_verifications": (
        "id",
        "app_id",
        "source_revision",
        "definition_digest",
        "artifact_digest",
        "target_environment",
        "checks",
        "revoked_at",
    ),
    "official_app_bindings": (
        "id",
        "installation_id",
        "generation",
        "release_id",
        "verification_id",
        "artifact",
        "origin",
        "environment",
        "logical_app_ids",
        "revoked_at",
    ),
    "whiteboards": ("id", "owner_id", "trashed_at"),
    "whiteboard_user_shares": ("whiteboard_id", "user_id", "access_level"),
    "whiteboard_group_shares": ("whiteboard_id", "group_id", "access_level"),
    "whiteboard_targets": ("whiteboard_id", "target_app", "target_type", "target_id"),
    "pms_spaces": ("id", "active", "trashed_at"),
    "pms_space_members": ("team_id", "user_id", "role"),
    "pms_space_group_bindings": ("team_id", "group_id", "role"),
    "pms_task_lists": ("id", "team_id", "archived"),
    "meetings": ("id", "organizer_id"),
    "meeting_attendees": ("meeting_id", "user_id"),
}
# PostgreSQL FOR SHARE requires UPDATE on at least one column of each locked
# relation. Only the NOLOGIN definer receives these grants; its body has no DML.
OWNER_LOCK_COLUMNS = {table: (columns[0],) for table, columns in OWNER_READ_COLUMNS.items()}
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


@dataclass(frozen=True)
class WhiteboardActorACLProfile:
    role_oid: int
    role_name: str
    identity: WriterIdentity
    capability_owner_oid: int
    service_capability_owner_oid: int
    producer_owner_oid: int
    source_guard_owner_oid: int

    def __post_init__(self):
        for value in (
            self.role_oid,
            self.capability_owner_oid,
            self.service_capability_owner_oid,
            self.producer_owner_oid,
            self.source_guard_owner_oid,
        ):
            _oid(value)
        if not isinstance(self.role_name, str):
            raise WriterControlError("whiteboard_actor_acl_role_invalid")
        _identifier(self.role_name)
        _identity(self.identity)


@dataclass(frozen=True)
class WhiteboardActorACLPreparation:
    principal: RuntimePrincipal
    writer: WhiteboardActorACLProfile
    profile_prepared: bool = True


def _profile(db: Session, name: str, *, owner: bool = False) -> tuple[bool, ...]:
    oid = _actor_role(db, name, login=not owner)
    _actor_schema(db, name)
    required = set()
    flags = []
    rows = db.execute(
        text("""
      SELECT n.nspname,c.relname,a.attname,
        pg_catalog.has_table_privilege(:name,c.oid,:privileges)
          OR pg_catalog.has_table_privilege(:name,c.oid,:grants),
        CASE WHEN a.attnum IS NULL THEN false
          ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'SELECT') END,
        CASE WHEN a.attnum IS NULL THEN false
          ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'UPDATE') END,
        CASE WHEN a.attnum IS NULL THEN false
          ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'INSERT,REFERENCES')
            OR pg_catalog.has_column_privilege(:name,c.oid,a.attnum,
              'SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION,REFERENCES WITH GRANT OPTION') END
      FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
      WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)(_|$)'
        AND c.relkind IN ('r','p','v','m','f')
    """),
        {
            "name": name,
            "privileges": ",".join(_TABLE_PRIVILEGES),
            "grants": ",".join(p + " WITH GRANT OPTION" for p in _TABLE_PRIVILEGES),
        },
    ).all()
    for schema, table, column, table_forbidden, reads, updates, column_forbidden in rows:
        if table_forbidden or column_forbidden:
            raise WriterControlError("whiteboard_actor_acl_table_privilege_forbidden")
        if column is None:
            continue
        for privilege, granted, manifest in (
            ("SELECT", reads, OWNER_READ_COLUMNS),
            ("UPDATE", updates, OWNER_LOCK_COLUMNS),
        ):
            allowed = owner and schema == "public" and column in manifest.get(table, ())
            if granted and not allowed:
                raise WriterControlError("whiteboard_actor_acl_column_privilege_forbidden")
            if allowed:
                required.add((table, column, privilege))
                flags.append(bool(granted))
    expected = (
        {
            (table, column, privilege)
            for manifest, privilege in (
                (OWNER_READ_COLUMNS, "SELECT"),
                (OWNER_LOCK_COLUMNS, "UPDATE"),
            )
            for table, columns in manifest.items()
            for column in columns
        }
        if owner
        else set()
    )
    if required != expected:
        raise WriterControlError("whiteboard_actor_acl_schema_invalid")
    functions = db.execute(
        text("""
      SELECT p.proowner::bigint,p.prosecdef,
        pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'),
        pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION'),
        p.oid=pg_catalog.to_regprocedure(:cap),p.oid=pg_catalog.to_regprocedure(:service)
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)(_|$)'
    """),
        {"name": name, "cap": CAPABILITY, "service": SERVICE_CAPABILITY},
    ).all()
    for function_owner, definer, execute, grantable, cap, service in functions:
        owns_cap = owner and cap and function_owner == oid
        allowed = cap or (owner and service)
        if (
            (function_owner == oid and not owns_cap)
            or (grantable and not owns_cap)
            or (definer and execute and not allowed)
        ):
            raise WriterControlError("whiteboard_actor_acl_function_privilege_forbidden")
    flags.append(
        bool(
            db.scalar(
                text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
                {"name": name, "cap": SERVICE_CAPABILITY if owner else CAPABILITY},
            )
        )
    )
    if owner:
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:cap,'EXECUTE')"),
                    {"name": name, "cap": CAPABILITY},
                )
            )
        )
    return tuple(flags)


def whiteboard_actor_acl_contract(
    db: Session,
    *,
    capability_owner_oid: int,
    service_capability_owner_oid: int,
    producer_owner_oid: int,
    source_guard_owner_oid: int,
) -> None:
    for value in (
        capability_owner_oid,
        service_capability_owner_oid,
        producer_owner_oid,
        source_guard_owner_oid,
    ):
        _oid(value)
    whiteboard_source_writer_contract(
        db,
        capability_owner_oid=service_capability_owner_oid,
        producer_owner_oid=producer_owner_oid,
        source_guard_owner_oid=source_guard_owner_oid,
    )
    _function_contract(db, CAPABILITY, body=CAPABILITY_BODY_SHA256, owner_oid=capability_owner_oid)
    name = db.scalar(
        text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"),
        {"oid": capability_owner_oid},
    )
    if name is None or not all(_profile(db, name, owner=True)):
        raise WriterControlError("whiteboard_actor_acl_capability_owner_invalid")
    if not db.scalar(
        text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"), {"name": name}
    ):
        raise WriterControlError("whiteboard_actor_acl_schema_usage_required")


def install_whiteboard_actor_acl_guard(
    db: Session,
    actor: AuthContext,
    *,
    guard_owner: str,
    expected: WriterIdentity,
    expected_migration_owner_oid: int,
    expected_service_capability_owner_oid: int,
    expected_producer_owner_oid: int,
    expected_source_guard_owner_oid: int,
) -> None:
    for value in (
        expected_migration_owner_oid,
        expected_service_capability_owner_oid,
        expected_producer_owner_oid,
        expected_source_guard_owner_oid,
    ):
        _oid(value)
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        whiteboard_source_writer_contract(
            db,
            capability_owner_oid=expected_service_capability_owner_oid,
            producer_owner_oid=expected_producer_owner_oid,
            source_guard_owner_oid=expected_source_guard_owner_oid,
        )
        owner_oid = _actor_role(db, guard_owner, login=False)
        kwargs = dict(
            capability_owner_oid=owner_oid,
            service_capability_owner_oid=expected_service_capability_owner_oid,
            producer_owner_oid=expected_producer_owner_oid,
            source_guard_owner_oid=expected_source_guard_owner_oid,
        )
        actual = db.scalar(
            text(
                "SELECT proowner::bigint FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure(:cap)"
            ),
            {"cap": CAPABILITY},
        )
        if actual == owner_oid:
            whiteboard_actor_acl_contract(db, **kwargs)
            return
        if owner_oid == expected_migration_owner_oid:
            raise WriterControlError("whiteboard_actor_acl_fresh_owner_required")
        _function_contract(
            db, CAPABILITY, body=CAPABILITY_BODY_SHA256, owner_oid=expected_migration_owner_oid
        )
        if any(_profile(db, guard_owner, owner=True)):
            raise WriterControlError("whiteboard_actor_acl_existing_owner_profile_forbidden")
        role = _identifier(guard_owner)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            for privilege, manifest in (
                ("SELECT", OWNER_READ_COLUMNS),
                ("UPDATE", OWNER_LOCK_COLUMNS),
            ):
                for table, columns in manifest.items():
                    db.execute(
                        text(f"GRANT {privilege} ({','.join(columns)}) ON public.{table} TO {role}")
                    )
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {SERVICE_CAPABILITY} TO {role}"))
            db.execute(text(f"ALTER FUNCTION {CAPABILITY} OWNER TO {role}"))
            db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            whiteboard_actor_acl_contract(db, **kwargs)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_actor_acl.guard.install",
                entity_kind="official_whiteboard_actor_acl_guard",
                entity_id=str(owner_oid),
                summary="Inactive full-edit actor lock capability prepared",
                payload={"role": guard_owner, "role_oid": owner_oid, "profile": PROFILE},
            )


def prepare_whiteboard_actor_acl_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    identity: WriterIdentity,
    expected: WriterIdentity,
    expected_state: str,
    capability_owner_oid: int,
    service_capability_owner_oid: int,
    producer_owner_oid: int,
    source_guard_owner_oid: int,
) -> WhiteboardActorACLPreparation:
    _identity(identity)
    for value in (
        capability_owner_oid,
        service_capability_owner_oid,
        producer_owner_oid,
        source_guard_owner_oid,
    ):
        _oid(value)
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        whiteboard_actor_acl_contract(
            db,
            capability_owner_oid=capability_owner_oid,
            service_capability_owner_oid=service_capability_owner_oid,
            producer_owner_oid=producer_owner_oid,
            source_guard_owner_oid=source_guard_owner_oid,
        )
        oid = _actor_role(db, role_name, login=True)
        writer = WhiteboardActorACLProfile(
            oid,
            role_name,
            identity,
            capability_owner_oid,
            service_capability_owner_oid,
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
                raise WriterControlError("whiteboard_actor_acl_identity_immutable")
            if not all(flags) or not db.scalar(
                text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                {"name": role_name},
            ):
                raise WriterControlError("whiteboard_actor_acl_existing_profile_forbidden")
            return WhiteboardActorACLPreparation(existing, writer)
        if any(flags):
            raise WriterControlError("whiteboard_actor_acl_fresh_principal_required")
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
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {CAPABILITY} TO {role}"))
            if not all(_profile(db, role_name)):
                raise WriterControlError("whiteboard_actor_acl_profile_incomplete")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_actor_acl.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Fresh DML0 inactive actor principal prepared",
                payload={
                    "role": role_name,
                    "generation": identity.generation,
                    "artifact": identity.artifact,
                    "profile": PROFILE,
                },
            )
        return WhiteboardActorACLPreparation(principal, writer)
