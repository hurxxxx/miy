"""Managed Recording SQL ownership in an explicitly owned disposable cluster."""

from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace

import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, text
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.recording_roles import prepare_core_principal
from miy_api.domains.official_apps.writer_roles import revoke_principal
from miy_api.domains.official_apps.writer import WriterControlError
from test_official_writer_roles import ACTIVE, PASSWORD, activate, denied, sa_dsn, move


from sqlalchemy import inspect

from miy_api.domains.recording.pipeline_models import RecordingStageCommand
from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication
from miy_api.domains.official_apps.recording_roles import guard_contract
from sqlalchemy.orm import Session
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


def test_managed_schema_is_inactive_and_matches_models(world):
    schema = inspect(world.engine)
    for model in (RecordingStageCommand, CoreRecordingPublication):
        assert {c["name"]: c["nullable"] for c in schema.get_columns(model.__tablename__)} == {
            c.name: c.nullable for c in model.__table__.columns
        }
        assert {c["name"] for c in schema.get_check_constraints(model.__tablename__)} == {
            c.name
            for c in (
                *model.__table__.constraints,
                *(item for column in model.__table__.columns for item in column.constraints),
            )
            if c.__class__.__name__ == "CheckConstraint"
        }
    with Session(world.engine) as db:
        guard_contract(db)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
        assert conn.execute(
            "SELECT active_owner,state,generation FROM official_runtime_ownership WHERE scope='official.suite'"
        ).fetchone() == ("legacy", "active", 1)
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0


def test_separate_principals_prepare_without_business_authority_expansion(world):
    from miy_api.domains.official_apps.recording_roles import prepare_core_principal
    from test_official_writer_roles import ACTIVE, activate, denied

    source, _, _ = activate(world)
    core = world.role()
    with Session(world.engine) as db:
        prepare_core_principal(
            db, world.actor, role_name=core, expected=ACTIVE, expected_state="active"
        )
        db.commit()
    with world.connect(source) as conn:
        assert conn.execute(
            "SELECT has_table_privilege(current_user,'recording_stage_commands','SELECT,INSERT,UPDATE')"
        ).fetchone()[0]
        assert conn.execute(
            "SELECT has_table_privilege(current_user,'core_recording_publications','SELECT')"
        ).fetchone()[0]
        denied(conn, "UPDATE core_recording_publications SET state=state WHERE false")
        denied(
            conn,
            "SELECT miy_recording_publication_admit(gen_random_uuid(),gen_random_uuid(),'bad')",
        )
    with world.connect(core) as conn:
        denied(conn, "UPDATE recordings SET title=title WHERE false")
        denied(conn, "SELECT id FROM recordings FOR SHARE")
        denied(conn, "UPDATE recording_stage_commands SET state=state WHERE false")
        assert conn.execute("SELECT count(*) FROM core_recording_publications").fetchone()[0] == 0


@pytest.fixture
def prepared(world):
    source, _, oid = activate(world)
    core = world.role()
    with Session(world.engine) as db:
        issuer = prepare_core_principal(
            db, world.actor, role_name=core, expected=ACTIVE, expected_state="active"
        )
        db.commit()
    engines = [
        create_engine(sa_dsn(make_conninfo(world.dsn, user=role, password=PASSWORD)))
        for role in (source, core)
    ]
    result = SimpleNamespace(
        source=source,
        core=core,
        source_oid=oid,
        core_oid=issuer["role_oid"],
        source_engine=engines[0],
        core_engine=engines[1],
    )
    yield result
    for engine in engines:
        engine.dispose()


def new_command(db, **changes):
    values = dict(
        command_id=str(uuid4()),
        recording_id=str(uuid4()),
        attempt_id=str(uuid4()),
        stage="transcribe",
        retry_ordinal=0,
        task_id=str(uuid4()),
        owner_id=str(uuid4()),
        storage_key="synthetic/recording.wav",
        payload_digest="a" * 64,
        due_at=utcnow_naive() - timedelta(seconds=1),
        state="pending",
    )
    values.update(changes)
    row = RecordingStageCommand(**values)
    db.add(row)
    db.flush()
    return row


