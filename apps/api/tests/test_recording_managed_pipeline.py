"""Restricted real PostgreSQL identities; all broker/provider calls synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from types import SimpleNamespace
from uuid import uuid4

import pytest
from celery.exceptions import Ignore
from company_admission_fixture import seed_company_app_access
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from test_independent_app_data import isolated_data_cluster  # noqa: F401
from test_official_writer_fence import wait_for_blockers
from test_official_writer_roles import (  # noqa: F401
    ACTIVE,
    PASSWORD,
    activate,
    move,
    role_template,
    sa_dsn,
    world,
)

from miy_api.domains.official_apps.recording_publications import (
    prepare_publication,
    reconcile_publication,
    send_publication,
)
from miy_api.domains.recording.models import Recording, RecordingResult
from miy_api.domains.recording.pipeline_commands import create_managed_recording_attempt
from miy_api.domains.recording.pipeline_contracts import (
    MANAGED_HEADER,
    MANAGED_QUEUE,
    RecordingCommandCommitUnknown,
    RecordingCommandError,
)
from miy_api.domains.recording.pipeline_models import RecordingStageCommand


@pytest.fixture
def pipeline(world, monkeypatch):  # noqa: F811
    from miy_worker.settings import get_settings as get_worker_settings

    from miy_api.domains.official_apps.recording_roles import prepare_core_principal

    monkeypatch.setenv("MIY_POSTGRES_DSN", sa_dsn(world.dsn))
    get_worker_settings.cache_clear()
    from miy_worker.tasks import recording as task

    recording_id = str(uuid4())
    with Session(world.engine) as db:
        seed_company_app_access(db, ["recording"])
        db.add(
            Recording(
                id=recording_id,
                owner_id=world.user_id,
                title="Synthetic managed",
                storage_key="synthetic/" + recording_id,
                audio_status="saved",
                transcript_status="pending",
                summary_status="pending",
            )
        )
        db.commit()
    source_role, _, _ = activate(world)
    core_role = world.role()
    with Session(world.engine) as db:
        prepare_core_principal(
            db, world.actor, role_name=core_role, expected=ACTIVE, expected_state="active"
        )
        db.commit()
    # This fixture deliberately adds the already-existing app admission SELECT
    # dependencies. New writer role preparation alone is not a service profile.
    acl_tables = (
        "users",
        "user_system_roles",
        "company_app_controls",
        "app_access_policies",
        "app_user_grants",
        "app_group_grants",
        "groups",
        "group_members",
    )
    with world.connect() as conn:
        conn.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                sql.SQL(",").join(sql.Identifier("public", name) for name in acl_tables),
                sql.Identifier(source_role),
            )
        )
    engines = []

    def factory(role):
        dsn = make_conninfo(world.dsn, user=role, password=PASSWORD)
        engine = create_engine(sa_dsn(dsn), pool_size=1, max_overflow=0, pool_timeout=0.2)
        engines.append(engine)
        return sessionmaker(engine)

    source, core = factory(source_role), factory(core_role)
    with source() as db:
        command_id = create_managed_recording_attempt(
            db, recording_id=recording_id, owner_id=world.user_id
        )
    c = SimpleNamespace(
        world=world,
        source=source,
        core=core,
        task=task,
        recording_id=recording_id,
        command_id=command_id,
        source_role=source_role,
        core_role=core_role,
        factory=factory,
        calls=[],
        messages=[],
        sessions=[],
        on_asr=lambda progress: (progress(0.25), progress(0.25), progress(0.1), progress(0.8)),
        on_publish=lambda message: None,
    )

    def source_session():
        db = source()
        c.sessions.append(db)
        return db

    monkeypatch.setattr(task, "_db_session", source_session)
    monkeypatch.setattr(task, "check_asr_health", lambda **_: SimpleNamespace(ready=True))
    monkeypatch.setattr(task, "_download_recording_to_tmp", lambda row: "/synthetic/no-local-file")

    def transcribe(path, *, on_progress):
        c.calls.append("asr")
        c.on_asr(on_progress)
        return SimpleNamespace(text="Transcript", duration_sec=2)

    def complete(*args, **kwargs):
        c.calls.append(kwargs["source"])
        return "Verified" if "verifier" in kwargs["source"] else "Summary"

    monkeypatch.setattr(task, "get_asr_backend", lambda: SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(task, "_complete_local_agent", complete)
    try:
        yield c
    finally:
        for engine in engines:
            engine.dispose()
        get_worker_settings.cache_clear()


def publish(c, command_id=None, *, callback=None):
    with c.core() as db:
        pub_id = prepare_publication(db, command_id or c.command_id)
    with c.core() as db:

        def send(message):
            c.messages.append(message)
            if callback:
                callback(message)

        outcome = send_publication(db, pub_id, publish=send)
    return pub_id, c.messages[-1], outcome


def run_message(c, message, *, header=True, **request_changes):
    task = {
        "recording.transcribe": c.task.transcribe_recording,
        "recording.analyze_transcript": c.task.analyze_transcript,
        "recording.verify_transcript_summary": c.task.verify_transcript_summary,
        "recording.persist_result": c.task.persist_recording_result,
    }[message.task]
    request = dict(
        id=message.task_id,
        root_id=message.attempt_id,
        parent_id=message.predecessor_task_id,
        retries=message.retry_ordinal,
        headers={
            MANAGED_HEADER: dict(
                version=1,
                command_id=message.command_id,
                publication_id=message.publication_id,
                payload_digest=message.payload_digest,
            )
        }
        if header
        else {},
        delivery_info={"routing_key": MANAGED_QUEUE},
        chain=None,
        callbacks=None,
        errbacks=None,
    )
    request.update(request_changes)
    task.push_request(**request)
    try:
        return task.run(*message.args)
    finally:
        task.pop_request()


def advance_to(c, stage):
    command_id = c.command_id
    while True:
        with c.source() as db:
            command = db.get(RecordingStageCommand, command_id)
            if command.stage == stage:
                return command_id
        _, message, _ = publish(c, command_id)
        run_message(c, message)
        with c.source() as db:
            command_id = db.scalar(
                select(RecordingStageCommand.command_id).where(
                    RecordingStageCommand.predecessor_id == command_id
                )
            )
        assert command_id is not None


def test_four_fixed_stages_atomic_successors_and_completed_replay(pipeline):
    c = pipeline
    command_id = c.command_id
    attempt = None
    for stage in (
        "transcribe",
        "analyze_transcript",
        "verify_transcript_summary",
        "persist_result",
    ):
        pub_id, message, outcome = publish(c, command_id)
        assert outcome == "acknowledged" and message.task == "recording." + stage
        attempt = attempt or message.attempt_id
        result = run_message(c, message)
        assert (
            result == c.recording_id
            if stage == "persist_result"
            else result["attempt_id"] == attempt
        )
        with pytest.raises(Ignore):
            run_message(c, message)
        with c.source() as db:
            command = db.get(RecordingStageCommand, command_id)
            assert command.state == "succeeded" and command.execution_token
            following = db.scalar(
                select(RecordingStageCommand).where(
                    RecordingStageCommand.predecessor_id == command_id
                )
            )
            if stage == "persist_result":
                assert following is None and message.task_id == attempt
                row = db.get(Recording, c.recording_id)
                assert row.celery_task_id is None and row.summary_status == "done"
                assert db.get(RecordingResult, row.id).summary_text == "Summary"
            else:
                assert following is not None
                command_id = following.command_id
        with c.core() as db:
            assert reconcile_publication(db, pub_id) == "consumed"
    assert len(c.calls) == 3 and len(c.messages) == 4


def test_concurrent_source_claim_enters_remote_once(pipeline, monkeypatch):
    c = pipeline
    _, message, _ = publish(c)
    entered, release, duplicate_entered = Event(), Event(), Event()
    factories = [c.factory(c.source_role), c.factory(c.source_role)]
    pids = {}

    def held(_):
        entered.set()
        assert release.wait(20)

    c.on_asr = held

    # Separate one-connection pools model two workers. Each task still owns
    # one Session; adding an outer fence connection would exhaust its pool.
    def worker_session(index):
        def session():
            db = factories[index]()
            pids[index] = db.scalar(text("SELECT pg_backend_pid()"))
            if index == 1:
                duplicate_entered.set()
            return db

        return session

    sessions = [worker_session(0), worker_session(1)]
    worker = local()
    monkeypatch.setattr(c.task, "_db_session", lambda: sessions[worker.index]())

    def run(index):
        worker.index = index
        if index == 1:
            with pytest.raises(Ignore):
                run_message(c, message)
        else:
            return run_message(c, message)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, 0)
        try:
            assert entered.wait(10)
            duplicate = pool.submit(run, 1)
            assert duplicate_entered.wait(10)
            wait_for_blockers(sessionmaker(c.world.engine), pids[1], {pids[0]})
            assert not duplicate.done()
        finally:
            release.set()
        first.result(timeout=10)
        duplicate.result(timeout=10)
    with c.source() as db:
        assert db.get(RecordingStageCommand, c.command_id).state == "succeeded"
        assert len(db.scalars(select(RecordingStageCommand)).all()) == 2
    assert c.calls == ["asr"]


def test_transient_remote_unknown_keeps_running_token_no_retry_or_successor(pipeline):
    c = pipeline
    _, message, _ = publish(c)
    c.on_asr = lambda callback: (_ for _ in ()).throw(
        c.task.TransientError("synthetic remote unknown")
    )
    with pytest.raises(RecordingCommandError, match="remote_outcome_unknown"):
        run_message(c, message)
    with c.source() as db:
        command = db.get(RecordingStageCommand, c.command_id)
        token = command.execution_token
        assert command.state == "running" and token
        assert db.get(Recording, c.recording_id).celery_task_id == message.attempt_id
        assert len(db.scalars(select(RecordingStageCommand)).all()) == 1
    with pytest.raises(Ignore):
        run_message(c, message)
    assert c.calls == ["asr"]


@pytest.mark.parametrize("accepted", [False, True])
def test_source_claim_commit_unknown_never_invokes_remote_or_rewrites(
    pipeline, accepted, monkeypatch
):
    c = pipeline
    _, message, _ = publish(c)
    original = c.task._db_session

    def session():
        db = original()
        commit = db.commit

        def lost():
            if accepted:
                commit()
            raise OSError("synthetic commit outcome")

        db.commit = lost
        return db

    monkeypatch.setattr(c.task, "_db_session", session)
    with pytest.raises(RecordingCommandCommitUnknown):
        run_message(c, message)
    with c.source() as db:
        command = db.get(RecordingStageCommand, c.command_id)
        assert command.state == ("running" if accepted else "pending")
        assert db.get(Recording, c.recording_id).celery_task_id == message.attempt_id
    assert not c.calls


@pytest.mark.parametrize("accepted", [False, True])
def test_final_result_commit_unknown_has_atomic_successor(pipeline, accepted):
    c = pipeline
    _, message, _ = publish(c)
    original = c.task._commit_recording_phase
    commits = []

    def commit(db):
        commits.append(True)
        if len(commits) == 4:
            if accepted:
                original(db)
            raise c.task.RecordingPhaseCommitUnknown("synthetic final acknowledgement loss")
        original(db)

    c.task._commit_recording_phase = commit
    try:
        with pytest.raises(c.task.RecordingPhaseCommitUnknown):
            run_message(c, message)
    finally:
        c.task._commit_recording_phase = original
    with c.source() as db:
        command = db.get(RecordingStageCommand, c.command_id)
        following = db.scalars(
            select(RecordingStageCommand).where(
                RecordingStageCommand.predecessor_id == c.command_id
            )
        ).all()
        assert command.state == ("succeeded" if accepted else "running")
        assert len(following) == int(accepted)
        result = db.get(RecordingResult, c.recording_id)
        assert (result is not None and result.transcript_text == "Transcript") == accepted
    with pytest.raises(Ignore):
        run_message(c, message)
    assert c.calls == ["asr"]


def test_successor_insert_rejection_rolls_back_result_and_completion(pipeline, monkeypatch):
    c = pipeline
    _, message, _ = publish(c)
    commands = c.task.managed_pipeline
    original = commands._new_command

    def invalid(*args, **kwargs):
        following = original(*args, **kwargs)
        following.retry_ordinal = 99
        return following

    monkeypatch.setattr(commands, "_new_command", invalid)
    with pytest.raises(c.task.RecordingPhaseCommitUnknown):
        run_message(c, message)
    with c.source() as db:
        assert db.get(RecordingStageCommand, c.command_id).state == "running"
        assert db.get(RecordingResult, c.recording_id) is None
        assert len(db.scalars(select(RecordingStageCommand)).all()) == 1
    assert c.calls == ["asr"]
