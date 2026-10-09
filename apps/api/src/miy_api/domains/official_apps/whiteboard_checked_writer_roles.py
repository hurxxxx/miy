"""Inactive supplied-role contracts for Core-sealed checked Whiteboard storage.

This adapter owns new exact ledger/content ceilings. It reuses the existing Core
admin/CAS and role/schema/catalog primitives; it never expands an old profile,
provisions roles/credentials, selects a factory, commits, or activates native IO.
"""

from dataclasses import dataclass
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin
from miy_api.domains.official_apps.writer_roles import RuntimePrincipal, _identifier, _lock
from miy_api.domains.official_apps.whiteboard_actor_writer_roles import _actor_role, _actor_schema
from miy_api.domains.official_apps.whiteboard_actor_acl_writer_roles import (
    whiteboard_actor_acl_contract,
    CAPABILITY as ACL_CAPABILITY,
)
from miy_api.domains.official_apps.whiteboard_source_writer_roles import (
    _function_contract,
    _identity,
    _oid,
)

SOURCE_PROFILE = "whiteboard_checked_source_v1"
CORE_PROFILE = "whiteboard_checked_core_v1"
COMPOSITION_EPOCH = "whiteboard_checked_cas_v1"
SEAL_CAPABILITY = "public.miy_whiteboard_seal_checked(uuid,bigint,text,integer,text,text,text,text,uuid,bigint,bytea,jsonb,bigint,jsonb)"
SAVE_CAPABILITY = "public.miy_whiteboard_save_checked(uuid,text)"
RESOLVE_CAPABILITY = "public.miy_whiteboard_resolve_checked(uuid,text)"
REVISION_TRIGGER = "public.miy_whiteboard_content_revision()"
IMMUTABLE_TRIGGER = "public.miy_whiteboard_checked_immutable()"
PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
FUNCTION_CONTRACTS = {
    "public.miy_whiteboard_seal_checked(uuid,bigint,text,integer,text,text,text,text,uuid,bigint,bytea,jsonb,bigint,jsonb)": (
        "f66042b10d7448a385347a6a5249c000be830413a9af3d9b7aace9c80ab230ef",
        "jsonb",
        True,
    ),
    "public.miy_whiteboard_save_checked(uuid,text)": (
        "4abf366e359b5044fd6b3513f79886aebb23c9ada0b19ab99d187dea5f5474f8",
        "jsonb",
        True,
    ),
    "public.miy_whiteboard_resolve_checked(uuid,text)": (
        "44c5694ba98218625ed7ecf693ea4a5d6315cff07951fa653c283602f02e3e1a",
        "jsonb",
        True,
    ),
    "public.miy_whiteboard_content_revision()": (
        "cad7d4f3bf36655a29bd59ded03cf19ec971e96cbd3c5bb0e6c10eb4f43308e2",
        "trigger",
        False,
    ),
    "public.miy_whiteboard_checked_immutable()": (
        "2b65a5858afe4d062ec4e22032f96004b14e063a8790eeac97d62d009b5e9d82",
        "trigger",
        False,
    ),
}
FUNCTION_ARGUMENTS = {
    SEAL_CAPABILITY: [
        "requested_attempt",
        "expected_source_oid",
        "expected_source_name",
        "service_generation",
        "service_artifact",
        "requested_board",
        "requested_collab",
        "requested_room",
        "expected_incarnation",
        "expected_revision",
        "requested_yjs",
        "requested_snapshot",
        "requested_cutoff",
        "requested_contributors",
    ],
    SAVE_CAPABILITY: ["requested_attempt", "expected_digest"],
    RESOLVE_CAPABILITY: ["requested_attempt", "expected_digest"],
    REVISION_TRIGGER: None,
    IMMUTABLE_TRIGGER: None,
}