def new_publication(db, command):
    row = CoreRecordingPublication(
        publication_id=str(uuid4()),
        command_id=command.command_id,
        task_id=command.task_id,
        payload_digest=command.payload_digest,
        queue="miy.official.meeting_transcribe",
        profile="official",
        state="pending",
    )
    db.add(row)
    db.flush()
    return row


def seeded(prepared):
    with Session(prepared.source_engine) as db:
        command = new_command(db)
        db.expunge(command)
        db.commit()
    with Session(prepared.core_engine) as db:
        publication = new_publication(db, command)
        db.expunge(publication)
        db.commit()
    return command, publication


def admit(db, command, publication):
    db.execute(
        text("SELECT public.miy_recording_publication_admit(:command,:publication,:digest)"),
        {
            "command": command.command_id,
            "publication": publication.publication_id,
            "digest": command.payload_digest,
        },
    )


def test_sql_stamps_provenance_and_core_issuer_not_caller_or_guc(world, prepared):
    with Session(prepared.source_engine) as db:
        db.execute(text("SET LOCAL miy.writer_generation='999'"))
        row = new_command(
            db,
            producer_role_oid=999,
            producer_role_name="forged",
            producer_generation=999,
            producer_artifact="sha256:" + "f" * 64,
        )
        db.refresh(row)
        assert (
            row.producer_role_oid,
            row.producer_role_name,
            row.producer_generation,
            row.producer_artifact,
        ) == (prepared.source_oid, prepared.source, 3, ACTIVE.artifact)
        db.expunge(row)
        db.commit()
    with Session(prepared.core_engine) as db:
        publication = CoreRecordingPublication(
            publication_id=str(uuid4()),
            command_id=row.command_id,
            task_id=row.task_id,
            payload_digest=row.payload_digest,
            queue="miy.official.meeting_transcribe",
            profile="official",
            state="pending",
            issuer_role_oid=999,
            issuer_role_name="forged",
        )
        db.add(publication)
        db.flush()
        db.refresh(publication)
        assert (publication.issuer_role_oid, publication.issuer_role_name) == (
            prepared.core_oid,
            prepared.core,
        )
        admit(db, row, publication)
        db.commit()


@pytest.mark.parametrize(
    "mutation",
    [
        "payload_digest='" + "b" * 64 + "'",
        "producer_generation=999",
        "task_id=gen_random_uuid()",
        "due_at=due_at+interval '1 second'",
        "owner_id='other'",
        "state='succeeded'",
    ],
)
def test_source_identity_and_unclaimed_terminal_are_immutable(world, prepared, mutation):
    command, _ = seeded(prepared)
    with world.connect(prepared.source) as conn:
        denied(
            conn,
            f"UPDATE recording_stage_commands SET {mutation} WHERE command_id='{command.command_id}'",
            "23514",
        )
        assert (
            conn.execute(
                "SELECT state FROM recording_stage_commands WHERE command_id=%s",
                (command.command_id,),
            ).fetchone()[0]
            == "pending"
        )


def test_running_token_is_durable_noop_valid_reclaim_and_history_delete_denied(world, prepared):
    command, _ = seeded(prepared)
    token = str(uuid4())
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE recording_stage_commands SET state='running',execution_token=%s WHERE command_id=%s",
            (token, command.command_id),
        )
        conn.commit()
        conn.execute(
            "UPDATE recording_stage_commands SET state='running' WHERE command_id=%s",
            (command.command_id,),
        )
        denied(
            conn,
            f"UPDATE recording_stage_commands SET execution_token=gen_random_uuid() WHERE command_id='{command.command_id}'",
            "23514",
        )
        denied(
            conn,
            f"UPDATE recording_stage_commands SET state='pending',execution_token=NULL,started_at=NULL WHERE command_id='{command.command_id}'",
            "23514",
        )
        conn.execute(
            "UPDATE recording_stage_commands SET state='succeeded' WHERE command_id=%s",
            (command.command_id,),
        )
        conn.commit()
        denied(
            conn,
            f"UPDATE recording_stage_commands SET state='running',finished_at=NULL WHERE command_id='{command.command_id}'",
            "23514",
        )
        denied(conn, "DELETE FROM recording_stage_commands")
    with world.connect() as conn:
        denied(conn, "DELETE FROM recording_stage_commands", "55000")
        denied(conn, "TRUNCATE recording_stage_commands CASCADE", "55000")
        denied(conn, "TRUNCATE core_recording_publications", "55000")


