"""Explicit restricted Core publication role preparation, never activation.

No role creation, credential handling, startup grant or runtime toggle. SQL
admission checks actual session_user and never needs source UPDATE authority.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, _admin

CORE_READ_TABLES = ("recordings", "recording_results", "recording_stage_commands")
CORE_TABLE = "core_recording_publications"
ADMIT = "public.miy_recording_publication_admit(uuid,uuid,text)"
_FUNCTIONS = (
    "public.miy_recording_lock_producer(bigint,text,integer,text)",
    "public.miy_recording_check_core()",
    "public.miy_recording_command_guard()",
    "public.miy_recording_keep_history()",
    ADMIT,
    "public.miy_recording_publication_scope()",
    "public.miy_recording_publication_guard()",
)


def guard_contract(db: Session) -> None:
    """Every fixed trigger/function must be present before any new runtime grant."""
    rows = db.execute(
        text("""
      SELECT c.relname,t.tgname,p.proname,n.nspname,pn.nspname,t.tgenabled,t.tgtype,t.tgnargs
      FROM pg_catalog.pg_trigger t
      JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
      JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
      WHERE t.tgname IN ('miy_recording_command_guard','miy_recording_history',
                        'miy_recording_publication_scope','miy_recording_publication_guard')
    """)
    ).all()
    expected = {
        (
            "recording_stage_commands",
            "miy_recording_command_guard",
            "miy_recording_command_guard",
            "public",
            "public",
            "O",
            23,
            0,
        ),
        (
            "recording_stage_commands",
            "miy_recording_history",
            "miy_recording_keep_history",
            "public",
            "public",
            "O",
            42,
            0,
        ),
        (
            CORE_TABLE,
            "miy_recording_history",
            "miy_recording_keep_history",
            "public",
            "public",
            "O",
            42,
            0,
        ),
        (
            CORE_TABLE,
            "miy_recording_publication_scope",
            "miy_recording_publication_scope",
            "public",
            "public",
            "O",
            22,
            0,
        ),
        (
            CORE_TABLE,
            "miy_recording_publication_guard",
            "miy_recording_publication_guard",
            "public",
            "public",
            "O",
            23,
            0,
        ),
    }
    if {tuple(row) for row in rows} != expected:
        raise WriterControlError("recording_managed_trigger_contract_invalid")
    for signature in _FUNCTIONS:
        row = db.execute(
            text("""
          SELECT p.prosecdef,p.proconfig,
            EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(:signature)
        """),
            {"signature": signature},
        ).one_or_none()
        expected_definer = not signature.endswith("miy_recording_keep_history()")
        if row is None or tuple(row) != (
            expected_definer,
            ["search_path=pg_catalog, pg_temp"],
            False,
        ):
            raise WriterControlError("recording_managed_function_contract_invalid")


def _privileges(db: Session, role_name: str) -> None:
    from miy_api.domains.official_apps.writer_roles import (
        _sequence_privileges,
        _table_privilege_forbidden,
    )

    if db.scalar(
        text("""
      SELECT pg_catalog.has_database_privilege(:name,current_database(),'CREATE')
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%'
          AND nspname<>'information_schema' AND pg_catalog.has_schema_privilege(:name,oid,'CREATE'))
    """),
        {"name": role_name},
    ):
        raise WriterControlError("recording_core_role_create_forbidden")
    for schema, table, oid in db.execute(
        text("""
      SELECT n.nspname,c.relname,c.oid FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
        AND c.relkind IN ('r','p','v','m','f')
    """)
    ):
        forbidden = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if schema == "public" and table in CORE_READ_TABLES:
            forbidden = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        elif schema == "public" and table == CORE_TABLE:
            forbidden = "DELETE,TRUNCATE,REFERENCES,TRIGGER"
        if _table_privilege_forbidden(db, role_name, oid, forbidden):
            raise WriterControlError("recording_core_role_existing_privilege_forbidden")
    if db.scalar(
        text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
          AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:name)
            OR (p.prosecdef AND p.oid<>pg_catalog.to_regprocedure(:admit)
                AND pg_catalog.has_function_privilege(:name,p.oid,'EXECUTE'))))
    """),
        {"name": role_name, "admit": ADMIT},
    ):
        raise WriterControlError("recording_core_role_function_privilege_forbidden")
    _sequence_privileges(db, role_name)


def prepare_core_principal(
    db: Session,
    actor: AuthContext,
    *,
    role_name: str,
    expected: WriterIdentity,
    expected_state: str,
) -> dict[str, int | str]:
    """Prepare a supplied restricted Core LOGIN role in the caller transaction.

    Publications stamp its OID/name immutably; another login or a recreated role
    cannot rewrite old bindings. No source DML or source row-lock grant is made.
    """
    from miy_api.domains.official_apps.writer_roles import _identifier, _lock, _role, _source_guard

    with db.no_autoflush:
        current = _lock(db, actor, expected, expected_state)
        oid = _role(db, role_name, login=True)
        _privileges(db, role_name)
        _source_guard(db)
        guard_contract(db)
        role = _identifier(role_name)
        with db.begin_nested():
            db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            for table in CORE_READ_TABLES:
                db.execute(text(f"GRANT SELECT ON public.{table} TO {role}"))
            db.execute(text(f"GRANT SELECT,INSERT,UPDATE ON public.{CORE_TABLE} TO {role}"))
            db.execute(text(f"GRANT EXECUTE ON FUNCTION {ADMIT} TO {role}"))
            _admin(db, actor)
            record_audit_log(
                db,
                actor_user_id=current.user.id,
                action="official_recording.core_principal.prepare",
                entity_kind="official_recording_core_principal",
                entity_id=str(oid),
                summary="Restricted Recording Core publisher prepared",
                payload={"role": role_name, "role_oid": oid},
            )
        return {"role_oid": oid, "role_name": role_name}