SOURCE_READ_COLUMNS = {
    "whiteboard_checked_attempts": [
        "attempt_id",
        "request_digest",
        "seal_role_oid",
        "seal_role_name",
        "source_role_oid",
        "source_role_name",
        "service_generation",
        "service_artifact",
        "composition_epoch",
        "whiteboard_id",
        "collab_id",
        "room_key",
        "content_incarnation_id",
        "base_revision",
        "yjs_state",
        "snapshot_scene",
        "payload_digest",
        "cohort_cutoff",
        "contributor_count",
        "state",
        "result_incarnation_id",
        "result_revision",
        "sealed_at",
        "completed_at",
    ],
    "whiteboard_checked_contributors": [
        "attempt_id",
        "ordinal",
        "delegated_token_digest",
        "actor_user_id",
        "source_session_id",
        "installation_id",
        "installation_generation",
        "binding_id",
        "release_id",
        "verification_id",
        "execution_artifact",
        "origin",
        "environment",
        "database_name",
        "database_oid",
        "server_address",
        "server_port",
    ],
    "whiteboard_collab_documents": [
        "id",
        "whiteboard_id",
        "room_key",
        "yjs_state",
        "snapshot_scene",
        "updated_at",
        "writer_scope",
        "content_incarnation_id",
        "content_revision",
    ],
    "auth_sessions": ["id", "expires_at"],
    "independent_app_sessions": ["token_hash", "expires_at"],
}
SOURCE_UPDATE_COLUMNS = {
    "whiteboard_checked_attempts": [
        "state",
        "result_incarnation_id",
        "result_revision",
        "completed_at",
    ],
    "whiteboard_collab_documents": ["yjs_state", "snapshot_scene", "updated_at", "writer_scope"],
}
CORE_READ_COLUMNS = {
    "whiteboard_checked_attempts": [
        "attempt_id",
        "request_digest",
        "seal_role_oid",
        "seal_role_name",
        "source_role_oid",
        "source_role_name",
        "service_generation",
        "service_artifact",
        "composition_epoch",
        "whiteboard_id",
        "collab_id",
        "room_key",
        "content_incarnation_id",
        "base_revision",
        "yjs_state",
        "snapshot_scene",
        "payload_digest",
        "cohort_cutoff",
        "contributor_count",
        "state",
        "result_incarnation_id",
        "result_revision",
        "sealed_at",
        "completed_at",
    ],
    "whiteboard_checked_contributors": [
        "attempt_id",
        "ordinal",
        "delegated_token_digest",
        "actor_user_id",
        "source_session_id",
        "installation_id",
        "installation_generation",
        "binding_id",
        "release_id",
        "verification_id",
        "execution_artifact",
        "origin",
        "environment",
        "database_name",
        "database_oid",
        "server_address",
        "server_port",
    ],
}
CORE_INSERT_COLUMNS = {
    "whiteboard_checked_attempts": [
        "attempt_id",
        "request_digest",
        "seal_role_oid",
        "seal_role_name",
        "source_role_oid",
        "source_role_name",
        "service_generation",
        "service_artifact",
        "composition_epoch",
        "whiteboard_id",
        "collab_id",
        "room_key",
        "content_incarnation_id",
        "base_revision",
        "yjs_state",
        "snapshot_scene",
        "payload_digest",
        "cohort_cutoff",
        "contributor_count",
        "state",
        "sealed_at",
    ],
    "whiteboard_checked_contributors": [
        "attempt_id",
        "ordinal",
        "delegated_token_digest",
        "actor_user_id",
        "source_session_id",
        "installation_id",
        "installation_generation",
        "binding_id",
        "release_id",
        "verification_id",
        "execution_artifact",
        "origin",
        "environment",
        "database_name",
        "database_oid",
        "server_address",
        "server_port",
    ],
}
CORE_UPDATE_COLUMNS = {"whiteboard_checked_attempts": ["state", "completed_at"]}
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
class WhiteboardCheckedProfile:
    role_oid: int
    role_name: str
    identity: WriterIdentity
    kind: str
    source_owner_oid: int
    core_owner_oid: int
    acl_owner_oid: int
    service_capability_owner_oid: int
    producer_owner_oid: int
    source_guard_owner_oid: int
    trigger_owner_oid: int

    def __post_init__(self):
        for value in (
            self.role_oid,
            self.source_owner_oid,
            self.core_owner_oid,
            self.acl_owner_oid,
            self.service_capability_owner_oid,
            self.producer_owner_oid,
            self.source_guard_owner_oid,
            self.trigger_owner_oid,
        ):
            _oid(value)
        if not isinstance(self.role_name, str):
            raise WriterControlError("whiteboard_checked_profile_invalid")
        _identifier(self.role_name)
        _identity(self.identity)
        if self.kind not in ("source", "core") or self.source_owner_oid == self.core_owner_oid:
            raise WriterControlError("whiteboard_checked_profile_invalid")