def test_publication_lifecycle_fixed_binding_and_actual_consumption(world, prepared):
    command, publication = seeded(prepared)
    with Session(prepared.core_engine) as db:
        admit(db, command, publication)
        current = db.get(CoreRecordingPublication, publication.publication_id)
        current.state = "publishing"
        current.publication_token = str(uuid4())
        db.commit()
        current = db.get(CoreRecordingPublication, publication.publication_id)
        token = current.publication_token
        current.state = "unknown"
        db.commit()
        current = db.get(CoreRecordingPublication, publication.publication_id)
        current.state = "publishing"
        current.publication_token = str(uuid4())
        db.commit()
        assert current.publication_token != token
        current.state = "consumed"
        with pytest.raises(Exception) as error:
            db.commit()
        assert error.value.orig.sqlstate == "23514"
        db.rollback()
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE recording_stage_commands SET state='running',execution_token=gen_random_uuid() WHERE command_id=%s",
            (command.command_id,),
        )
    with Session(prepared.core_engine) as db:
        admit(db, command, publication)
        current = db.get(CoreRecordingPublication, publication.publication_id)
        current.state = "consumed"
        db.commit()
        current.state = "unknown"
        with pytest.raises(Exception) as error:
            db.commit()
        assert error.value.orig.sqlstate == "23514"
        db.rollback()
    with world.connect(prepared.core) as conn:
        denied(
            conn,
            "UPDATE core_recording_publications SET payload_digest='" + "c" * 64 + "'",
            "23514",
        )
        denied(conn, "DELETE FROM core_recording_publications")


@pytest.mark.parametrize("change", ["drain", "revoke"])
def test_stale_source_and_core_admission_reject_before_effect(world, prepared, change):
    command, publication = seeded(prepared)
    if change == "drain":
        move(world, ACTIVE, "active", state="draining")
    else:
        with Session(world.engine) as db:
            revoke_principal(
                db,
                world.actor,
                role_oid=prepared.source_oid,
                expected=ACTIVE,
                expected_state="active",
            )
            db.commit()
    with Session(prepared.core_engine) as db:
        with pytest.raises(Exception) as error:
            admit(db, command, publication)
        assert error.value.orig.sqlstate == "55000"
    with world.connect(prepared.source) as conn:
        denied(
            conn,
            "UPDATE recording_stage_commands SET state=state WHERE false",
            "55000",
        )


def test_set_role_cannot_impersonate_prepared_core_session_user(world, prepared):
    command, publication = seeded(prepared)
    with world.connect() as conn:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(prepared.core)))
        denied(
            conn,
            f"SELECT public.miy_recording_publication_admit('{command.command_id}','{publication.publication_id}','{command.payload_digest}')",
            "42501",
        )


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_core_preparation_rejects_non_read_committed_transaction(world, isolation):
    core = world.role()
    from test_official_writer_roles import BASE

    engine = create_engine(sa_dsn(world.dsn), isolation_level=isolation)
    try:
        with Session(engine) as db, pytest.raises(WriterControlError, match="read_committed"):
            prepare_core_principal(
                db, world.actor, role_name=core, expected=BASE, expected_state="active"
            )
    finally:
        engine.dispose()
    with world.connect() as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'core_recording_publications','INSERT')", (core,)
        ).fetchone()[0]


