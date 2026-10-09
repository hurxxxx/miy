"""Inactive full actor edit admission against actual Core ACL and migrated PG.

The fresh LOGIN has no Core/business SELECT or DML and one private EXECUTE.
Its distinct NOLOGIN definer holds selected current positive witnesses in the
caller's transaction. These tests never enable a runtime factory or Yjs write;
decision-time expiry does not promise a physical-COMMIT expiry fence.

All database authority is disposable synthetic fixture authority. Missing new
APIs are readiness failures, never evidence of a behavioral RED.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
import json
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import User, UserSystemRole
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.pms.models import TaskList
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember
from miy_api.domains.whiteboard.access import resolve_whiteboard_access
from miy_api.domains.whiteboard.models import (
    Whiteboard,
    WhiteboardCollabDocument,
    WhiteboardGroupShare,
    WhiteboardLinkShare,
    WhiteboardTarget,
    WhiteboardUserShare,
)
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, DRAIN, PASSWORD, move
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_actor_writer import (
    CAPABILITY as OWNER_CAPABILITY,
    PRODUCER,
    SERVICE,
    _collab_snapshot,
    _commands,
    _migration_snapshot as _owner_snapshot,
    _oid,
    _replace_body,
    _wait_for_blocker,
    actor_boundary as actor_boundary,  # noqa: F401
)

CAPABILITY = "public.miy_whiteboard_lock_edit_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
REVISION = "wb_actor_acl_20261009"
PARENT_REVISION = "wb_actor_owner_20261009"
MUTATING_COMMANDS = {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}


def _api():
    try:
        roles = import_module("miy_api.domains.official_apps.whiteboard_actor_acl_writer_roles")
        runtime = import_module("miy_api.domains.official_apps.whiteboard_actor_acl_writer")
    except ModuleNotFoundError:
        pytest.fail("Actor ACL API readiness missing; no behavioral RED", pytrace=False)
    for module, names in (
        (
            roles,
            (
                "WhiteboardActorACLProfile",
                "WhiteboardActorACLPreparation",
                "whiteboard_actor_acl_contract",
                "install_whiteboard_actor_acl_guard",
                "prepare_whiteboard_actor_acl_principal",
            ),
        ),
        (
            runtime,
            (
                "WhiteboardActorACLWriterRefused",
                "CapturedWhiteboardWriteExecution",
                "capture_whiteboard_write_execution",
                "lock_whiteboard_actor_edit_write",
            ),
        ),
    ):
        if any(not hasattr(module, name) for name in names):
            pytest.fail("Actor ACL API readiness missing; no behavioral RED", pytrace=False)
    return SimpleNamespace(roles=roles, runtime=runtime)


@pytest.fixture
def acl_boundary(actor_boundary):
    base = actor_boundary
    owner, source = base.role(login=False), base.role()
    with base.connect() as conn:
        row = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=to_regprocedure(%s)",
            (CAPABILITY,),
        ).fetchone()
        if row is None:
            pytest.fail("Actor ACL migration readiness missing; no behavioral RED", pytrace=False)
        migration_owner_oid = row[0]
        owner_oid = _oid(conn, owner)
    c = SimpleNamespace(**vars(base))
    c.owner_api = base.api
    c.original_owner_login = base.source
    c.api = _api()
    c.capability_owner, c.capability_owner_oid = owner, owner_oid
    c.source, c.migration_owner_oid = source, migration_owner_oid
    return c


def _install(c, db):
    return c.api.roles.install_whiteboard_actor_acl_guard(
        db,
        c.actor,
        guard_owner=c.capability_owner,
        expected=DRAIN,
        expected_migration_owner_oid=c.migration_owner_oid,
        expected_service_capability_owner_oid=c.service_capability_owner_oid,
        expected_producer_owner_oid=c.producer_owner_oid,
        expected_source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _prepare(c, db, *, role_name=None):
    return c.api.roles.prepare_whiteboard_actor_acl_principal(
        db,
        c.actor,
        role_name=c.source if role_name is None else role_name,
        identity=ACTIVE,
        expected=c.expected,
        expected_state=c.expected_state,
        capability_owner_oid=c.capability_owner_oid,
        service_capability_owner_oid=c.service_capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
    )


@pytest.fixture
def acl_prepared(acl_boundary):
    c = acl_boundary
    with Session(c.engine) as db:
        assert _install(c, db) is None
        result = _prepare(c, db)
        assert type(result) is c.api.roles.WhiteboardActorACLPreparation
        assert result.profile_prepared is True
        c.writer = result.writer
        db.commit()
    assert move(c.control, DRAIN, "draining", state="active", artifact=ACTIVE.artifact) == ACTIVE
    c.expected, c.expected_state = ACTIVE, "active"
    # Privileged synthetic Core is explicitly registered solely to make actual
    # Source triggers govern fixture metadata mutations. Actor LOGIN stays DML0.
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO official_writer_principals "
            "(role_oid,role_name,scope,owner,generation,artifact,approved_by_user_id,approved_by_session_id,created_at) "
            "SELECT oid::bigint,rolname,%s,%s,%s,%s,%s,%s,timezone('UTC',clock_timestamp()) FROM pg_roles WHERE rolname=session_user",
            (
                ACTIVE.scope,
                ACTIVE.owner,
                ACTIVE.generation,
                ACTIVE.artifact,
                c.actor.user.id,
                c.actor.session.id,
            ),
        )
    c.source_engine = create_engine(
        c.engine.url.set(username=c.source, password=PASSWORD), pool_size=1, max_overflow=0
    )
    c.execution = c.api.runtime.capture_whiteboard_write_execution(
        c.world.factory,
        token=c.world.token,
        original_user_id=c.world.state["member_id"],
        original_source_session_id=c.world.state["source_id"],
    )
    try:
        yield c
    finally:
        c.source_engine.dispose()


def _lock(c, db, *, writer=None, execution=None, board=None):
    return c.api.runtime.lock_whiteboard_actor_edit_write(
        db,
        writer=c.writer if writer is None else writer,
        execution=c.execution if execution is None else execution,
        whiteboard_id=c.board_id if board is None else board,
    )


def _refused(c, db, **kwargs):
    with pytest.raises(c.api.runtime.WhiteboardActorACLWriterRefused) as caught:
        _lock(c, db, **kwargs)
    assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
    assert c.execution.delegated_token_digest not in repr(caught.value)
    db.rollback()


def _resource_group(db, c, *, hr=False, member=True):
    group_id = str(uuid4())
    db.add(
        Group(
            id=group_id,
            source="hr" if hr else "local",
            name="Synthetic resource witness",
            slug="acl-" + uuid4().hex if hr else None,
            unit_type="department" if hr else None,
        )
    )
    db.flush()
    if member:
        if hr:
            db.get(User, c.execution.actor_user_id).primary_organization_unit_id = group_id
        else:
            db.add(GroupMember(group_id=group_id, user_id=c.execution.actor_user_id))
    return group_id


def _seed(c, kind, *, role="member"):
    """Only actual Core models/predicates; every case starts with a sole witness.

    Resource groups differ from the installation audience group, so a held
    resource group/membership cannot be mistaken for an auth admission lock.
    """
    p = {"board": c.board_id, "user": c.execution.actor_user_id, "other": c.actor.user.id}
    with Session(c.engine) as db:
        board = db.get(Whiteboard, c.board_id)
        if kind != "owner":
            board.owner_id = c.actor.user.id
        if kind.startswith("direct_"):
            db.add(
                WhiteboardUserShare(
                    id=str(uuid4()),
                    whiteboard_id=c.board_id,
                    user_id=p["user"],
                    access_level=kind.removeprefix("direct_"),
                    created_by_id=p["other"],
                )
            )
        elif kind.startswith(("local_", "hr_")):
            p["group"] = _resource_group(db, c, hr=kind.startswith("hr_"))
            db.add(
                WhiteboardGroupShare(
                    whiteboard_id=c.board_id,
                    group_id=p["group"],
                    access_level=kind.split("_", 1)[1],
                    created_by_id=p["other"],
                )
            )
        elif kind.startswith("pms_"):
            seed_company_app_access(db, app_ids=["pms"])
            p["space"] = str(uuid4())
            db.add(Team(id=p["space"], key="acl-" + uuid4().hex, name="Synthetic ACL space"))
            db.flush()
            if "group" in kind:
                p["group"] = _resource_group(db, c, hr="hrgroup" in kind)
                db.add(SpaceGroupBinding(team_id=p["space"], group_id=p["group"], role=role))
            elif kind != "pms_admin_only":
                db.add(
                    TeamMember(id=str(uuid4()), team_id=p["space"], user_id=p["user"], role=role)
                )
            else:
                db.add(UserSystemRole(id=str(uuid4()), user_id=p["user"], role="platform_admin"))
            target_type, target_id = "space", p["space"]
            if "list" in kind:
                p["list"] = str(uuid4())
                db.add(
                    TaskList(
                        id=p["list"],
                        key="acl-" + uuid4().hex[:16],
                        name="Synthetic ACL list",
                        team_id=p["space"],
                        created_by_id=p["other"],
                    )
                )
                target_type, target_id = "task_list", p["list"]
            db.add(
                WhiteboardTarget(
                    id=str(uuid4()),
                    whiteboard_id=c.board_id,
                    target_app="pms",
                    target_type=target_type,
                    target_id=target_id,
                    created_by_id=p["other"],
                )
            )
        elif kind.startswith("meeting_"):
            seed_company_app_access(db, app_ids=["meeting"])
            p["meeting"] = str(uuid4())
            now = datetime.now(UTC).replace(tzinfo=None)
            db.add(
                Meeting(
                    id=p["meeting"],
                    organizer_id=p["user"] if kind == "meeting_organizer" else p["other"],
                    title="Synthetic ACL meeting",
                    start_at=now,
                    end_at=now + timedelta(hours=1),
                    status="cancelled" if kind == "meeting_declined" else "scheduled",
                )
            )
            db.flush()
            if kind in {"meeting_attendee", "meeting_declined"}:
                db.add(
                    MeetingAttendee(
                        id=str(uuid4()),
                        meeting_id=p["meeting"],
                        user_id=p["user"],
                        response="declined" if kind == "meeting_declined" else "pending",
                    )
                )
            if kind == "meeting_admin_only":
                db.add(UserSystemRole(id=str(uuid4()), user_id=p["user"], role="platform_admin"))
            db.add(
                WhiteboardTarget(
                    id=str(uuid4()),
                    whiteboard_id=c.board_id,
                    target_app="meeting",
                    target_type="meeting",
                    target_id=p["meeting"],
                    created_by_id=p["other"],
                )
            )
        elif kind == "company_visible":
            board.company_visible = True
        elif kind == "company_admin":
            board.ownership_kind = "company"
            db.add(UserSystemRole(id=str(uuid4()), user_id=p["user"], role="platform_admin"))
        elif kind == "link_edit":
            db.add(
                WhiteboardLinkShare(
                    id=str(uuid4()),
                    whiteboard_id=c.board_id,
                    token=uuid4().hex,
                    access_level="edit",
                    created_by_id=p["other"],
                )
            )
        elif kind == "unknown_target":
            db.add(
                WhiteboardTarget(
                    id=str(uuid4()),
                    whiteboard_id=c.board_id,
                    target_app="whiteboard",
                    target_type="unknown",
                    target_id="unknown-synthetic-resource",
                    created_by_id=p["other"],
                )
            )
        elif kind not in {"owner", "none"}:
            raise AssertionError("Unknown owned synthetic witness")
        db.commit()
    return p


def _core_edit(c):
    with Session(c.engine) as db:
        user = db.get(User, c.execution.actor_user_id)
        board = db.get(Whiteboard, c.board_id)
        return resolve_whiteboard_access(db, board, user, share_token=None).can_edit


PARITY_CASES = [
    ("owner", "member", True),
    ("direct_edit", "member", True),
    ("local_edit", "member", True),
    ("hr_edit", "member", True),
    ("pms_space", "member", True),
    ("pms_space", "admin", True),
    ("pms_space", "owner", True),
    ("pms_group", "member", True),
    ("pms_group", "admin", True),
    ("pms_hrgroup", "member", True),
    ("pms_list", "member", True),
    ("pms_list", "admin", True),
    ("pms_list", "owner", True),
    ("pms_list_group", "member", True),
    ("pms_list_hrgroup", "admin", True),
    ("meeting_organizer", "member", True),
    ("meeting_attendee", "member", True),
    # Existing is_participant checks any attendee, regardless of response or
    # meeting status. Do not silently substitute a stricter invented predicate.
    ("meeting_declined", "member", True),
    ("none", "member", False),
    ("direct_read", "member", False),
    ("local_read", "member", False),
    ("hr_read", "member", False),
    ("pms_space", "viewer", False),
    ("pms_group", "viewer", False),
    ("pms_list", "viewer", False),
    ("pms_admin_only", "member", False),
    ("meeting_none", "member", False),
    ("meeting_admin_only", "member", False),
    ("company_visible", "member", False),
    ("company_admin", "member", False),
    ("link_edit", "member", False),
    ("unknown_target", "member", False),
]


@pytest.mark.parametrize("kind,role,allowed", PARITY_CASES)
def test_genuine_edit_decision_matches_actual_core_acl_without_source_dml(
    acl_prepared, kind, role, allowed
):
    c = acl_prepared
    _seed(c, kind, role=role)
    assert _core_edit(c) is allowed
    before = _collab_snapshot(c)
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        if allowed:
            assert _lock(c, db) is None
            assert db.in_transaction()
            db.rollback()
        else:
            _refused(c, db)
    assert set(commands) <= {"SELECT", "SET", "SHOW"}
    assert _collab_snapshot(c) == before


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("\u00a0MeMbEr\u2003", True),
        ("\tADMIN\n", True),
        ("\u001cOwNeR\u001f", True),
        ("\u3000member\u205f", True),
        ("\u0085member\u2028", True),
        ("team_admin", False),
        ("mem ber", False),
        ("member\u200b", False),
        ("member\u180e", False),
    ],
)
def test_genuine_pms_role_normalization_matches_python_unicode_strip_lower(
    acl_prepared, role, allowed
):
    c = acl_prepared
    _seed(c, "pms_space", role=role)
    assert _core_edit(c) is allowed
    with Session(c.source_engine) as db:
        if allowed:
            assert _lock(c, db) is None
            db.rollback()
        else:
            _refused(c, db)


def test_genuine_higher_group_role_can_supply_edit_when_direct_role_is_only_viewer(acl_prepared):
    c = acl_prepared
    p = _seed(c, "pms_space", role="viewer")
    with Session(c.engine) as db:
        group_id = _resource_group(db, c)
        db.add(SpaceGroupBinding(team_id=p["space"], group_id=group_id, role="admin"))
        db.commit()
    assert _core_edit(c) is True
    with Session(c.source_engine) as db:
        assert _lock(c, db) is None
        db.rollback()


@pytest.mark.parametrize(
    "kind,mutation",
    [
        ("owner", "UPDATE company_app_controls SET enabled=false WHERE app_id='whiteboard'"),
        ("pms_space", "UPDATE company_app_controls SET enabled=false WHERE app_id='pms'"),
        (
            "meeting_attendee",
            "UPDATE company_app_controls SET enabled=false WHERE app_id='meeting'",
        ),
        ("pms_space", "UPDATE pms_spaces SET active=false WHERE id=%(space)s"),
        (
            "pms_space",
            "UPDATE pms_spaces SET trashed_at=timezone('UTC',clock_timestamp()) WHERE id=%(space)s",
        ),
        ("pms_list", "UPDATE pms_task_lists SET archived=true WHERE id=%(list)s"),
        ("local_edit", "UPDATE groups SET active=false WHERE id=%(group)s"),
        ("hr_edit", "UPDATE groups SET active=false WHERE id=%(group)s"),
    ],
)
def test_genuine_current_app_and_resource_admission_denies_old_execution(
    acl_prepared, kind, mutation
):
    c = acl_prepared
    p = _seed(c, kind)
    assert _core_edit(c) is True
    with c.connect() as conn:
        conn.execute(mutation, p)
    assert _core_edit(c) is False
    with Session(c.source_engine) as db:
        _refused(c, db)


@pytest.mark.parametrize("kind", ["owner", "direct_edit", "pms_space", "meeting_organizer"])
def test_genuine_trashed_board_is_never_a_persistable_edit_even_for_core_manager(
    acl_prepared, kind
):
    c = acl_prepared
    _seed(c, kind)
    assert _core_edit(c) is True
    with c.connect() as conn:
        conn.execute(
            "UPDATE whiteboards SET trashed_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
            (c.board_id,),
        )
    # The ordinary resolver itself still returns can_edit; the persistence
    # contract deliberately refuses every trashed board, including managers.
    assert _core_edit(c) is True
    with Session(c.source_engine) as db:
        _refused(c, db)


# Sole selected resource witnesses: holding these must block real Core revoke.
WITNESS_MUTATIONS = {
    "direct": (
        "direct_edit",
        "whiteboard_user_shares",
        "whiteboard_id=%(board)s AND user_id=%(user)s",
        "DELETE FROM whiteboard_user_shares WHERE whiteboard_id=%(board)s AND user_id=%(user)s",
    ),
    "group_share": (
        "local_edit",
        "whiteboard_group_shares",
        "whiteboard_id=%(board)s AND group_id=%(group)s",
        "DELETE FROM whiteboard_group_shares WHERE whiteboard_id=%(board)s AND group_id=%(group)s",
    ),
    "local_member": (
        "local_edit",
        "group_members",
        "group_id=%(group)s AND user_id=%(user)s",
        "DELETE FROM group_members WHERE group_id=%(group)s AND user_id=%(user)s",
    ),
    "group_active": (
        "local_edit",
        "groups",
        "id=%(group)s",
        "UPDATE groups SET active=false WHERE id=%(group)s",
    ),
    "hr_assignment": (
        "hr_edit",
        "users",
        "id=%(user)s",
        "UPDATE users SET primary_organization_unit_id=NULL WHERE id=%(user)s",
    ),
    "space_member": (
        "pms_space",
        "pms_space_members",
        "team_id=%(space)s AND user_id=%(user)s",
        "UPDATE pms_space_members SET role='viewer' WHERE team_id=%(space)s AND user_id=%(user)s",
    ),
    "space_group": (
        "pms_group",
        "pms_space_group_bindings",
        "team_id=%(space)s AND group_id=%(group)s",
        "UPDATE pms_space_group_bindings SET role='viewer' WHERE team_id=%(space)s AND group_id=%(group)s",
    ),
    "space_active": (
        "pms_space",
        "pms_spaces",
        "id=%(space)s",
        "UPDATE pms_spaces SET active=false WHERE id=%(space)s",
    ),
    "list_archived": (
        "pms_list",
        "pms_task_lists",
        "id=%(list)s",
        "UPDATE pms_task_lists SET archived=true WHERE id=%(list)s",
    ),
    "target": (
        "pms_list",
        "whiteboard_targets",
        "whiteboard_id=%(board)s",
        "DELETE FROM whiteboard_targets WHERE whiteboard_id=%(board)s",
    ),
    "meeting_organizer": (
        "meeting_organizer",
        "meetings",
        "id=%(meeting)s",
        "UPDATE meetings SET organizer_id=%(other)s WHERE id=%(meeting)s",
    ),
    "meeting_attendee": (
        "meeting_attendee",
        "meeting_attendees",
        "meeting_id=%(meeting)s AND user_id=%(user)s",
        "DELETE FROM meeting_attendees WHERE meeting_id=%(meeting)s AND user_id=%(user)s",
    ),
}


@pytest.mark.parametrize("witness", list(WITNESS_MUTATIONS))
@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_genuine_selected_edit_witness_survives_until_actual_caller_end(
    acl_prepared, witness, finish
):
    c = acl_prepared
    kind, _, _, mutation = WITNESS_MUTATIONS[witness]
    p = _seed(c, kind)
    before = _collab_snapshot(c)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        caller_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _lock(c, db) is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(revoker.execute, mutation, p)
            try:
                _wait_for_blocker(observer, revoker_pid, caller_pid)
                assert not future.done()
                getattr(db, finish)()
                future.result(timeout=5)
                revoker.commit()
            finally:
                db.rollback()
                revoker.rollback()
        _refused(c, db)
    assert _core_edit(c) is False
    assert _collab_snapshot(c) == before


@pytest.mark.parametrize("witness", ["direct", "space_member", "meeting_attendee"])
def test_genuine_waited_resource_rechecks_revocation_before_edit_decision(acl_prepared, witness):
    c = acl_prepared
    kind, table, predicate, mutation = WITNESS_MUTATIONS[witness]
    p = _seed(c, kind)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        caller_pid = db.scalar(text("SELECT pg_backend_pid()"))
        # Pool size one preserves this captured backend after releasing its
        # preliminary read transaction, before the genuine capability wait.
        db.rollback()
        holder_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        revoker.execute(f"SELECT 1 FROM {table} WHERE {predicate} FOR UPDATE", p)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, caller_pid, holder_pid)
                assert not future.done()
                revoker.execute(mutation, p)
                revoker.commit()
                with pytest.raises(c.api.runtime.WhiteboardActorACLWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()


@pytest.mark.parametrize(
    "selected", ["direct_share", "pms_direct_role", "meeting_organizer", "target_app_user_grant"]
)
def test_genuine_selected_positive_witness_cannot_switch_to_an_alternate_after_wait(
    acl_prepared, selected
):
    c = acl_prepared
    kind = {
        "direct_share": "direct_edit",
        "pms_direct_role": "pms_space",
        "meeting_organizer": "meeting_organizer",
        "target_app_user_grant": "pms_space",
    }[selected]
    p = _seed(c, kind)
    with Session(c.engine) as core:
        if selected == "direct_share":
            group_id = _resource_group(core, c)
            core.add(
                WhiteboardGroupShare(
                    whiteboard_id=p["board"],
                    group_id=group_id,
                    access_level="edit",
                    created_by_id=p["other"],
                )
            )
            table, predicate, mutation = WITNESS_MUTATIONS["direct"][1:]
        elif selected == "pms_direct_role":
            group_id = _resource_group(core, c)
            core.add(SpaceGroupBinding(team_id=p["space"], group_id=group_id, role="admin"))
            table, predicate, mutation = WITNESS_MUTATIONS["space_member"][1:]
        elif selected == "meeting_organizer":
            core.add(MeetingAttendee(id=str(uuid4()), meeting_id=p["meeting"], user_id=p["user"]))
            table, predicate, mutation = WITNESS_MUTATIONS["meeting_organizer"][1:]
        else:
            group_id = _resource_group(core, c)
            core.get(AppAccessPolicy, "pms").audience = "selected"
            core.add(AppUserGrant(app_id="pms", user_id=p["user"]))
            core.add(AppGroupGrant(app_id="pms", group_id=group_id))
            table = "app_user_grants"
            predicate = "app_id='pms' AND user_id=%(user)s"
            mutation = "DELETE FROM app_user_grants WHERE app_id='pms' AND user_id=%(user)s"
        core.commit()
    assert _core_edit(c) is True
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        caller_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        revoker.execute(f"SELECT 1 FROM {table} WHERE {predicate} FOR UPDATE", p)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, caller_pid, holder_pid)
                assert not future.done()
                revoker.execute(mutation, p)
                revoker.commit()
                with pytest.raises(c.api.runtime.WhiteboardActorACLWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()
        # A new operation may deliberately choose the remaining live witness;
        # the old waited operation must fail rather than silently switch facts.
        assert _core_edit(c) is True
        assert _lock(c, db) is None
        db.rollback()


def test_genuine_expired_delegation_after_actual_resource_wait_never_grants_edit(acl_prepared):
    c = acl_prepared
    _seed(c, "direct_edit")
    with c.connect() as conn:
        conn.execute(
            "UPDATE independent_app_sessions SET expires_at=timezone('UTC',clock_timestamp())+interval '1 second' WHERE token_hash=%s",
            (c.execution.delegated_token_digest,),
        )
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as holder,
        Session(c.source_engine) as db,
    ):
        caller_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        holder.rollback()
        holder.execute(
            "SELECT 1 FROM whiteboard_user_shares WHERE whiteboard_id=%s AND user_id=%s FOR UPDATE",
            (c.board_id, c.execution.actor_user_id),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, caller_pid, holder_pid)
                deadline = time.monotonic() + 3
                while observer.execute(
                    "SELECT expires_at>timezone('UTC',clock_timestamp()) FROM independent_app_sessions WHERE token_hash=%s",
                    (c.execution.delegated_token_digest,),
                ).fetchone()[0]:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert not future.done()
                holder.rollback()
                with pytest.raises(c.api.runtime.WhiteboardActorACLWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
            finally:
                holder.rollback()
                db.rollback()


@pytest.mark.parametrize("nullable", ["installation_release", "release_verification"])
def test_genuine_null_current_release_or_proof_never_adopts_old_captured_identity(
    acl_prepared, nullable
):
    c = acl_prepared
    _seed(c, "direct_edit")
    with c.connect() as conn:
        if nullable == "installation_release":
            conn.execute(
                "UPDATE independent_app_installations SET release_id=NULL WHERE id=%s",
                (c.execution.installation_id,),
            )
        else:
            conn.execute(
                "UPDATE independent_app_releases SET verification_id=NULL WHERE id=%s",
                (c.execution.release_id,),
            )
    with Session(c.source_engine) as db:
        _refused(c, db)


def test_genuine_distinct_acl_profile_has_exact_24_100_24_and_login_exec1_dml0(acl_prepared):
    c = acl_prepared
    assert c.api.roles.PROFILE == "whiteboard_actor_edit_v1"
    assert c.api.roles.CAPABILITY == CAPABILITY
    assert type(c.writer) is c.api.roles.WhiteboardActorACLProfile
    assert c.writer.role_name == c.source and c.writer.identity == ACTIVE
    assert c.writer.role_oid not in {
        c.capability_owner_oid,
        c.service_capability_owner_oid,
        c.producer_owner_oid,
        c.source_guard_owner_oid,
    }
    read = c.api.roles.OWNER_READ_COLUMNS
    locks = c.api.roles.OWNER_LOCK_COLUMNS
    assert len(read) == len(locks) == 24
    assert sum(map(len, read.values())) == 100
    assert sum(map(len, locks.values())) == 24
    # Assert the new resource manifest independently from the production map.
    assert {
        table: read[table]
        for table in (
            "whiteboard_user_shares",
            "whiteboard_group_shares",
            "whiteboard_targets",
            "pms_spaces",
            "pms_space_members",
            "pms_space_group_bindings",
            "pms_task_lists",
            "meetings",
            "meeting_attendees",
        )
    } == {
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
    assert c.owner_api.roles.PROFILE == "whiteboard_actor_owner_v1"
    assert len(c.owner_api.roles.OWNER_READ_COLUMNS) == 15
    assert sum(map(len, c.owner_api.roles.OWNER_READ_COLUMNS.values())) == 74
    with c.connect() as conn:
        assert conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE oid=%s", (c.capability_owner_oid,)
        ).fetchone() == (False,)
        granted = conn.execute(
            "SELECT c.relname,a.attname,has_column_privilege(%s,c.oid,a.attnum,'SELECT'),"
            "has_column_privilege(%s,c.oid,a.attnum,'UPDATE'),"
            "has_column_privilege(%s,c.oid,a.attnum,'SELECT,INSERT,UPDATE,REFERENCES') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p')",
            (c.capability_owner, c.capability_owner, c.source),
        ).fetchall()
        assert {(t, col) for t, col, r, _, _ in granted if r} == {
            (t, col) for t, cols in read.items() for col in cols
        }
        assert {(t, col) for t, col, _, u, _ in granted if u} == {
            (t, col) for t, cols in locks.items() for col in cols
        }
        assert not any(row[4] for row in granted)
        assert conn.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p') AND "
            "has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')",
            (c.source,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE'),"
            "has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE')",
            (
                c.source,
                CAPABILITY,
                c.source,
                OWNER_CAPABILITY,
                c.source,
                SERVICE,
                c.source,
                PRODUCER,
                c.original_owner_login,
                CAPABILITY,
            ),
        ).fetchone() == (True, False, False, False, False)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT id FROM pms_spaces",
        "SELECT organizer_id FROM meetings",
        "SELECT role_oid FROM official_writer_principals",
        "UPDATE whiteboard_collab_documents SET yjs_state=yjs_state WHERE false",
        "UPDATE pms_space_members SET role=role WHERE false",
    ],
)
def test_genuine_acl_login_cannot_select_or_mutate_business_and_core(acl_prepared, statement):
    c = acl_prepared
    with Session(c.source_engine) as db:
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501"
        db.rollback()


def test_genuine_exact_acl_prepare_replay_observes_and_never_repairs_partial_authority(
    acl_prepared,
):
    c = acl_prepared
    with c.connect() as conn:
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        assert _prepare(c, db).writer == c.writer
        db.commit()
    assert not set(commands) & MUTATING_COMMANDS
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits
        conn.execute(
            sql.SQL("REVOKE EXECUTE ON FUNCTION {} FROM {}").format(
                sql.SQL(CAPABILITY), sql.Identifier(c.source)
            )
        )
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()
    assert not set(commands) & MUTATING_COMMANDS
    with Session(c.source_engine) as db:
        _refused(c, db)


def test_genuine_exact_acl_install_replay_under_drain_is_observation_only(acl_boundary):
    c = acl_boundary
    with Session(c.engine) as db:
        assert _install(c, db) is None
        db.commit()
    with c.connect() as conn:
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        assert _install(c, db) is None
        db.commit()
    assert not set(commands) & MUTATING_COMMANDS
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits


@pytest.mark.parametrize("preexisting", ["read", "execute", "nologin"])
def test_genuine_acl_fresh_preparation_refuses_preexisting_authority_without_repair(
    acl_boundary, preexisting
):
    c = acl_boundary
    with Session(c.engine) as db:
        assert _install(c, db) is None
        db.commit()
    fresh = c.role(login=preexisting != "nologin")
    with c.connect() as conn:
        if preexisting == "read":
            conn.execute(
                sql.SQL("GRANT SELECT (id) ON pms_spaces TO {}").format(sql.Identifier(fresh))
            )
        elif preexisting == "execute":
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                    sql.SQL(CAPABILITY), sql.Identifier(fresh)
                )
            )
        before = conn.execute(
            "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (fresh,)
        ).fetchone()[0]
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db, role_name=fresh)
        db.rollback()
    assert not set(commands) & MUTATING_COMMANDS
    with c.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (fresh,)
            ).fetchone()[0]
            == before
            == 0
        )
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits


@pytest.mark.parametrize(
    "tamper",
    [
        "login_read",
        "login_update",
        "membership",
        "public_definer",
        "namespace_column",
        "owner_extra_lock",
        "body",
        "overload",
    ],
)
def test_genuine_acl_profile_or_capability_tamper_is_refused_without_repair(acl_prepared, tamper):
    c = acl_prepared
    with c.connect() as conn:
        login, owner = sql.Identifier(c.source), sql.Identifier(c.capability_owner)
        if tamper == "login_read":
            conn.execute(sql.SQL("GRANT SELECT (organizer_id) ON meetings TO {}").format(login))
        elif tamper == "login_update":
            conn.execute(sql.SQL("GRANT UPDATE (role) ON pms_space_members TO {}").format(login))
        elif tamper == "membership":
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(c.role(login=False)), login)
            )
        elif tamper == "public_definer":
            conn.execute("CREATE SCHEMA pgx_acl")
            conn.execute(
                "CREATE FUNCTION pgx_acl.private_cap() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
            )
        elif tamper == "namespace_column":
            conn.execute("CREATE SCHEMA pgx_acl")
            conn.execute("CREATE TABLE pgx_acl.private_metadata(marker integer)")
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA pgx_acl TO {}").format(login))
            conn.execute(
                sql.SQL("GRANT SELECT (marker) ON pgx_acl.private_metadata TO {}").format(login)
            )
        elif tamper == "owner_extra_lock":
            conn.execute(sql.SQL("GRANT UPDATE (role) ON pms_space_members TO {}").format(owner))
        elif tamper == "body":
            _replace_body(conn, CAPABILITY)
        else:
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_edit_actor(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_edit_actor(text) FROM PUBLIC"
            )
    before = _collab_snapshot(c)
    with Session(c.source_engine) as db:
        _refused(c, db)
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()
    assert not set(commands) & MUTATING_COMMANDS
    assert _collab_snapshot(c) == before


@pytest.mark.parametrize("change", ["generation", "role_oid", "session_user"])
def test_genuine_original_acl_service_identity_cannot_be_replaced_by_spoofed_guc(
    acl_prepared, change
):
    c = acl_prepared
    writer = c.writer
    if change == "generation":
        writer = replace(
            writer, identity=WriterIdentity(ACTIVE.scope, ACTIVE.owner, 2, ACTIVE.artifact)
        )
    elif change == "role_oid":
        writer = replace(writer, role_oid=c.writer.role_oid + 100000)
    if change == "session_user":
        other = c.role()
        with c.connect() as conn:
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(other))
            )
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                    sql.SQL(CAPABILITY), sql.Identifier(other)
                )
            )
        engine = create_engine(c.engine.url.set(username=other, password=PASSWORD))
    else:
        engine = c.source_engine
    try:
        with Session(engine) as db:
            db.execute(
                text("SELECT set_config('miy.official_writer',:spoof,true)"),
                {
                    "spoof": json.dumps(
                        {
                            "scope": ACTIVE.scope,
                            "owner": ACTIVE.owner,
                            "generation": 3,
                            "artifact": ACTIVE.artifact,
                        }
                    )
                },
            )
            _refused(c, db, writer=writer)
    finally:
        if engine is not c.source_engine:
            engine.dispose()


def test_genuine_known_different_database_locator_refuses_before_capability_use(acl_prepared):
    c = acl_prepared
    with Session(c.source_engine) as db:
        _refused(
            c, db, execution=replace(c.execution, database_oid=c.execution.database_oid + 100000)
        )
        assert _lock(c, db) is None
        db.rollback()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_edit_requires_actual_read_committed_non_autocommit_caller(acl_prepared, isolation):
    c = acl_prepared
    engine = create_engine(c.source_engine.url, isolation_level=isolation)
    try:
        with Session(engine) as db:
            _refused(c, db)
    finally:
        engine.dispose()


def test_genuine_missing_board_has_private_refusal_without_source_changes(acl_prepared):
    c = acl_prepared
    before = _collab_snapshot(c)
    with Session(c.source_engine) as db:
        _refused(c, db, board=str(uuid4()))
    assert _collab_snapshot(c) == before


def _pure_execution(api):
    return api.runtime.CapturedWhiteboardWriteExecution(
        "a" * 64,
        "user",
        "session",
        "install",
        1,
        "binding",
        "release",
        "proof",
        "sha256:" + "a" * 64,
        "https://standalone.example.test",
        "dev",
        "synthetic_db",
        123,
        None,
        None,
    )


@pytest.mark.parametrize(
    "model",
    [
        WhiteboardUserShare,
        WhiteboardGroupShare,
        WhiteboardTarget,
        Team,
        TeamMember,
        SpaceGroupBinding,
        TaskList,
        Meeting,
        MeetingAttendee,
    ],
)
def test_pure_new_resource_model_cannot_route_to_another_engine_before_any_sql(monkeypatch, model):
    api = _api()
    monkeypatch.setattr(
        api.runtime,
        "get_settings",
        lambda: SimpleNamespace(independent_app_platform_origins=["https://portal.example.test"]),
    )
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    writer = api.roles.WhiteboardActorACLProfile(1, "synthetic_actor", ACTIVE, 2, 3, 4, 5)
    calls = []

    def observe(*_):
        calls.append(1)

    for engine in (first, second):
        event.listen(engine, "before_cursor_execute", observe)
    try:
        with Session(bind=first, binds={model: second}) as db:
            with pytest.raises(api.runtime.WhiteboardActorACLWriterRefused) as caught:
                api.runtime.lock_whiteboard_actor_edit_write(
                    db, writer=writer, execution=_pure_execution(api), whiteboard_id="board"
                )
            assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
            assert caught.value.reason == "single_caller_engine_required"
            assert not db.in_transaction() and calls == []
    finally:
        for engine in (first, second):
            event.remove(engine, "before_cursor_execute", observe)
            engine.dispose()


@pytest.mark.parametrize("caller", ["routed", "connection", "pending"])
def test_pure_nonstandard_or_dirty_caller_is_never_adopted_before_sql(monkeypatch, caller):
    api = _api()
    monkeypatch.setattr(
        api.runtime,
        "get_settings",
        lambda: SimpleNamespace(independent_app_platform_origins=["https://portal.example.test"]),
    )
    engine = create_engine("sqlite://")
    writer = api.roles.WhiteboardActorACLProfile(1, "synthetic_actor", ACTIVE, 2, 3, 4, 5)
    execution = _pure_execution(api)
    calls = []

    def observe(*_):
        calls.append(1)

    class Routed(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            calls.append("route")
            return engine

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with engine.connect() as connection:
            db = (
                Routed(bind=engine)
                if caller == "routed"
                else Session(bind=connection if caller == "connection" else engine)
            )
            with db:
                marker = None
                if caller == "pending":
                    marker = User(
                        id="unrelated",
                        login_id="unrelated",
                        email="unused@example.test",
                        full_name="Synthetic",
                        password_hash="synthetic",
                    )
                    db.add(marker)
                with pytest.raises(api.runtime.WhiteboardActorACLWriterRefused) as caught:
                    api.runtime.lock_whiteboard_actor_edit_write(
                        db, writer=writer, execution=execution, whiteboard_id="board"
                    )
                assert str(caught.value) == "whiteboard_actor_acl_writer_refused"
                assert calls == []
                if marker is not None:
                    assert marker in db.new and db.in_transaction()
    finally:
        event.remove(engine, "before_cursor_execute", observe)
        engine.dispose()


def test_pure_acl_uses_original_frozen_private_capture_and_distinct_descriptor():
    api = _api()
    original = import_module("miy_api.domains.official_apps.whiteboard_actor_writer")
    original_roles = import_module("miy_api.domains.official_apps.whiteboard_actor_writer_roles")
    assert api.runtime.CapturedWhiteboardWriteExecution is original.CapturedWhiteboardWriteExecution
    assert (
        api.runtime.capture_whiteboard_write_execution
        is original.capture_whiteboard_write_execution
    )
    assert api.roles.WhiteboardActorACLProfile is not original_roles.WhiteboardActorOwnerProfile
    execution = _pure_execution(api)
    assert execution.delegated_token_digest not in repr(execution)
    with pytest.raises(FrozenInstanceError):
        execution.actor_user_id = "other"
    with pytest.raises(original.WhiteboardActorWriterRefused) as caught:
        replace(execution, database_oid=True)
    assert str(caught.value) == "whiteboard_actor_writer_refused"


def _snapshot(c):
    original = _owner_snapshot(c)
    with c.connect() as conn:
        acl = conn.execute(
            "SELECT pg_get_function_identity_arguments(p.oid),p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_edit_actor' ORDER BY 1"
        ).fetchall()
    return {**original, "acl": acl}


def test_genuine_acl_legacy_roundtrip_preserves_owner_source_guards_roles_and_data(http_world):
    import y_py as Y

    with http_world.core() as db:
        engine = db.get_bind()
        doc = Y.YDoc()
        with doc.begin_transaction() as txn:
            doc.get_map("scene").set(txn, "marker", "legacy-acl-migration")
        db.add(
            WhiteboardCollabDocument(
                id=str(uuid4()),
                whiteboard_id=http_world.ids["board"],
                room_key="legacy-acl:" + http_world.ids["board"],
                yjs_state=bytes(Y.encode_state_as_update(doc)),
            )
        )
        db.commit()
    url = engine.url
    dsn = make_conninfo(
        host=url.host, port=url.port, dbname=url.database, user=url.username, password=url.password
    )
    c = SimpleNamespace(
        engine=engine, connect=lambda **kwargs: psycopg.connect(dsn, **kwargs), roles=[]
    )
    before = _snapshot(c)
    assert before["version"] == REVISION and len(before["acl"]) == 1
    config = _migration_config(c.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, PARENT_REVISION)
    removed = _snapshot(c)
    assert removed["version"] == PARENT_REVISION and removed["acl"] == []
    assert removed["actor"] == before["actor"] and removed["existing"] == before["existing"]
    # Upgrade explicitly only this owned revision; never assume it is a future head.
    command.upgrade(config, REVISION)
    assert _snapshot(c) == before


def test_genuine_acl_active_rollback_refuses_without_changes_and_admission_still_works(
    acl_prepared,
):
    c = acl_prepared
    before = _snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_acl_requires_draining"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)), PARENT_REVISION
        )
    assert _snapshot(c) == before
    with Session(c.source_engine) as db:
        assert _lock(c, db) is None
        db.rollback()


def test_genuine_acl_drained_rollback_removes_only_new_inactive_capability(acl_prepared):
    c = acl_prepared
    drained = move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation == 4
    before = _snapshot(c)
    command.downgrade(
        _migration_config(c.engine.url.render_as_string(hide_password=False)), PARENT_REVISION
    )
    removed = _snapshot(c)
    assert removed["version"] == PARENT_REVISION and removed["acl"] == []
    assert removed["actor"] == before["actor"] and removed["existing"] == before["existing"]
    with Session(c.source_engine) as db:
        _refused(c, db)
    assert _snapshot(c) == removed


@pytest.mark.parametrize("tamper", ["body", "overload"])
def test_genuine_acl_rollback_refuses_tampered_shape_without_partial_downgrade(
    acl_boundary, tamper
):
    c = acl_boundary
    with c.connect() as conn:
        if tamper == "body":
            _replace_body(conn, CAPABILITY)
        else:
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_edit_actor(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_edit_actor(text) FROM PUBLIC"
            )
    before = _snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_acl_capability_contract_invalid"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)), PARENT_REVISION
        )
    assert _snapshot(c) == before