@dataclass(frozen=True)
class WhiteboardCheckedPreparation:
    principal: RuntimePrincipal
    writer: WhiteboardCheckedProfile
    profile_prepared: bool = True


def _profile(db, name, *, kind, owner=False):
    if kind not in ("source", "core"):
        raise WriterControlError("whiteboard_checked_profile_invalid")
    oid = _actor_role(db, name, login=not owner)
    _actor_schema(db, name)
    manifests = (
        {
            "SELECT": SOURCE_READ_COLUMNS if kind == "source" else CORE_READ_COLUMNS,
            "UPDATE": SOURCE_UPDATE_COLUMNS if kind == "source" else CORE_UPDATE_COLUMNS,
            "INSERT": {} if kind == "source" else CORE_INSERT_COLUMNS,
        }
        if owner
        else {"SELECT": {}, "UPDATE": {}, "INSERT": {}}
    )
    rows = db.execute(
        text("""
      SELECT n.nspname,c.relname,a.attname,
        pg_catalog.has_table_privilege(:name,c.oid,:privileges) OR pg_catalog.has_table_privilege(:name,c.oid,:grants),
        CASE WHEN a.attnum IS NULL THEN false ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'SELECT') END,
        CASE WHEN a.attnum IS NULL THEN false ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'UPDATE') END,
        CASE WHEN a.attnum IS NULL THEN false ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'INSERT') END,
        CASE WHEN a.attnum IS NULL THEN false ELSE pg_catalog.has_column_privilege(:name,c.oid,a.attnum,'REFERENCES,SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION,REFERENCES WITH GRANT OPTION') END
      FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
      WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)(_|$)' AND c.relkind IN ('r','p','v','m','f')
    """),
        {
            "name": name,
            "privileges": ",".join(_TABLE_PRIVILEGES),
            "grants": ",".join(x + " WITH GRANT OPTION" for x in _TABLE_PRIVILEGES),
        },
    ).all()
    required = set()
    flags = []
    for schema, table, column, forbidden, reads, updates, inserts, grantable in rows:
        if forbidden or grantable:
            raise WriterControlError("whiteboard_checked_table_privilege_forbidden")
        if column is None:
            continue
        for privilege, granted in (("SELECT", reads), ("UPDATE", updates), ("INSERT", inserts)):
            allowed = schema == "public" and column in manifests[privilege].get(table, ())
            if granted and not allowed:
                raise WriterControlError("whiteboard_checked_column_privilege_forbidden")
            if allowed:
                required.add((table, column, privilege))
                flags.append(bool(granted))
    expected = {
        (table, column, privilege)
        for privilege, manifest in manifests.items()
        for table, columns in manifest.items()
        for column in columns
    }
    if required != expected:
        raise WriterControlError("whiteboard_checked_schema_invalid")
    owned = {SAVE_CAPABILITY} if kind == "source" else {SEAL_CAPABILITY, RESOLVE_CAPABILITY}
    dependencies = {ACL_CAPABILITY} if kind == "source" else {PRODUCER_ADMISSION}
    allowed = owned | (dependencies if owner else set())
    functions = db.execute(
        text("""
      SELECT p.oid::bigint,p.proowner::bigint,p.prosecdef,
        pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'),pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE WITH GRANT OPTION')
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)(_|$)'
    """),
        {"name": name},
    ).all()
    function_oids = {
        signature: db.scalar(
            text("SELECT pg_catalog.to_regprocedure(:signature)::oid::bigint"),
            {"signature": signature},
        )
        for signature in allowed
    }
    owned_oids = {function_oids[x] for x in owned}
    for function_oid, function_owner, definer, execute, grantable in functions:
        owns = owner and function_oid in owned_oids and function_owner == oid
        if (
            (function_owner == oid and not owns)
            or (grantable and not owns)
            or (definer and execute and function_oid not in function_oids.values())
        ):
            raise WriterControlError("whiteboard_checked_function_privilege_forbidden")
    for signature in sorted(allowed):
        flags.append(
            bool(
                db.scalar(
                    text("SELECT pg_catalog.has_function_privilege(:name,:signature,'EXECUTE')"),
                    {"name": name, "signature": signature},
                )
            )
        )
    return tuple(flags)


