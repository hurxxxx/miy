"""Current native/managed ACL and bounded Source storage admission."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from test_file_extraction_commands import bound, c as c, current, invoke
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    wait_for_blocker,
    world as world,
)
from miy_api.domains.auth.models import AuthSession, User
from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files.extraction_contracts import FileExtractionRefused
from miy_api.domains.files.extraction_runner import compute_local_file_extraction
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
    FileManagerFolder,
)
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.pms.space_models import Team, TeamMember
from miy_api.domains.official_apps.projection_outbox import lock_projection_source


def other_actor(c):
    actor, execution = map(str, (uuid4(), uuid4()))
    with Session(c.world.engine) as db:
        db.add(
            User(
                id=actor,
                login_id=actor,
                email="synthetic@fixture.test",
                password_hash="synthetic",
                full_name="Synthetic other",
            )
        )
        db.flush()
        db.add(
            AuthSession(
                id=execution,
                user_id=actor,
                token_hash=uuid4().hex + uuid4().hex,
                expires_at=commands._clock() + timedelta(hours=1),
            )
        )
        db.commit()
    return actor, execution


def recapture(c, actor=None, execution=None):
    actor = actor or c.spec.actor_user_id
    execution = execution or c.spec.execution_ref
    captured = c.runner.capture(
        actor_user_id=actor, execution_ref=execution, file_id=c.spec.file_id
    )
    c.spec = c.spec.model_copy(
        update=dict(actor_user_id=actor, execution_ref=execution, expected_input=captured)
    )


@pytest.mark.parametrize("visible", [False, True])
def test_actual_native_private_denial_company_admission(c, visible):
    actor, execution = other_actor(c)
    if visible:
        with Session(c.engine) as db:
            db.get(FileManagerFile, c.spec.file_id).visibility = "company"
            db.commit()
        recapture(c, actor, execution)
        assert c.runner.run(c.spec, claim_token=c.token).state == "ready"
    else:
        with pytest.raises(FileExtractionRefused) as error:
            c.runner.capture(actor_user_id=actor, execution_ref=execution, file_id=c.spec.file_id)
        assert error.value.reason == "current_source_acl_denied" and c.reads == []


def test_native_folder_acl_remains_required(c):
    actor, execution = other_actor(c)
    with Session(c.engine) as db:
        folder = FileManagerFolder(
            id=str(uuid4()),
            owner_id=c.spec.actor_user_id,
            name="Synthetic folder",
            visibility="private",
        )
        db.add(folder)
        db.flush()
        file = db.get(FileManagerFile, c.spec.file_id)
        file.folder_id = folder.id
        file.visibility = "company"
        db.commit()
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.capture(actor_user_id=actor, execution_ref=execution, file_id=c.spec.file_id)
    assert error.value.reason == "current_source_acl_denied" and c.reads == []


@pytest.mark.parametrize("revoke", [False, True])
def test_native_company_ancestor_current_admission(c, revoke):
    actor, execution = other_actor(c)
    with Session(c.engine) as db:
        parent = FileManagerFolder(
            id=str(uuid4()),
            owner_id=c.spec.actor_user_id,
            name="Synthetic root",
            visibility="company",
        )
        db.add(parent)
        db.flush()
        leaf = FileManagerFolder(
            id=str(uuid4()),
            owner_id=c.spec.actor_user_id,
            name="Synthetic leaf",
            visibility="company",
            parent_id=parent.id,
        )
        db.add(leaf)
        db.flush()
        file = db.get(FileManagerFile, c.spec.file_id)
        file.folder_id = leaf.id
        file.visibility = "company"
        parent_id = parent.id
        db.commit()
    recapture(c, actor, execution)
    if not revoke:
        assert c.runner.run(c.spec, claim_token=c.token).state == "ready"
    else:
        c.runner.prepare(c.spec)
        with Session(c.engine) as db:
            db.get(FileManagerFolder, parent_id).visibility = "private"
            db.commit()
        with pytest.raises(FileExtractionRefused) as error:
            invoke(c, commands.claim_file_extraction)
        assert error.value.reason == "current_source_acl_denied" and c.reads == []


def managed(c, actor):
    with Session(c.engine) as db:
        corpus = FileManagerCorpus(
            id=str(uuid4()),
            name="Synthetic managed",
            created_by_id=c.spec.actor_user_id,
            source_managed=True,
            authorization_mode="explicit_grants",
            retrieval_partition_id=c.roles.partition,
        )
        db.add(corpus)
        db.flush()
        file = db.get(FileManagerFile, c.spec.file_id)
        file.corpus_id = corpus.id
        db.add(
            FileManagerFileSourceMetadata(
                file_id=file.id,
                corpus_id=corpus.id,
                external_id="synthetic-external",
                external_id_sha256="a" * 64,
                source_kind="synthetic",
                source_id="synthetic-source",
                source_id_sha256="b" * 64,
                source_version="synthetic-v1",
                content_checksum=sha256(b"Synthetic text").hexdigest(),
                acl_resolved=True,
            )
        )
        grant = FileManagerFileAccessGrant(
            id=str(uuid4()),
            file_id=file.id,
            grant_type="user",
            target_id=actor,
            grant_key="synthetic-user",
        )
        db.add(grant)
        db.commit()
        return grant.id


@pytest.mark.parametrize("revoke", [False, True])
def test_actual_managed_current_explicit_grants(c, revoke):
    actor, execution = other_actor(c)
    grant = managed(c, actor)
    recapture(c, actor, execution)
    if not revoke:
        assert c.runner.run(c.spec, claim_token=c.token).state == "ready"
    else:
        c.runner.prepare(c.spec)
        invoke(c, commands.claim_file_extraction)
        with Session(c.engine) as db:
            db.delete(db.get(FileManagerFileAccessGrant, grant))
            db.commit()
        with pytest.raises(FileExtractionRefused) as error:
            invoke(c, commands.bind_file_extraction_input)
        assert error.value.reason == "current_source_acl_denied" and c.reads == []
        assert current(c).state == "claimed"


@pytest.mark.parametrize("kind", ["company", "group", "hr_group", "team"])
@pytest.mark.parametrize("revoke", [False, True])
def test_actual_managed_public_grant_query_closure(c, kind, revoke):
    actor, execution = other_actor(c)
    grant_id = managed(c, actor)
    target = None
    if kind in {"group", "hr_group"}:
        target = str(uuid4())
        with Session(c.world.engine) as db:
            db.add(
                Group(
                    id=target,
                    name="Synthetic audience",
                    source="hr" if kind == "hr_group" else "local",
                    **({"slug": target, "unit_type": "team"} if kind == "hr_group" else {}),
                )
            )
            db.flush()
            if kind == "hr_group":
                db.get(User, actor).primary_organization_unit_id = target
            else:
                db.add(GroupMember(group_id=target, user_id=actor))
            db.commit()
    elif kind == "team":
        target = str(uuid4())
        with Session(c.engine) as db:
            db.add(Team(id=target, key=target, name="Synthetic PMS space"))
            db.flush()
            db.add(TeamMember(id=str(uuid4()), team_id=target, user_id=actor, role="member"))
            db.commit()
    with Session(c.engine) as db:
        grant = db.get(FileManagerFileAccessGrant, grant_id)
        grant.grant_type = "group" if kind == "hr_group" else kind
        grant.target_id = target
        db.commit()
    recapture(c, actor, execution)
    if not revoke:
        assert c.runner.run(c.spec, claim_token=c.token).state == "ready"
    else:
        c.runner.prepare(c.spec)
        if kind in {"group", "hr_group"}:
            with Session(c.world.engine) as db:
                db.get(Group, target).active = False
                db.commit()
        else:
            with Session(c.engine) as db:
                if kind == "team":
                    db.get(Team, target).active = False
                else:
                    db.delete(db.get(FileManagerFileAccessGrant, grant_id))
                db.commit()
        with pytest.raises(FileExtractionRefused) as error:
            invoke(c, commands.claim_file_extraction)
        assert error.value.reason == "current_source_acl_denied" and c.reads == []


def test_unresolved_managed_acl_is_not_a_read_grant(c):
    actor, execution = other_actor(c)
    managed(c, actor)
    with Session(c.engine) as db:
        db.get(FileManagerFileSourceMetadata, c.spec.file_id).acl_resolved = False
        db.commit()
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.capture(actor_user_id=actor, execution_ref=execution, file_id=c.spec.file_id)
    assert error.value.reason == "current_source_acl_denied" and c.reads == []


def test_existing_external_checksum_conflict_blocks_input_bind(c):
    managed(c, c.spec.actor_user_id)
    with Session(c.engine) as db:
        db.get(FileManagerFileSourceMetadata, c.spec.file_id).content_checksum = "f" * 64
        db.commit()
    recapture(c)
    c.runner.prepare(c.spec)
    invoke(c, commands.claim_file_extraction)
    with pytest.raises(FileExtractionRefused) as error:
        invoke(c, commands.bind_file_extraction_input)
    assert error.value.reason == "source_bytes_changed" and current(c).state == "claimed"


@pytest.mark.parametrize("change", ["delete", "storage", "partition"])
def test_bound_input_current_file_drift_refuses_apply(c, change):
    item = bound(c)
    with Session(c.engine) as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        if change == "delete":
            file.deleted_at = commands._clock()
        if change == "storage":
            file.storage_key = "synthetic-replacement"
        if change == "partition":
            file.retrieval_partition_id = None
        db.commit()
    with pytest.raises(FileExtractionRefused):
        invoke(
            c,
            commands.apply_file_extraction_result,
            computed_result=compute_local_file_extraction(item),
        )
    assert current(c).state == "input_bound" and len(current(c).events) == 1


def test_prepare_over_10m_is_stable_refusal_before_storage(c):
    with Session(c.engine) as db:
        db.get(FileManagerFile, c.spec.file_id).size_bytes = 10 * 1024 * 1024 + 1
        db.commit()
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.capture(
            actor_user_id=c.spec.actor_user_id,
            execution_ref=c.spec.execution_ref,
            file_id=c.spec.file_id,
        )
    assert error.value.reason == "source_contract_invalid" and c.reads == []


@pytest.mark.parametrize("stage", ["claim", "bind", "apply"])
def test_current_session_expiry_after_stream_wait_refuses_every_active_stage(c, stage):
    c.runner.prepare(c.spec)
    if stage in {"bind", "apply"}:
        invoke(c, commands.claim_file_extraction)
    item = invoke(c, commands.bind_file_extraction_input) if stage == "apply" else None
    function = {
        "claim": commands.claim_file_extraction,
        "bind": commands.bind_file_extraction_input,
        "apply": commands.apply_file_extraction_result,
    }[stage]
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_projection_source(blocker, "file_manager_file", c.spec.file_id)
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(
            invoke,
            c,
            function,
            **({"computed_result": compute_local_file_extraction(item)} if item else {}),
        )
        try:
            wait_for_blocker(c.world, pid)
            with c.world.connect() as core:
                core.execute(
                    "UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                    [c.spec.execution_ref],
                )
        finally:
            blocker.rollback()
        with pytest.raises(FileExtractionRefused):
            future.result(timeout=8)
    assert (
        current(c).state == {"claim": "prepared", "bind": "claimed", "apply": "input_bound"}[stage]
    )
    assert len(c.reads) == (1 if stage == "apply" else 0)


def test_storage_read_retains_actual_file_and_external_metadata_locks(c, monkeypatch):
    managed(c, c.spec.actor_user_id)
    recapture(c)
    c.runner.prepare(c.spec)
    invoke(c, commands.claim_file_extraction)
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = []

        def update():
            with Session(c.engine) as db:
                # Source metadata is held SHARE while the actual File is UPDATE.
                row = db.get(FileManagerFileSourceMetadata, c.spec.file_id)
                row.source_version = "synthetic-v2"
                db.flush()
                db.commit()

        def read(file):
            # Capture the real Source Session PID directly from the locked row owner
            # via pg_locks; no timing assertion substitutes for lock wait.
            with c.world.connect() as core:
                pid = core.execute(
                    "SELECT pid FROM pg_locks WHERE locktype='relation' AND relation='file_manager_files'::regclass AND mode='RowShareLock' AND granted ORDER BY pid LIMIT 1"
                ).fetchone()[0]
            future = pool.submit(update)
            futures.append(future)
            wait_for_blocker(c.world, pid)
            assert not future.done()
            return b"Synthetic text"

        monkeypatch.setattr(commands, "_read_source", read)
        receipt = invoke(c, commands.bind_file_extraction_input)
        assert receipt.receipt.input_sha256 == sha256(b"Synthetic text").hexdigest()
        futures[0].result(timeout=8)
    with pytest.raises(FileExtractionRefused):
        invoke(
            c,
            commands.apply_file_extraction_result,
            computed_result=compute_local_file_extraction(receipt),
        )


def test_minimal_current_nonadmin_policy_projection(c):
    actor, _ = other_actor(c)
    with Session(c.engine) as db:
        try:
            allowed = can_use_app(db, user_id=actor, app_id="files")
        except SQLAlchemyError as error:
            sqlstate = getattr(error.orig, "sqlstate", None)
            primary = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            match = re.fullmatch(r"permission denied for table ([a-z_]+)", primary)
            table = match.group(1) if match else "unknown"
            if table not in {
                "app_user_grants",
                "app_group_grants",
                "users",
                "group_members",
                "groups",
            }:
                table = "unknown"
            raise AssertionError(f"current_policy_read_denied:{sqlstate}:{table}") from None
        assert allowed
