"""Managed Recording SQL ownership in an explicitly owned disposable cluster."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import ACTIVE, PASSWORD, activate, denied, sa_dsn
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import world as world

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication
from miy_api.domains.official_apps.recording_roles import prepare_core_principal
from miy_api.domains.recording.pipeline_models import RecordingStageCommand


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


@pytest.mark.parametrize("with_publication", [True])
def test_legacy_downgrade_refuses_recorded_command_history(world, prepared, with_publication):
    from test_alembic_migrations import _migration_config

    from alembic import command
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