def _shape(db):
    from miy_api.domains.official_apps.whiteboard_checked_models import (
        WhiteboardCheckedAttempt,
        WhiteboardCheckedContributor,
    )

    expected = {
        (
            model.__tablename__,
            column.name,
            column.type.compile(dialect=db.get_bind().dialect),
            column.nullable,
        )
        for model in (WhiteboardCheckedAttempt, WhiteboardCheckedContributor)
        for column in model.__table__.columns
    }
    rows = db.execute(
        text("""
      SELECT c.relname,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),NOT a.attnotnull
      FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
      WHERE n.nspname='public' AND c.relname IN ('whiteboard_checked_attempts','whiteboard_checked_contributors') AND c.relkind='r'
    """)
    ).all()

    def normalize(value):
        return (
            value.lower()
            .replace("varchar", "character varying")
            .replace("timestamp without time zone", "timestamp")
        )

    def normalized(rows):
        return {(a, b, normalize(c), d) for a, b, c, d in rows}

    if normalized(expected) != normalized(rows):
        raise WriterControlError("whiteboard_checked_schema_invalid")
    rows = db.execute(
        text("""
      SELECT c.relname,p.proname,nf.nspname,t.tgenabled,t.tgtype,t.tgnargs,t.tgargs,
        t.tgattr=''::int2vector,t.tgqual IS NULL,t.tgconstraint=0
      FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid JOIN pg_catalog.pg_namespace nf ON nf.oid=p.pronamespace
      WHERE n.nspname='public' AND t.tgname IN ('miy_whiteboard_content_revision','miy_whiteboard_checked_immutable')
    """)
    ).all()
    if set((a, b, c, d, e, f, bytes(g), h, i, j) for a, b, c, d, e, f, g, h, i, j in rows) != {
        (
            "whiteboard_collab_documents",
            "miy_whiteboard_content_revision",
            "public",
            "O",
            23,
            0,
            b"",
            True,
            True,
            True,
        ),
        (
            "whiteboard_checked_attempts",
            "miy_whiteboard_checked_immutable",
            "public",
            "O",
            31,
            0,
            b"",
            True,
            True,
            True,
        ),
        (
            "whiteboard_checked_contributors",
            "miy_whiteboard_checked_immutable",
            "public",
            "O",
            31,
            0,
            b"",
            True,
            True,
            True,
        ),
    }:
        raise WriterControlError("whiteboard_checked_trigger_invalid")


def _checked_function_contract(db, signature, *, body, owner_oid, result, definer):
    _function_contract(
        db, signature, body=body, owner_oid=owner_oid, result=result, definer=definer
    )
    row = db.execute(
        text(
            "SELECT proargnames,proargmodes FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure(:signature)"
        ),
        {"signature": signature},
    ).one_or_none()
    if row is None or tuple(row) != (FUNCTION_ARGUMENTS[signature], None):
        raise WriterControlError("whiteboard_checked_function_arguments_invalid")


