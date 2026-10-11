"""Explicit current Source worksets: no request creation or compute authority."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from test_file_extraction_access import (
    managed as managed,
    other_actor as other_actor,
    recapture as recapture,
)
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_extraction_commands import (
    bound as bound,
    c as c,
    current as current,
    invoke as invoke,
)
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    wait_for_blocker as wait_for_blocker,
    world as world,
)
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files import extraction_runner as runner_module
from miy_api.domains.files.extraction_contracts import (
    FileExtractionCommitUnknown,
    FileExtractionRefused,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFolder,
)
from miy_api.domains.files.source_extraction_bootstrap import (
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


@pytest.mark.parametrize("when", ["after"])
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