def test_copy_stamps_source_identity_and_core_cannot_copy_commands(world, prepared):
    command_id, attempt_id, task_id = str(uuid4()), str(uuid4()), str(uuid4())
    columns = "command_id,recording_id,attempt_id,stage,retry_ordinal,task_id,owner_id,storage_key,payload_digest,due_at,state"
    with world.connect(prepared.source) as conn:
        with conn.cursor().copy(f"COPY recording_stage_commands ({columns}) FROM STDIN") as copy:
            copy.write_row(
                (
                    command_id,
                    str(uuid4()),
                    attempt_id,
                    "transcribe",
                    0,
                    task_id,
                    str(uuid4()),
                    "synthetic/copy.wav",
                    "d" * 64,
                    utcnow_naive(),
                    "pending",
                )
            )
        assert conn.execute(
            "SELECT producer_role_oid,producer_role_name FROM recording_stage_commands WHERE command_id=%s",
            (command_id,),
        ).fetchone() == (prepared.source_oid, prepared.source)
    with world.connect(prepared.core) as conn:
        denied(conn, f"COPY recording_stage_commands ({columns}) FROM STDIN")


def test_core_role_recreated_name_cannot_adopt_old_publication(world, prepared):
    command, publication = seeded(prepared)
    prepared.core_engine.dispose()
    with world.connect() as conn:
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(prepared.core)))
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(prepared.core)))
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(prepared.core), sql.Literal(PASSWORD))
        )
    with Session(world.engine) as db:
        current = prepare_core_principal(
            db, world.actor, role_name=prepared.core, expected=ACTIVE, expected_state="active"
        )
        db.commit()
        assert current["role_oid"] != prepared.core_oid
    with Session(prepared.core_engine) as db:
        with pytest.raises(Exception) as error:
            admit(db, command, publication)
        assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("grant", ["column", "public", "membership", "function"])
def test_core_preparation_rejects_ambient_privileges_without_repair(world, grant):
    from test_official_writer_roles import BASE

    core = world.role()
    with world.connect() as conn:
        if grant == "column":
            conn.execute(
                sql.SQL("GRANT UPDATE(title) ON recordings TO {}").format(sql.Identifier(core))
            )
        elif grant == "public":
            conn.execute("GRANT SELECT ON users TO PUBLIC")
        elif grant == "membership":
            member = world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(member), sql.Identifier(core))
            )
        else:
            conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION miy_recording_lock_producer(bigint,text,integer,text) TO {}"
                ).format(sql.Identifier(core))
            )
    with Session(world.engine) as db, pytest.raises(WriterControlError):
        prepare_core_principal(
            db, world.actor, role_name=core, expected=BASE, expected_state="active"
        )
    with world.connect() as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'core_recording_publications','INSERT')", (core,)
        ).fetchone()[0]
        if grant == "membership":
            conn.execute(
                sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(member), sql.Identifier(core))
            )