def whiteboard_checked_contract(
    db,
    *,
    source_owner_oid,
    core_owner_oid,
    acl_owner_oid,
    service_capability_owner_oid,
    producer_owner_oid,
    source_guard_owner_oid,
    trigger_owner_oid,
):
    for value in (
        source_owner_oid,
        core_owner_oid,
        acl_owner_oid,
        service_capability_owner_oid,
        producer_owner_oid,
        source_guard_owner_oid,
        trigger_owner_oid,
    ):
        _oid(value)
    if len({source_owner_oid, core_owner_oid, trigger_owner_oid}) != 3:
        raise WriterControlError("whiteboard_checked_distinct_owners_required")
    whiteboard_actor_acl_contract(
        db,
        capability_owner_oid=acl_owner_oid,
        service_capability_owner_oid=service_capability_owner_oid,
        producer_owner_oid=producer_owner_oid,
        source_guard_owner_oid=source_guard_owner_oid,
    )
    for signature, (body, result, definer) in FUNCTION_CONTRACTS.items():
        owner = (
            source_owner_oid
            if signature == SAVE_CAPABILITY
            else core_owner_oid
            if signature in (SEAL_CAPABILITY, RESOLVE_CAPABILITY)
            else trigger_owner_oid
        )
        _checked_function_contract(
            db, signature, body=body, owner_oid=owner, result=result, definer=definer
        )
    _shape(db)
    for oid, kind in ((source_owner_oid, "source"), (core_owner_oid, "core")):
        name = db.scalar(
            text("SELECT rolname FROM pg_catalog.pg_roles WHERE oid=:oid"), {"oid": oid}
        )
        if (
            name is None
            or not all(_profile(db, name, kind=kind, owner=True))
            or not db.scalar(
                text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                {"name": name},
            )
        ):
            raise WriterControlError("whiteboard_checked_owner_invalid")


def install_whiteboard_checked_guard(
    db: Session,
    actor: AuthContext,
    *,
    source_guard_owner,
    core_guard_owner,
    expected,
    expected_migration_owner_oid,
    expected_acl_owner_oid,
    expected_service_capability_owner_oid,
    expected_producer_owner_oid,
    expected_source_guard_owner_oid,
):
    with db.no_autoflush:
        current = _lock(db, actor, expected, "draining")
        whiteboard_actor_acl_contract(
            db,
            capability_owner_oid=expected_acl_owner_oid,
            service_capability_owner_oid=expected_service_capability_owner_oid,
            producer_owner_oid=expected_producer_owner_oid,
            source_guard_owner_oid=expected_source_guard_owner_oid,
        )
        source_oid = _actor_role(db, source_guard_owner, login=False)
        core_oid = _actor_role(db, core_guard_owner, login=False)
        kwargs = dict(
            source_owner_oid=source_oid,
            core_owner_oid=core_oid,
            acl_owner_oid=expected_acl_owner_oid,
            service_capability_owner_oid=expected_service_capability_owner_oid,
            producer_owner_oid=expected_producer_owner_oid,
            source_guard_owner_oid=expected_source_guard_owner_oid,
            trigger_owner_oid=expected_migration_owner_oid,
        )
        if len({source_oid, core_oid, expected_migration_owner_oid}) != 3:
            raise WriterControlError("whiteboard_checked_distinct_owners_required")
        actual = [
            db.scalar(
                text(
                    "SELECT proowner::bigint FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure(:cap)"
                ),
                {"cap": signature},
            )
            for signature in (SAVE_CAPABILITY, SEAL_CAPABILITY, RESOLVE_CAPABILITY)
        ]
        if actual == [source_oid, core_oid, core_oid]:
            whiteboard_checked_contract(db, **kwargs)
            return
        if actual != [expected_migration_owner_oid] * 3:
            raise WriterControlError("whiteboard_checked_partial_owner_forbidden")
        for signature, (body, result, definer) in FUNCTION_CONTRACTS.items():
            _checked_function_contract(
                db,
                signature,
                body=body,
                owner_oid=expected_migration_owner_oid,
                result=result,
                definer=definer,
            )
        _shape(db)
        for name, kind in ((source_guard_owner, "source"), (core_guard_owner, "core")):
            if any(_profile(db, name, kind=kind, owner=True)):
                raise WriterControlError("whiteboard_checked_fresh_owner_required")
        with db.begin_nested():
            for name, kind in ((source_guard_owner, "source"), (core_guard_owner, "core")):
                role = _identifier(name)
                db.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
                manifests = (
                    ("SELECT", SOURCE_READ_COLUMNS if kind == "source" else CORE_READ_COLUMNS),
                    ("UPDATE", SOURCE_UPDATE_COLUMNS if kind == "source" else CORE_UPDATE_COLUMNS),
                )
                if kind == "core":
                    manifests += (("INSERT", CORE_INSERT_COLUMNS),)
                for privilege, manifest in manifests:
                    for table, columns in manifest.items():
                        db.execute(
                            text(
                                f"GRANT {privilege} ({','.join(columns)}) ON public.{table} TO {role}"
                            )
                        )
                dependency = ACL_CAPABILITY if kind == "source" else PRODUCER_ADMISSION
                db.execute(text(f"GRANT EXECUTE ON FUNCTION {dependency} TO {role}"))
                for signature in (
                    (SAVE_CAPABILITY,)
                    if kind == "source"
                    else (SEAL_CAPABILITY, RESOLVE_CAPABILITY)
                ):
                    db.execute(text(f"ALTER FUNCTION {signature} OWNER TO {role}"))
                db.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
            whiteboard_checked_contract(db, **kwargs)
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_checked.guard.install",
                entity_kind="official_whiteboard_checked_guard",
                entity_id=str(source_oid),
                summary="Inactive Core-sealed checked storage owners prepared",
                payload={"source_role_oid": source_oid, "core_role_oid": core_oid},
            )


