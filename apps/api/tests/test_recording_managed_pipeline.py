"""Restricted real PostgreSQL identities; all broker/provider calls synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from types import SimpleNamespace
from uuid import uuid4

from celery.exceptions import Ignore
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from company_admission_fixture import seed_company_app_access
from test_independent_app_data import isolated_data_cluster  # noqa: F401
from test_official_writer_fence import wait_for_blockers
from miy_api.domains.official_apps.writer import transition
from miy_api.domains.official_apps.writer_roles import revoke_principal
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
    from miy_api.domains.official_apps.recording_roles import prepare_core_principal
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
    yield c
    for engine in engines:
        engine.dispose()


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


def test_duplicate_across_progress_commit_cannot_reenter_remote(pipeline):
    c = pipeline
    _, message, _ = publish(c)

    # Reentrant duplicate while the original holds source locks would wait on
    # the Recording row. Instead test the exact durable handoff after commit,
    # before the original reacquires; hook only that acknowledged commit.
    original = c.task._commit_recording_phase
    seen = []

    def commit(db):
        original(db)
        seen.append(True)
        if len(seen) == 2:
            with pytest.raises(Ignore):
                run_message(c, message)

    c.task._commit_recording_phase = commit
    try:
        run_message(c, message)
    finally:
        c.task._commit_recording_phase = original
    assert c.calls.count("asr") == 1


def test_concurrent_core_preparation_returns_one_immutable_binding(pipeline):
    c = pipeline
    factories = [c.factory(c.core_role), c.factory(c.core_role)]
    inserts = Barrier(2)

    def simultaneous_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO core_recording_publications"):
            inserts.wait(timeout=10)

    for factory in factories:
        event.listen(factory.kw["bind"], "before_cursor_execute", simultaneous_insert)

    def prepare(factory):
        with factory() as db:
            return prepare_publication(db, c.command_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prepare, factories))
    assert results[0] == results[1]
    from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication

    with c.core() as db:
        rows = db.scalars(select(CoreRecordingPublication)).all()
        assert len(rows) == 1 and rows[0].publication_id == results[0]
        assert rows[0].state == "pending" and rows[0].publication_token is None
    assert not c.messages and not c.calls


def test_concurrent_send_and_reconcile_wait_for_same_publication_claim(pipeline):
    c = pipeline
    with c.core() as db:
        pub_id = prepare_publication(db, c.command_id)
    sending, release, send_entered, reconcile_entered = Event(), Event(), Event(), Event()
    pids = {}
    factories = [c.factory(c.core_role) for _ in range(3)]

    def first_send():
        with factories[0]() as db:
            pids["first"] = db.scalar(text("SELECT pg_backend_pid()"))

            def held(message):
                c.messages.append(message)
                sending.set()
                assert release.wait(20)

            return send_publication(db, pub_id, publish=held)

    def competing_send():
        with factories[1]() as db:
            pids["second"] = db.scalar(text("SELECT pg_backend_pid()"))
            send_entered.set()
            with pytest.raises(RecordingCommandError, match="not_sendable"):
                send_publication(db, pub_id, publish=c.messages.append)

    def observer():
        with factories[2]() as db:
            pids["observer"] = db.scalar(text("SELECT pg_backend_pid()"))
            reconcile_entered.set()
            return reconcile_publication(db, pub_id)

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(first_send)
        try:
            assert sending.wait(10)
            second = pool.submit(competing_send)
            assert send_entered.wait(10)
            wait_for_blockers(sessionmaker(c.world.engine), pids["second"], {pids["first"]})
            observed = pool.submit(observer)
            assert reconcile_entered.wait(10)
            assert not second.done() and not observed.done()
        finally:
            release.set()
        assert first.result(timeout=10) == "acknowledged"
        second.result(timeout=10)
        assert observed.result(timeout=10) == "acknowledged"
    assert len(c.messages) == 1 and not c.calls


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


@pytest.mark.parametrize("stage", ["analyze_transcript", "verify_transcript_summary"])
def test_summary_remote_unknown_retains_exact_claim_without_retry(pipeline, monkeypatch, stage):
    c = pipeline
    command_id = advance_to(c, stage)
    _, message, _ = publish(c, command_id)
    previous_calls = list(c.calls)

    def unknown(*args, **kwargs):
        c.calls.append(kwargs["source"])
        raise c.task.TransientError("synthetic accepted summary response loss")

    def no_retry(*args, **kwargs):
        pytest.fail("managed unknown cannot request Celery retry")

    monkeypatch.setattr(c.task, "_complete_local_agent", unknown)
    monkeypatch.setattr(getattr(c.task, stage), "retry", no_retry)
    with pytest.raises(RecordingCommandError, match="remote_outcome_unknown"):
        run_message(c, message)
    with c.source() as db:
        command = db.get(RecordingStageCommand, command_id)
        token = command.execution_token
        assert command.state == "running" and token
        assert db.get(Recording, c.recording_id).celery_task_id == message.attempt_id
        assert not db.scalar(
            select(RecordingStageCommand.command_id).where(
                RecordingStageCommand.predecessor_id == command_id
            )
        )
        result = db.get(RecordingResult, c.recording_id)
        assert result.transcript_text == "Transcript" and result.verifier_note is None
        assert result.summary_text == ("Summary" if stage == "verify_transcript_summary" else None)
    with pytest.raises(Ignore):
        run_message(c, message)
    assert len(c.calls) == len(previous_calls) + 1


@pytest.mark.parametrize("stage", ["transcribe", "analyze_transcript", "verify_transcript_summary"])
@pytest.mark.parametrize("boundary", ["publisher", "worker"])
def test_current_source_bytes_are_rechecked_before_delivery_effect(pipeline, stage, boundary):
    c = pipeline
    command_id = advance_to(c, stage)
    previous_calls = list(c.calls)
    previous_messages = len(c.messages)
    with c.core() as db:
        pub_id = prepare_publication(db, command_id)
    if boundary == "worker":
        _, message, _ = publish(c, command_id)
    with c.source() as db:
        if stage == "transcribe":
            db.get(Recording, c.recording_id).storage_key = "synthetic/changed-object"
        else:
            result = db.get(RecordingResult, c.recording_id)
            if stage == "analyze_transcript":
                result.transcript_text = "Changed transcript at same version"
            else:
                result.summary_text = "Changed summary at same version"
        db.commit()
    with pytest.raises(RecordingCommandError, match="source_changed"):
        if boundary == "publisher":
            with c.core() as db:
                send_publication(db, pub_id, publish=c.messages.append)
        else:
            run_message(c, message)
    with c.source() as db:
        assert db.get(RecordingStageCommand, command_id).state == "pending"
    assert c.calls == previous_calls
    assert len(c.messages) == previous_messages + int(boundary == "worker")


def test_revoked_actual_producer_stops_core_and_worker_before_effect(pipeline):
    c = pipeline
    pub_id, message, _ = publish(c)
    with c.world.connect() as conn:
        oid = conn.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (c.source_role,)
        ).fetchone()[0]
    with Session(c.world.engine) as db:
        revoke_principal(db, c.world.actor, role_oid=oid, expected=ACTIVE, expected_state="active")
        db.commit()
    with c.core() as db, pytest.raises(DBAPIError) as core_denied:
        reconcile_publication(db, pub_id)
    with pytest.raises(DBAPIError) as source_denied:
        run_message(c, message)
    assert core_denied.value.orig.sqlstate == source_denied.value.orig.sqlstate == "55000"
    assert not c.calls


@pytest.mark.parametrize("change", ["header", "id", "queue", "chain", "digest", "retries"])
def test_invalid_or_missing_envelope_denies_before_effect(pipeline, change):
    c = pipeline
    _, message, _ = publish(c)
    modifications = {
        "id": dict(id=str(uuid4())),
        "queue": dict(delivery_info={"routing_key": "meeting_transcribe"}),
        "chain": dict(chain=[{"task": "recording.persist_result"}]),
        "retries": dict(retries=1),
        "digest": dict(
            headers={
                MANAGED_HEADER: dict(
                    version=1,
                    command_id=message.command_id,
                    publication_id=message.publication_id,
                    payload_digest="0" * 64,
                )
            }
        ),
    }
    with pytest.raises(RecordingCommandError):
        run_message(c, message, header=change != "header", **modifications.get(change, {}))
    assert c.calls == []


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
def test_publish_exception_and_explicit_same_id_reconcile(pipeline, accepted):
    c = pipeline

    def response_loss(message):
        if accepted:
            run_message(c, message)
        raise OSError("synthetic broker response loss")

    pub_id, message, outcome = publish(c, callback=response_loss)
    assert outcome == "unknown"
    with c.core() as db:
        assert reconcile_publication(db, pub_id) == ("consumed" if accepted else "unknown")
    if not accepted:
        with c.core() as db:
            assert (
                send_publication(db, pub_id, republish=True, publish=c.messages.append)
                == "acknowledged"
            )
        assert c.messages[0] == c.messages[1]
        run_message(c, c.messages[1])
    with pytest.raises(Ignore):
        run_message(c, message)
    assert c.calls.count("asr") == 1


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


def test_drain_before_effect_and_publication_reject(pipeline):
    c = pipeline
    pub_id, message, _ = publish(c)
    move(c.world, ACTIVE, "active", state="draining")
    with pytest.raises(DBAPIError):
        run_message(c, message)
    with c.core() as db, pytest.raises(DBAPIError):
        reconcile_publication(db, pub_id)
    assert not c.calls


def test_current_account_revocation_after_claim_stops_remote_without_failure(pipeline):
    c = pipeline
    _, message, _ = publish(c)
    original = c.task._commit_recording_phase

    def commit(db):
        original(db)
        with c.world.connect() as conn:
            conn.execute("UPDATE users SET status='disabled' WHERE id=%s", (c.world.user_id,))

    c.task._commit_recording_phase = commit
    try:
        with pytest.raises(RecordingCommandError, match="access_denied"):
            run_message(c, message)
    finally:
        c.task._commit_recording_phase = original
    with c.source() as db:
        assert db.get(RecordingStageCommand, c.command_id).state == "running"
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


@pytest.mark.parametrize("accepted", [False, True])
def test_publication_ack_commit_unknown_no_followup_or_new_id(pipeline, accepted):
    c = pipeline
    with c.core() as db:
        pub_id = prepare_publication(db, c.command_id)
    with c.core() as db:
        original = db.commit
        commits = []

        def commit():
            commits.append(True)
            if len(commits) == 2:
                if accepted:
                    original()
                raise OSError("synthetic publication COMMIT acknowledgement loss")
            original()

        db.commit = commit
        with pytest.raises(RecordingCommandCommitUnknown):
            send_publication(db, pub_id, publish=c.messages.append)
    from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication

    with c.core() as db:
        row = db.get(CoreRecordingPublication, pub_id)
        assert row.state == ("acknowledged" if accepted else "publishing")
        assert row.command_id == c.command_id
        assert reconcile_publication(db, pub_id) == ("acknowledged" if accepted else "unknown")
    assert len(c.messages) == 1


def test_known_permanent_failure_is_terminal_with_exact_claim(pipeline):
    c = pipeline
    _, message, _ = publish(c)
    c.on_asr = lambda _: (_ for _ in ()).throw(c.task.PermanentError("Synthetic rejected audio"))
    with pytest.raises(Ignore):
        run_message(c, message)
    with c.source() as db:
        assert db.get(RecordingStageCommand, c.command_id).state == "failed"
        row = db.get(Recording, c.recording_id)
        assert row.celery_task_id is None and row.transcript_status == "failed"
        assert len(db.scalars(select(RecordingStageCommand)).all()) == 1


@pytest.mark.parametrize("phase", ["source", "publisher"])
def test_inflight_phase_blocks_drain_until_its_same_session_finishes(pipeline, phase):
    c = pipeline
    entered, release, drain_entered = Event(), Event(), Event()
    pids = {}

    def drain():
        with Session(c.world.engine) as db:
            pids["drain"] = db.scalar(text("SELECT pg_backend_pid()"))
            drain_entered.set()
            transition(
                db,
                c.world.actor,
                request_id=uuid4(),
                expected=ACTIVE,
                expected_state="active",
                owner="legacy",
                state="draining",
                artifact=None,
                reason="Owned managed phase drain",
            )
            db.commit()

    if phase == "source":
        _, message, _ = publish(c)

        def held(_):
            pids["source"] = c.sessions[-1].scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            assert release.wait(20)

        c.on_asr = held

        def execute():
            return run_message(c, message)
    else:
        with c.core() as db:
            pub_id = prepare_publication(db, c.command_id)

        def execute():
            with c.core() as db:

                def held(message):
                    pids["source"] = db.scalar(text("SELECT pg_backend_pid()"))
                    entered.set()
                    assert release.wait(20)

                return send_publication(db, pub_id, publish=held)

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(execute)
        try:
            assert entered.wait(10)
            moving = pool.submit(drain)
            assert drain_entered.wait(10)
            wait_for_blockers(sessionmaker(c.world.engine), pids["drain"], {pids["source"]})
            assert not moving.done()
        finally:
            release.set()
        running.result(timeout=10)
        moving.result(timeout=10)


@pytest.mark.parametrize("old_permissions", [False, True])
def test_legacy_noheader_compatibility_requires_explicit_new_role_reads(pipeline, old_permissions):
    c = pipeline
    recording_id, attempt_id = str(uuid4()), str(uuid4())
    with c.source() as db:
        db.add(
            Recording(
                id=recording_id,
                owner_id=c.world.user_id,
                title="Legacy fixture",
                storage_key="synthetic/" + recording_id,
                audio_status="saved",
                transcript_status="pending",
                summary_status="pending",
                celery_task_id=attempt_id,
            )
        )
        db.commit()
    if old_permissions:
        with c.world.connect() as conn:
            conn.execute(
                sql.SQL("REVOKE SELECT ON public.recording_stage_commands FROM {}").format(
                    sql.Identifier(c.source_role)
                )
            )
        with pytest.raises(DBAPIError) as caught:
            c.task.transcribe_recording.run(recording_id, attempt_id)
        assert caught.value.orig.sqlstate == "42501" and not c.calls
    else:
        assert c.task.transcribe_recording.run(recording_id, attempt_id) == dict(
            recording_id=recording_id, attempt_id=attempt_id
        )
        with c.source() as db:
            assert db.get(Recording, recording_id).transcript_status == "done"
            assert len(db.scalars(select(RecordingStageCommand)).all()) == 1
        assert c.calls == ["asr"]
