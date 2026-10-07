"""Explicit current Source worksets: no request creation or compute authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError, StatementError
from sqlalchemy.orm import Session

from test_file_extraction_access import managed, other_actor, recapture
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_extraction_commands import bound, c as c, current, invoke
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    wait_for_blocker,
    world as world,
)
from miy_api.domains.auth.models import AuthSession
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files import extraction_runner as runner_module
from miy_api.domains.files.extraction_contracts import (
    FileExtractionCommitUnknown,
    FileExtractionComputedResult,
    FileExtractionRefused,
)
from miy_api.domains.files.extraction_runner import FileExtractionRunner
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFolder,
)
from miy_api.domains.files.source_extraction_bootstrap import (
    FileExtractionBootstrapMember,
    FileExtractionBootstrapProbe,
    FileExtractionBootstrapWorkset,
)
from miy_api.domains.official_apps.file_extraction_models import FileExtractionRequest
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import (
    append_projection_intent,
    lock_projection_source,
)
from miy_api.domains.retrieval.partitioning import create_managed_partition


def workset(c, *, ids=None, actor=None, execution=None):
    return FileExtractionBootstrapWorkset(
        actor_user_id=actor or c.spec.actor_user_id,
        execution_ref=execution or c.spec.execution_ref,
        file_ids=ids or (c.spec.file_id,),
    )


def snapshot(c):
    with Session(c.engine) as db:
        return (
            current(c).__dict__,
            tuple(
                db.scalars(
                    select(FileExtractionRequest.request_id).order_by(
                        FileExtractionRequest.request_id
                    )
                )
            ),
            tuple(
                db.scalars(
                    select(OfficialProjectionOutbox.event_id).order_by(
                        OfficialProjectionOutbox.event_id
                    )
                )
            ),
        )


def add_pending(c, file_id, *, corpus_id=None, partition=None):
    partition = partition or c.roles.partition
    with Session(c.engine) as db:
        db.add(
            FileManagerFile(
                id=file_id,
                owner_id=c.spec.actor_user_id,
                filename="Synthetic workset.txt",
                content_type="text/plain",
                size_bytes=14,
                storage_key="synthetic-workset/" + file_id,
                visibility="private",
                retrieval_partition_id=partition,
                corpus_id=corpus_id,
                extraction_status="pending",
                extraction_blocks=[],
                extraction_metadata={},
            )
        )
        db.flush()
        append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file_id,
                retrieval_partition_id=partition,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=uuid4(),
        )
        db.commit()


def two_corpora(c):
    identifiers = ("00000000-0000-0000-0000-000000000001", "ffffffff-ffff-ffff-ffff-ffffffffffff")
    with Session(c.world.engine) as db:
        extra_partition = str(
            create_managed_partition(
                db, source_namespace="files", candidate_scope_kind="company"
            ).id
        )
        db.commit()
    partitions = (extra_partition, c.roles.partition)
    with Session(c.engine) as db:
        for identifier, partition in zip(identifiers, partitions, strict=True):
            db.add(
                FileManagerCorpus(
                    id=identifier,
                    name="Synthetic aggregate",
                    created_by_id=c.spec.actor_user_id,
                    retrieval_partition_id=partition,
                )
            )
        db.commit()
    return tuple(zip(identifiers, partitions, strict=True))


@pytest.fixture
def effect_trap(c, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("workset probe invoked an extraction or event effect")

    monkeypatch.setattr(commands, "_read_source", forbidden)
    monkeypatch.setattr(commands, "append_projection_intent", forbidden)
    monkeypatch.setattr(runner_module, "compute_local_file_extraction", forbidden)
    statements = []

    def sql(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().lower()
        assert not normalized.startswith(("insert", "update", "delete", "copy", "truncate"))
        assert not any(
            name in normalized
            for name in (
                "retrieval_partitions",
                "retrieval_projection_events",
                "retrieval_projection_heads",
                "rag_sync_jobs",
                "search_index_jobs",
            )
        )
        statements.append(normalized.split(None, 1)[0])

    event.listen(c.engine, "before_cursor_execute", sql)
    try:
        yield statements
    finally:
        event.remove(c.engine, "before_cursor_execute", sql)


@pytest.mark.parametrize(
    "ids", [(), tuple(str(i) for i in range(101)), (" ",), ("x\x00y",), ("x" * 37,)]
)
def test_explicit_workset_bounds_and_identity(ids):
    with pytest.raises(ValidationError):
        FileExtractionBootstrapWorkset(
            actor_user_id="actor", execution_ref="execution", file_ids=ids
        )


def test_workset_sorts_deduplicates_and_has_no_global_coverage_claim():
    selected = FileExtractionBootstrapWorkset(
        actor_user_id="actor", execution_ref="private-execution", file_ids=("b", "a", "b")
    )
    assert selected.file_ids == ("a", "b") and "private-execution" not in repr(selected)
    assert not any(hasattr(selected, key) for key in ("cursor", "complete", "skip_locked"))
    with pytest.raises(ValueError, match="status only"):
        FileExtractionBootstrapMember("file", "reserved_other_execution", current_input=object())


def test_stage_revalidates_malformed_typed_copy_before_source_sql(c):
    malformed = workset(c).model_copy(update={"file_ids": tuple(str(i) for i in range(101))})
    calls = []

    def sql(*args):
        calls.append("sql")

    event.listen(c.engine, "before_cursor_execute", sql)
    try:
        with pytest.raises(FileExtractionRefused) as error:
            c.runner.probe_bootstrap(malformed)
        assert error.value.reason == "source_contract_invalid"
        assert error.value.__cause__ is None and calls == [] and c.reads == []
    finally:
        event.remove(c.engine, "before_cursor_execute", sql)


def test_unrequested_stage_remains_provisional_and_rolls_back_without_writes(
    c, effect_trap, monkeypatch
):
    before = snapshot(c)
    with Session(c.engine) as db:
        monkeypatch.setattr(db, "commit", lambda: pytest.fail("stage committed caller Session"))
        observed = commands.probe_file_extraction_workset(db, workset=workset(c))
        assert observed.provisional and db.in_transaction()
        (member,) = observed.members
        assert member.disposition == "unrequested" and member.current_input == c.spec.expected_input
        assert member.spec is None and member.receipt is None
        db.rollback()
    assert snapshot(c) == before and c.reads == [] and effect_trap


def test_owned_ack_unrequested_has_no_new_ids_or_effects(c, effect_trap):
    before = snapshot(c)
    observed = c.runner.probe_bootstrap(workset(c))
    assert not observed.provisional and observed.members[0].disposition == "unrequested"
    assert snapshot(c) == before and c.reads == []


@pytest.mark.parametrize("state", ["prepared", "claimed", "input_bound", "ocr_required"])
def test_exact_existing_observation_is_not_a_compute_permit(c, monkeypatch, state):
    c.runner.prepare(c.spec)
    if state == "claimed":
        invoke(c, commands.claim_file_extraction)
    elif state in {"input_bound", "ocr_required"}:
        item = bound(c)
        if state == "ocr_required":
            invoke(
                c,
                commands.apply_file_extraction_result,
                computed_result=FileExtractionComputedResult(
                    "ocr_required", item.receipt.input_sha256
                ),
            )
    before = snapshot(c)
    reads = list(c.reads)
    monkeypatch.setattr(commands, "_read_source", lambda _: pytest.fail("probe read storage"))
    monkeypatch.setattr(
        runner_module, "compute_local_file_extraction", lambda _: pytest.fail("probe computed")
    )
    observed = c.runner.probe_bootstrap(workset(c))
    (member,) = observed.members
    assert member.disposition == ("existing_prepared" if state == "prepared" else "existing_bound")
    assert member.spec == c.spec and member.current_input == c.spec.expected_input
    assert (member.receipt.request_id, member.receipt.result_id, member.receipt.event_id) == (
        c.spec.request_id,
        c.spec.result_id,
        c.spec.event_id,
    )
    assert not member.receipt.provisional and not member.receipt.newly_acquired
    assert member.receipt.state == ("input_bound" if state == "ocr_required" else state)
    assert member.receipt.hold_reason == ("ocr_required" if state == "ocr_required" else None)
    assert snapshot(c) == before and c.reads == reads
    if state == "prepared":
        with Session(c.engine) as db:
            staged = commands.probe_file_extraction_workset(db, workset=workset(c))
            assert staged.provisional and staged.members[0].receipt.provisional
            assert not staged.members[0].receipt.newly_acquired


@pytest.mark.parametrize("different_actor", [False, True])
def test_other_execution_exposes_status_only(c, monkeypatch, different_actor):
    actor, execution = other_actor(c)
    if different_actor:
        with Session(c.engine) as db:
            db.get(FileManagerFile, c.spec.file_id).visibility = "company"
            db.commit()
        recapture(c)
    else:
        actor = c.spec.actor_user_id
        execution = str(uuid4())
        with Session(c.world.engine) as db:
            db.add(
                AuthSession(
                    id=execution,
                    user_id=actor,
                    token_hash=uuid4().hex + uuid4().hex,
                    expires_at=commands._clock() + timedelta(hours=1),
                )
            )
            db.commit()
    c.runner.prepare(c.spec)
    before = snapshot(c)
    observed = c.runner.probe_bootstrap(workset(c, actor=actor, execution=execution))
    (member,) = observed.members
    assert member.disposition == "reserved_other_execution"
    assert (member.current_input, member.spec, member.receipt) == (None, None, None)
    rendered = repr(observed)
    for private in (
        str(c.spec.request_id),
        str(c.spec.result_id),
        str(c.spec.event_id),
        c.spec.digest(),
        c.spec.execution_ref,
        c.spec.expected_input.storage_key,
    ):
        assert private not in rendered
    assert snapshot(c) == before and c.reads == []


def test_old_input_request_is_not_coverage_and_probe_does_not_create_retry_ids(c):
    c.runner.prepare(c.spec)
    with Session(c.engine) as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        file.filename = "Synthetic changed input.txt"
        db.flush()
        event_ref = append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file.id,
                retrieval_partition_id=c.roles.partition,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=uuid4(),
        )
        new_event_id = event_ref.event_id
        db.commit()
    before = snapshot(c)
    (member,) = c.runner.probe_bootstrap(workset(c)).members
    assert member.disposition == "unrequested" and member.spec is None and member.receipt is None
    assert str(member.current_input.pending_event_id) == str(new_event_id)
    assert member.current_input.fingerprint() != c.spec.expected_input.fingerprint()
    assert snapshot(c) == before and c.reads == []


@pytest.mark.parametrize("outcome", ["ready", "unsupported", "failed"])
def test_terminal_history_is_not_current_pending_workset_coverage(c, outcome):
    if outcome == "ready":
        c.runner.run(c.spec, claim_token=c.token)
    else:
        item = bound(c)
        invoke(
            c,
            commands.apply_file_extraction_result,
            computed_result=FileExtractionComputedResult(outcome, item.receipt.input_sha256),
        )
    before = snapshot(c)
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.probe_bootstrap(workset(c))
    assert error.value.reason == "pending_source_required" and snapshot(c) == before


@pytest.mark.parametrize("revoke", [False, True])
def test_actual_managed_current_acl_remains_required(c, revoke):
    actor, execution = other_actor(c)
    grant_id = managed(c, actor)
    if revoke:
        with Session(c.engine) as db:
            db.delete(db.get(FileManagerFileAccessGrant, grant_id))
            db.commit()
        with pytest.raises(FileExtractionRefused) as error:
            c.runner.probe_bootstrap(workset(c, actor=actor, execution=execution))
        assert error.value.reason == "current_source_acl_denied"
    else:
        (member,) = c.runner.probe_bootstrap(workset(c, actor=actor, execution=execution)).members
        assert (
            member.disposition == "unrequested"
            and member.current_input.source_version == "synthetic-v1"
        )
    assert current(c).state is None and c.reads == []


@pytest.mark.parametrize("change", ["session", "app"])
def test_stream_wait_rechecks_current_authority_without_writes(c, change):
    before = snapshot(c)
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_projection_source(blocker, "file_manager_file", c.spec.file_id)
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(c.runner.probe_bootstrap, workset(c))
        try:
            wait_for_blocker(c.world, pid)
            with c.world.connect() as db:
                if change == "session":
                    db.execute(
                        "UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                        [c.spec.execution_ref],
                    )
                else:
                    db.execute("UPDATE company_app_controls SET enabled=false WHERE app_id='files'")
        finally:
            blocker.rollback()
        with pytest.raises(FileExtractionRefused) as error:
            future.result(timeout=8)
    assert error.value.reason == (
        "current_execution_denied" if change == "session" else "current_actor_or_app_denied"
    )
    assert snapshot(c) == before and c.reads == []


def test_multifile_rechecks_earlier_acl_after_later_member_wait(c):
    actor, execution = other_actor(c)
    lower, higher = "00000000-0000-0000-0000-000000000001", "ffffffff-ffff-ffff-ffff-ffffffffffff"
    for identifier in (lower, higher):
        add_pending(c, identifier)
    with Session(c.engine) as db:
        folder = FileManagerFolder(
            id=str(uuid4()),
            owner_id=c.spec.actor_user_id,
            name="Synthetic workset folder",
            visibility="company",
        )
        db.add(folder)
        db.flush()
        for identifier in (lower, higher):
            file = db.get(FileManagerFile, identifier)
            file.visibility = "company"
        db.get(FileManagerFile, lower).folder_id = folder.id
        folder_id = folder.id
        db.commit()
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_projection_source(blocker, "file_manager_file", higher)
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(
            c.runner.probe_bootstrap,
            workset(c, ids=(higher, lower), actor=actor, execution=execution),
        )
        try:
            wait_for_blocker(c.world, pid)
            with c.world.connect(c.roles.source) as db:
                db.execute(
                    "UPDATE file_manager_folders SET visibility='private' WHERE id=%s", [folder_id]
                )
        finally:
            blocker.rollback()
        with pytest.raises(FileExtractionRefused) as error:
            future.result(timeout=8)
    assert (
        error.value.reason == "current_source_acl_denied"
        and current(c).state is None
        and c.reads == []
    )


def test_multifile_locked_low_id_and_later_low_id_are_not_skipped(c):
    lower = "00000000-0000-0000-0000-000000000001"
    add_pending(c, lower)
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_projection_source(blocker, "file_manager_file", lower)
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(c.runner.probe_bootstrap, workset(c, ids=(c.spec.file_id, lower)))
        try:
            wait_for_blocker(c.world, pid)
            assert not future.done()
        finally:
            blocker.rollback()
        observed = future.result(timeout=8)
    assert tuple(member.file_id for member in observed.members) == tuple(
        sorted((lower, c.spec.file_id))
    )
    assert all(member.disposition == "unrequested" for member in observed.members)
    later = "00000000-0000-0000-0000-000000000000"
    add_pending(c, later)
    assert c.runner.probe_bootstrap(workset(c, ids=(later,))).members[0].file_id == later
    assert not hasattr(observed, "complete") and c.reads == []


def test_all_corpora_precede_files_with_reverse_file_order_and_tree_participant(c):
    (first_corpus, first_partition), (last_corpus, last_partition) = two_corpora(c)
    lower_file, higher_file = (
        "00000000-0000-0000-0000-000000000002",
        "ffffffff-ffff-ffff-ffff-fffffffffffe",
    )
    add_pending(c, lower_file, corpus_id=last_corpus, partition=last_partition)
    add_pending(c, higher_file, corpus_id=first_corpus, partition=first_partition)
    errors = []
    observed = None
    with Session(c.engine) as tree, ThreadPoolExecutor(max_workers=1) as pool:
        tree.scalar(
            select(FileManagerCorpus.id)
            .where(FileManagerCorpus.id == first_corpus)
            .with_for_update()
        )
        pid = tree.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(c.runner.probe_bootstrap, workset(c, ids=(higher_file, lower_file)))
        try:
            wait_for_blocker(c.world, pid)
            # The tree participant locks the complete sorted corpus set before
            # its subsequent work. A per-File probe would hold the other corpus
            # and create the opposite lock order here.
            try:
                tree.scalar(
                    select(FileManagerCorpus.id)
                    .where(FileManagerCorpus.id == last_corpus)
                    .with_for_update()
                )
                tree.commit()
            except SQLAlchemyError as error:
                errors.append(getattr(error.orig, "sqlstate", "sql_error"))
        finally:
            tree.rollback()
            try:
                observed = future.result(timeout=8)
            except FileExtractionRefused as error:
                errors.append(error.reason)
    assert errors == []
    assert observed is not None and tuple(m.file_id for m in observed.members) == (
        lower_file,
        higher_file,
    )
    assert all(m.disposition == "unrequested" for m in observed.members) and c.reads == []


@pytest.mark.parametrize("original_corpus", [False, True])
def test_rediscovered_association_refuses_before_unexpected_corpus_lock(
    c, monkeypatch, original_corpus
):
    (old_corpus, old_partition), (new_corpus, new_partition) = two_corpora(c)

    def change_binding(corpus_id, partition):
        with Session(c.engine) as db:
            file = db.get(FileManagerFile, c.spec.file_id)
            file.corpus_id, file.retrieval_partition_id = corpus_id, partition
            db.flush()
            append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=file.id,
                    retrieval_partition_id=partition,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                ),
                event_id=uuid4(),
            )
            db.commit()

    if original_corpus:
        change_binding(old_corpus, old_partition)
    original_file = commands._file
    changed, unexpected_locks = [], []

    def file(db, file_id, **kwargs):
        if not changed:
            change_binding(new_corpus, new_partition)
            changed.append(True)
        return original_file(db, file_id, **kwargs)

    def sql(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lower()
        if "from file_manager_corpora" in normalized and "for share" in normalized:
            values = parameters.values() if isinstance(parameters, dict) else parameters
            # Keep only a Boolean from synthetic parameters, never log row keys.
            if new_corpus in values:
                unexpected_locks.append(True)

    monkeypatch.setattr(commands, "_file", file)
    event.listen(c.engine, "before_cursor_execute", sql)
    try:
        with pytest.raises(FileExtractionRefused) as error:
            c.runner.probe_bootstrap(workset(c))
        assert error.value.reason == "source_binding_changed"
        assert changed == [True] and unexpected_locks == [] and c.reads == []
    finally:
        event.remove(c.engine, "before_cursor_execute", sql)
    with Session(c.engine) as db:
        assert db.get(FileManagerFile, c.spec.file_id).corpus_id == new_corpus
        assert db.scalar(select(FileExtractionRequest.request_id)) is None


def test_concurrent_probes_create_no_request_or_effect(c):
    before = snapshot(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        observations = list(pool.map(lambda _: c.runner.probe_bootstrap(workset(c)), range(2)))
    assert all(
        r.members[0].disposition == "unrequested" and not r.provisional for r in observations
    )
    assert snapshot(c) == before and c.reads == []


@pytest.mark.parametrize("when", ["before", "after"])
def test_probe_unknown_ack_and_close_failure_retain_private_observation_without_retry(
    c, monkeypatch, when
):
    c.runner.prepare(c.spec)
    before = snapshot(c)
    original_commit, original_close = Session.commit, Session.close
    commits, closes = [], []

    def commit(db):
        if db.info.get("extraction_test_owned"):
            commits.append(True)
            if when == "after":
                original_commit(db)
            raise StatementError(
                "synthetic sensitive commit", "synthetic SQL", {"key": "private"}, RuntimeError()
            )
        original_commit(db)

    def close(db):
        original_close(db)
        if db.info.get("extraction_test_owned"):
            closes.append(True)
            raise StatementError("synthetic sensitive close", None, None, RuntimeError())

    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(Session, "close", close)
    with pytest.raises(FileExtractionCommitUnknown) as error:
        c.runner.probe_bootstrap(workset(c))
    unknown = error.value
    assert (
        unknown.phase == "bootstrap_probe" and unknown.receipt is None and unknown.__cause__ is None
    )
    retained = unknown._retained_result
    assert isinstance(retained, FileExtractionBootstrapProbe) and retained.provisional
    (member,) = retained.members
    assert (
        member.spec == c.spec and member.receipt.provisional and not member.receipt.newly_acquired
    )
    assert (
        member.receipt.request_id == c.spec.request_id
        and member.receipt.request_digest == c.spec.digest()
    )
    assert commits == [True] and closes == [True] and snapshot(c) == before and c.reads == []


def test_successful_probe_ack_survives_cleanup_failure(c, monkeypatch):
    original = Session.close

    def close(db):
        original(db)
        if db.info.get("extraction_test_owned"):
            raise StatementError("synthetic private cleanup", None, None, RuntimeError())

    monkeypatch.setattr(Session, "close", close)
    observed = c.runner.probe_bootstrap(workset(c))
    assert (
        not observed.provisional
        and observed.members[0].disposition == "unrequested"
        and c.reads == []
    )


def test_probe_database_refusal_is_stable_and_cleanup_does_not_replace_it(c, monkeypatch):
    original_admit = commands._admit

    def admit(db, request_id=None):
        original_admit(db, request_id)
        raise StatementError(
            "synthetic private SQL", "synthetic statement", {"key": "private"}, RuntimeError()
        )

    original_close, original_rollback = Session.close, Session.rollback

    def close(db):
        original_close(db)
        if db.info.get("extraction_test_owned"):
            raise RuntimeError("synthetic cleanup")

    def rollback(db):
        original_rollback(db)
        if db.info.get("extraction_test_owned"):
            raise RuntimeError("synthetic cleanup")

    monkeypatch.setattr(commands, "_admit", admit)
    monkeypatch.setattr(Session, "close", close)
    monkeypatch.setattr(Session, "rollback", rollback)
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.probe_bootstrap(workset(c))
    assert (
        error.value.reason == "source_database_refused"
        and error.value.__cause__ is None
        and c.reads == []
    )


def test_probe_refuses_borrowed_session_without_closing_marker(c, monkeypatch):
    with Session(c.engine) as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        file.extraction_metadata = {"synthetic_caller_marker": True}
        db.flush()
        outer = db.get_transaction()
        monkeypatch.setattr(db, "close", lambda: pytest.fail("borrowed Session close"))
        try:
            with pytest.raises(FileExtractionRefused) as error:
                FileExtractionRunner(lambda: db).probe_bootstrap(workset(c))
            assert error.value.reason == "fresh_clean_outer_transaction_required"
            assert db.get_transaction() is outer and db.get(
                FileManagerFile, file.id
            ).extraction_metadata == {"synthetic_caller_marker": True}
        finally:
            monkeypatch.undo()