def test_core_admission_holds_drain_until_same_transaction_finishes(world, prepared):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from test_official_writer_fence import wait_for_blockers
    from miy_api.domains.official_apps.writer import transition

    command, publication = seeded(prepared)
    entered = Event()
    pids = {}

    def drain():
        with Session(world.engine) as db:
            pids["drain"] = db.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            transition(
                db,
                world.actor,
                request_id=uuid4(),
                expected=ACTIVE,
                expected_state="active",
                owner="legacy",
                state="draining",
                artifact=ACTIVE.artifact,
                reason="Owned managed publication test",
            )
            db.commit()

    with Session(prepared.core_engine) as db:
        admit(db, command, publication)
        pid = db.scalar(text("SELECT pg_backend_pid()"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(drain)

            def observation_session():
                # Surface a control-thread exception before interpreting an absent
                # blocker as a SQL-lock failure.
                if future.done():
                    future.result()
                return Session(world.engine)

            try:
                assert entered.wait(10)
                wait_for_blockers(observation_session, pids["drain"], {pid})
                assert not future.done()
            finally:
                db.rollback()
            future.result(timeout=20)
    with Session(prepared.core_engine) as db:
        with pytest.raises(Exception) as error:
            admit(db, command, publication)
        assert error.value.orig.sqlstate == "55000"


def test_hardened_upgrade_preserves_old_principal_and_requires_explicit_new_role(
    world, monkeypatch
):
    from alembic import command
    from miy_api.domains.official_apps import writer_roles
    from miy_api.domains.official_apps.writer import WriterIdentity
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import prepare

    config = _migration_config(sa_dsn(world.dsn))
    previous = "docs_legacy_repair_20261007"
    revision = "recording_managed_20261007"
    command.downgrade(config, previous)
    with monkeypatch.context() as historical:
        historical.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ("official_projection_outbox",))
        runtime, guard_owner, oid = activate(world)
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, revision)
    with world.connect() as conn:
        assert conn.execute("SELECT to_regclass('recording_stage_commands')").fetchone()[0] is None
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == previous
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, revision)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
                "WHERE t.tgname='miy_official_source_writer' "
                "AND p.proname='miy_guard_official_source_writer_by_role'"
            ).fetchone()[0]
            == 90
        )
        grants_before = conn.execute(
            "SELECT table_name,privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee=%s ORDER BY 1,2",
            (runtime,),
        ).fetchall()
        audits_before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    assert prepare(world, runtime, ACTIVE, draining, "draining") == oid
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT table_name,privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee=%s ORDER BY 1,2",
                (runtime,),
            ).fetchall()
            == grants_before
        )
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits_before
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'recording_stage_commands','SELECT,INSERT,UPDATE')",
            (runtime,),
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'core_recording_publications','SELECT')", (runtime,)
        ).fetchone()[0]
    identity = WriterIdentity(ACTIVE.scope, "legacy", 5, "sha256:" + "c" * 64)
    new_role = world.role()
    prepare(world, new_role, identity, draining, "draining")
    with Session(world.engine) as db:
        writer_roles.install_role_guard(db, world.actor, guard_owner=guard_owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=oid, expected=draining, expected_state="draining"
        )
        db.commit()
    move(world, draining, "draining", state="active", artifact=identity.artifact)
    with world.connect(new_role) as conn:
        assert conn.execute(
            "SELECT has_table_privilege(session_user,'recording_stage_commands','SELECT,INSERT,UPDATE')"
        ).fetchone()[0]
        conn.execute("UPDATE meetings SET title=title WHERE false")
        conn.commit()
    with world.connect(runtime) as conn:
        denied(conn, "UPDATE meetings SET title=title WHERE false", "55000")
        denied(conn, "SELECT command_id FROM recording_stage_commands")
    with pytest.raises(RuntimeError, match="explicit_retirement"):
        command.downgrade(config, previous)


@pytest.mark.parametrize("hazard", ["disabled", "missing", "mixed", "args", "row"])
def test_upgrade_rejects_previous_guard_drift_without_partial_ddl(world, hazard):
    from alembic import command
    from test_alembic_migrations import _migration_config

    config = _migration_config(sa_dsn(world.dsn))
    previous = "docs_legacy_repair_20261007"
    command.downgrade(config, previous)
    with world.connect() as conn:
        if hazard in {"disabled", "missing"}:
            conn.execute(
                {
                    "disabled": "ALTER TABLE meetings DISABLE TRIGGER miy_official_source_writer",
                    "missing": "DROP TRIGGER miy_official_source_writer ON meetings",
                }[hazard]
            )
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON meetings")
            function = (
                "miy_guard_official_source_writer_by_role"
                if hazard == "mixed"
                else "miy_guard_official_source_writer"
            )
            argument = "'wrong.scope'" if hazard == "args" else "'official.suite'"
            event = (
                "INSERT OR UPDATE OR DELETE"
                if hazard == "row"
                else "INSERT OR UPDATE OR DELETE OR TRUNCATE"
            )
            level = "ROW" if hazard == "row" else "STATEMENT"
            conn.execute(
                f"CREATE TRIGGER miy_official_source_writer BEFORE {event} ON meetings FOR EACH {level} EXECUTE FUNCTION {function}({argument})"
            )
    with pytest.raises(RuntimeError, match="guard_inventory_invalid"):
        command.upgrade(config, "recording_managed_20261007")
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == previous
        assert conn.execute(
            "SELECT to_regclass('recording_stage_commands'),to_regclass('core_recording_publications')"
        ).fetchone() == (None, None)
        assert (
            conn.execute(
                "SELECT to_regprocedure('miy_recording_publication_admit(uuid,uuid,text)')"
            ).fetchone()[0]
            is None
        )