def prepare_whiteboard_checked_principal(
    db,
    actor,
    *,
    role_name,
    kind,
    identity,
    expected,
    expected_state,
    source_owner_oid,
    core_owner_oid,
    acl_owner_oid,
    service_capability_owner_oid,
    producer_owner_oid,
    source_guard_owner_oid,
    trigger_owner_oid,
):
    _identity(identity)
    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        kwargs = dict(
            source_owner_oid=source_owner_oid,
            core_owner_oid=core_owner_oid,
            acl_owner_oid=acl_owner_oid,
            service_capability_owner_oid=service_capability_owner_oid,
            producer_owner_oid=producer_owner_oid,
            source_guard_owner_oid=source_guard_owner_oid,
            trigger_owner_oid=trigger_owner_oid,
        )
        whiteboard_checked_contract(db, **kwargs)
        oid = _actor_role(db, role_name, login=True)
        writer = WhiteboardCheckedProfile(oid, role_name, identity, kind, **kwargs)
        existing = db.scalar(
            select(RuntimePrincipal)
            .where((RuntimePrincipal.role_oid == oid) | (RuntimePrincipal.role_name == role_name))
            .execution_options(populate_existing=True)
        )
        flags = _profile(db, role_name, kind=kind)
        if existing is not None:
            if (
                (
                    existing.role_oid,
                    existing.role_name,
                    existing.scope,
                    existing.owner,
                    existing.generation,
                    existing.artifact,
                    existing.revoked_at,
                )
                != (
                    oid,
                    role_name,
                    identity.scope,
                    identity.owner,
                    identity.generation,
                    identity.artifact,
                    None,
                )
                or not all(flags)
                or not db.scalar(
                    text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                    {"name": role_name},
                )
            ):
                raise WriterControlError("whiteboard_checked_existing_profile_forbidden")
            return WhiteboardCheckedPreparation(existing, writer)
        if any(flags):
            raise WriterControlError("whiteboard_checked_fresh_principal_required")
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
            for signature in (
                (SAVE_CAPABILITY,) if kind == "source" else (SEAL_CAPABILITY, RESOLVE_CAPABILITY)
            ):
                db.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}"))
            if not all(_profile(db, role_name, kind=kind)):
                raise WriterControlError("whiteboard_checked_profile_incomplete")
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_whiteboard_checked.principal.prepare",
                entity_kind="official_writer_principal",
                entity_id=str(oid),
                summary="Fresh inactive DML0 checked principal prepared",
                payload={
                    "role": role_name,
                    "profile": SOURCE_PROFILE if kind == "source" else CORE_PROFILE,
                },
            )
        return WhiteboardCheckedPreparation(principal, writer)
