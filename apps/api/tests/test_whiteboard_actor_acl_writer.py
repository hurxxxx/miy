"""Inactive full actor edit admission against actual Core ACL and migrated PG.

The fresh LOGIN has no Core/business SELECT or DML and one private EXECUTE.
Its distinct NOLOGIN definer holds selected current positive witnesses in the
caller's transaction. These tests never enable a runtime factory or Yjs write;
decision-time expiry does not promise a physical-COMMIT expiry fence.

All database authority is disposable synthetic fixture authority. Missing new
APIs are readiness failures, never evidence of a behavioral RED.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from company_admission_fixture import seed_company_app_access
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import User, UserSystemRole
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.pms.models import TaskList
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember
from miy_api.domains.whiteboard.access import resolve_whiteboard_access
from miy_api.domains.whiteboard.models import (
    Whiteboard,
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
    http_world as current_head_http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_actor_writer import (
    SERVICE,
    _collab_snapshot,
    _capture_before_actor_revision,
    _commands,
    _migration_snapshot as _owner_snapshot,
    _oid,
    _wait_for_blocker,
    actor_boundary as actor_boundary,  # noqa: F401
)

CAPABILITY = "public.miy_whiteboard_lock_edit_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
REVISION = "wb_actor_acl_20261009"
PARENT_REVISION = "wb_actor_owner_20261009"
MUTATING_COMMANDS = {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}


@pytest.fixture
def http_world(current_head_http_world, request, tmp_path, monkeypatch):  # noqa: F811
    if getattr(request, "param", None) is None:
        return current_head_http_world
    _capture_before_actor_revision(current_head_http_world)
    with current_head_http_world.core() as db:
        dsn = make_conninfo(
            **db.get_bind().url.translate_connect_args(username="user", database="dbname")
        )
    migration_revision_world(
        SimpleNamespace(dsn=dsn),
        request,
        tmp_path,
        monkeypatch,
        expected_revision=REVISION,
        config_alias_module=__name__,
    )
    return current_head_http_world


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
    if hasattr(c.world, "owner_revision_execution"):
        c.execution = c.world.owner_revision_execution
    else:
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


@pytest.mark.parametrize(
    "kind,role,allowed", [("pms_space", "member", True), ("pms_space", "viewer", False)]
)
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


@pytest.mark.parametrize("witness,finish", [("meeting_organizer", "commit")])
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


@pytest.mark.parametrize("selected", ["pms_direct_role"])
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


def _snapshot(c):
    original = _owner_snapshot(c)
    with c.connect() as conn:
        acl = conn.execute(
            "SELECT pg_get_function_identity_arguments(p.oid),p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_edit_actor' ORDER BY 1"
        ).fetchall()
    return {**original, "acl": acl}


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_acl_capability_install_edit_drain_retains_all_source_owners(acl_prepared):
    c = acl_prepared
    with c.connect() as conn:
        assert conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE oid=%s", (c.capability_owner_oid,)
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE')",
            (c.source, CAPABILITY, c.source, SERVICE),
        ).fetchone() == (True, False)
    with Session(c.source_engine) as db:
        with pytest.raises(DBAPIError) as denied_read:
            db.execute(text("SELECT owner_id FROM whiteboards"))
        assert denied_read.value.orig.sqlstate == "42501"
        db.rollback()
        with pytest.raises(DBAPIError) as denied_write:
            db.execute(text("UPDATE whiteboard_collab_documents SET yjs_state=NULL WHERE false"))
        assert denied_write.value.orig.sqlstate == "42501"
        db.rollback()
    original = _collab_snapshot(c)
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        assert _lock(c, db) is None
        db.commit()
    assert set(commands) <= {"SELECT", "SET", "SHOW"}
    assert _collab_snapshot(c) == original
    with c.connect() as conn:
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        assert _prepare(c, db).writer == c.writer
        db.commit()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audits
    before = _snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_acl_requires_draining"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)), PARENT_REVISION
        )
    assert _snapshot(c) == before
    drained = move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation > ACTIVE.generation
    before = _snapshot(c)
    command.downgrade(
        _migration_config(c.engine.url.render_as_string(hide_password=False)), PARENT_REVISION
    )
    removed = _snapshot(c)
    assert removed["existing"] == before["existing"]
    assert _collab_snapshot(c) == original
    assert removed["version"] == PARENT_REVISION
    assert removed["acl"] == [] and removed["actor"] == before["actor"]
    with Session(c.source_engine) as db:
        _refused(c, db)