@pytest.mark.parametrize("hazard", ["public", "search_path", "invoker"])
def test_upgrade_rejects_hardened_function_drift_without_partial_ddl(world, monkeypatch, hazard):
    from alembic import command
    from miy_api.domains.official_apps import writer_roles
    from test_alembic_migrations import _migration_config

    config = _migration_config(sa_dsn(world.dsn))
    previous = "docs_legacy_repair_20261007"
    command.downgrade(config, previous)
    with monkeypatch.context() as historical:
        historical.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ("official_projection_outbox",))
        activate(world)
    move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    with world.connect() as conn:
        conn.execute(
            {
                "public": "GRANT EXECUTE ON FUNCTION miy_guard_official_source_writer_by_role() TO PUBLIC",
                "search_path": "ALTER FUNCTION miy_guard_official_source_writer_by_role() SET search_path=public,pg_catalog",
                "invoker": "ALTER FUNCTION miy_guard_official_source_writer_by_role() SECURITY INVOKER",
            }[hazard]
        )
    with pytest.raises(RuntimeError, match="role_guard_invalid"):
        command.upgrade(config, "recording_managed_20261007")
    with world.connect() as conn:
        assert conn.execute("SELECT to_regclass('recording_stage_commands')").fetchone()[0] is None
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == previous


def test_current_new_principal_refuses_previous_schema_before_any_grant(world):
    from alembic import command
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import prepare

    command.downgrade(_migration_config(sa_dsn(world.dsn)), "docs_legacy_repair_20261007")
    role = world.role()
    with world.connect() as conn:
        before = conn.execute(
            "SELECT (SELECT count(*) FROM official_writer_principals),(SELECT count(*) FROM audit_logs)"
        ).fetchone()
    with pytest.raises(WriterControlError, match="trigger_inventory_invalid"):
        prepare(world, role)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT (SELECT count(*) FROM official_writer_principals),(SELECT count(*) FROM audit_logs)"
            ).fetchone()
            == before
        )
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'recordings','SELECT,INSERT,UPDATE')", (role,)
        ).fetchone()[0]


@pytest.mark.parametrize("principal", ["source", "core"])
@pytest.mark.parametrize(
    "hazard",
    [
        "command_disabled",
        "history_disabled",
        "scope_disabled",
        "guard_public",
        "admit_public",
        "admit_search_path",
        "admit_invoker",
    ],
)
def test_new_principal_checks_all_managed_guards_before_any_grant(world, principal, hazard):
    from test_official_writer_roles import BASE, prepare

    with world.connect() as conn:
        conn.execute(
            {
                "command_disabled": "ALTER TABLE recording_stage_commands DISABLE TRIGGER miy_recording_command_guard",
                "history_disabled": "ALTER TABLE core_recording_publications DISABLE TRIGGER miy_recording_history",
                "scope_disabled": "ALTER TABLE core_recording_publications DISABLE TRIGGER miy_recording_publication_scope",
                "guard_public": "GRANT EXECUTE ON FUNCTION miy_recording_command_guard() TO PUBLIC",
                "admit_public": "GRANT EXECUTE ON FUNCTION miy_recording_publication_admit(uuid,uuid,text) TO PUBLIC",
                "admit_search_path": "ALTER FUNCTION miy_recording_publication_admit(uuid,uuid,text) SET search_path=public,pg_catalog",
                "admit_invoker": "ALTER FUNCTION miy_recording_publication_admit(uuid,uuid,text) SECURITY INVOKER",
            }[hazard]
        )
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    role = world.role()
    with pytest.raises(WriterControlError):
        if principal == "source":
            prepare(world, role)
        else:
            with Session(world.engine) as db:
                prepare_core_principal(
                    db, world.actor, role_name=role, expected=BASE, expected_state="active"
                )
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        for table in ("recordings", "recording_stage_commands", "core_recording_publications"):
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE')", (role, table)
            ).fetchone()[0]


def test_empty_legacy_roundtrip_preserves_existing_recording(world):
    from alembic import command
    from miy_api.domains.recording.models import Recording
    from test_alembic_migrations import _migration_config

    identifier = str(uuid4())
    with Session(world.engine) as db:
        db.add(
            Recording(
                id=identifier,
                owner_id=world.user_id,
                title="Preserved synthetic recording",
                started_at=utcnow_naive(),
            )
        )
        db.commit()
    config = _migration_config(sa_dsn(world.dsn))
    for revision in (
        "docs_legacy_repair_20261007",
        "recording_managed_20261007",
        "docs_legacy_repair_20261007",
        "recording_managed_20261007",
    ):
        command.downgrade(
            config, revision
        ) if revision == "docs_legacy_repair_20261007" else command.upgrade(config, revision)
        with Session(world.engine) as db:
            assert db.get(Recording, identifier).title == "Preserved synthetic recording"


@pytest.mark.parametrize("with_publication", [False, True])
def test_legacy_downgrade_refuses_recorded_command_history(world, prepared, with_publication):
    from alembic import command
    from test_alembic_migrations import _migration_config
    from miy_api.domains.official_apps.writer_contracts import (
        COVERED_SOURCE_TABLES,
        WRITER_TRANSPORT_TABLES,
    )

    with Session(prepared.source_engine) as db:
        row = new_command(db)
        identifier = row.command_id
        db.expunge(row)
        db.commit()
    if with_publication:
        with Session(prepared.core_engine) as db:
            new_publication(db, row)
            db.commit()
    # A fixture-only explicit guard retirement reaches the separate history
    # check. Preserve all data/row guards, give the producer no control grants,
    # and never execute it under the restored legacy statement guards.
    with world.connect() as conn:
        before_schema = conn.execute(
            "SELECT version_num,"
            "to_regprocedure('public.miy_read_official_company_partition(text,uuid)')::oid,"
            "to_regprocedure('public.miy_lock_official_projection_partition(uuid,text)')::oid "
            "FROM alembic_version"
        ).fetchone()
        assert all(before_schema[1:])
        for table in (*COVERED_SOURCE_TABLES, *WRITER_TRANSPORT_TABLES):
            conn.execute(
                sql.SQL("DROP TRIGGER miy_official_source_writer ON {}").format(
                    sql.Identifier(table)
                )
            )
            conn.execute(
                sql.SQL(
                    "CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION miy_guard_official_source_writer('official.suite')"
                ).format(sql.Identifier(table))
            )
    with pytest.raises(RuntimeError, match="history_retention_required"):
        command.downgrade(_migration_config(sa_dsn(world.dsn)), "docs_legacy_repair_20261007")
    with world.connect() as conn:
        assert (
            str(conn.execute("SELECT command_id FROM recording_stage_commands").fetchone()[0])
            == identifier
        )
        assert conn.execute("SELECT count(*) FROM core_recording_publications").fetchone()[
            0
        ] == int(with_publication)
        # Alembic's outer transaction also restores every later private
        # capability and the exact initial head when history retirement fails.
        assert (
            conn.execute(
                "SELECT version_num,"
                "to_regprocedure('public.miy_read_official_company_partition(text,uuid)')::oid,"
                "to_regprocedure('public.miy_lock_official_projection_partition(uuid,text)')::oid "
                "FROM alembic_version"
            ).fetchone()
            == before_schema
        )


@pytest.mark.parametrize("with_publication", [False, True])
def test_fixture_baseline_refuses_populated_protocol_before_dump(
    world, prepared, tmp_path, monkeypatch, with_publication
):
    import conftest

    with Session(prepared.source_engine) as db:
        row = new_command(db)
        db.expunge(row)
        db.commit()
    if with_publication:
        with Session(prepared.core_engine) as db:
            new_publication(db, row)
            db.commit()

    def unexpected_dump(*args, **kwargs):
        raise AssertionError("A populated protocol baseline must not invoke pg_dump")

    monkeypatch.setattr(conftest, "_run_postgres_cli", unexpected_dump)
    baseline = tmp_path / "must-not-exist.dump"
    with pytest.raises(RuntimeError, match="protocol fixture baseline must be empty"):
        conftest._capture_application_postgres_state(sa_dsn(world.dsn), baseline)
    assert not baseline.exists()
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM recording_stage_commands").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM core_recording_publications").fetchone()[
            0
        ] == int(with_publication)
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_recording_history' AND tgenabled='O'"
            ).fetchone()[0]
            == 2
        )
