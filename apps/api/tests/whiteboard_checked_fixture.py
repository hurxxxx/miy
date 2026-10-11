"""Public synthetic migrated PG fixture for inactive checked-storage tests.

The existing yielding clone and supplied-role fixtures own all cleanup. No live
service, operational role/config, customer fixture, factory wiring or activation.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from miy_api.domains.official_apps import whiteboard_checked_writer_roles as roles
from miy_api.domains.official_apps.whiteboard_actor_writer import capture_whiteboard_write_execution
from miy_api.domains.whiteboard import checked_save as runtime
from miy_api.domains.whiteboard.models import WhiteboardCollabDocument
from miy_api.domains.whiteboard.scene_state import make_fresh_whiteboard_room_key
from test_official_writer_roles import ACTIVE, DRAIN, PASSWORD, move
from test_whiteboard_actor_acl_writer import _install as install_acl


def contract_kwargs(c):
    return {
        name: getattr(c.source_writer, name)
        for name in (
            "source_owner_oid",
            "core_owner_oid",
            "acl_owner_oid",
            "service_capability_owner_oid",
            "producer_owner_oid",
            "source_guard_owner_oid",
            "trigger_owner_oid",
        )
    }


def install(c, db):
    return roles.install_whiteboard_checked_guard(
        db,
        c.actor,
        source_guard_owner=c.checked_source_owner,
        core_guard_owner=c.checked_core_owner,
        expected=DRAIN,
        expected_migration_owner_oid=c.migration_owner_oid,
        expected_acl_owner_oid=c.acl_owner_oid,
        expected_service_capability_owner_oid=c.service_capability_owner_oid,
        expected_producer_owner_oid=c.producer_owner_oid,
        expected_source_guard_owner_oid=c.source_guard_owner_oid,
    )


def prepare(c, db, *, role_name, kind):
    return roles.prepare_whiteboard_checked_principal(
        db,
        c.actor,
        role_name=role_name,
        kind=kind,
        identity=ACTIVE,
        expected=c.expected,
        expected_state=c.expected_state,
        source_owner_oid=c.checked_source_owner_oid,
        core_owner_oid=c.checked_core_owner_oid,
        acl_owner_oid=c.acl_owner_oid,
        service_capability_owner_oid=c.service_capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
        trigger_owner_oid=c.migration_owner_oid,
    )


@pytest.fixture
def checked_boundary(acl_boundary):
    base = acl_boundary
    c = SimpleNamespace(**vars(base))
    c.acl_api = base.api
    c.acl_owner_oid = base.capability_owner_oid
    c.checked_source_owner = base.role(login=False)
    c.checked_core_owner = base.role(login=False)
    c.source = base.role()
    c.core_sealer = base.role()
    with c.connect() as conn:
        c.checked_source_owner_oid = conn.execute(
            "SELECT oid::bigint FROM pg_roles WHERE rolname=%s", (c.checked_source_owner,)
        ).fetchone()[0]
        c.checked_core_owner_oid = conn.execute(
            "SELECT oid::bigint FROM pg_roles WHERE rolname=%s", (c.checked_core_owner,)
        ).fetchone()[0]
        c.migration_owner_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure",
            (roles.SAVE_CAPABILITY,),
        ).fetchone()[0]
    with Session(c.engine) as db:
        assert install_acl(base, db) is None
        db.commit()
    c.api = SimpleNamespace(roles=roles, runtime=runtime)
    return c


@pytest.fixture
def checked_prepared(checked_boundary):
    c = checked_boundary
    with Session(c.engine) as db:
        assert install(c, db) is None
        c.source_writer = prepare(c, db, role_name=c.source, kind="source").writer
        c.core_writer = prepare(c, db, role_name=c.core_sealer, kind="core").writer
        db.commit()
    assert move(c.control, DRAIN, "draining", state="active", artifact=ACTIVE.artifact) == ACTIVE
    c.expected, c.expected_state = ACTIVE, "active"
    with c.connect() as conn:
        # Privileged synthetic Core alone can seed/update existing guarded Source
        # metadata. Neither tested LOGIN receives this authority.
        conn.execute(
            "INSERT INTO official_writer_principals(role_oid,role_name,scope,owner,generation,artifact,approved_by_user_id,approved_by_session_id,created_at) SELECT oid::bigint,rolname,%s,%s,%s,%s,%s,%s,timezone('UTC',clock_timestamp()) FROM pg_roles WHERE rolname=session_user",
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
        c.engine.url.set(username=c.source, password=PASSWORD), pool_size=4, max_overflow=0
    )
    c.core_engine = create_engine(
        c.engine.url.set(username=c.core_sealer, password=PASSWORD), pool_size=4, max_overflow=0
    )
    c.execution = capture_whiteboard_write_execution(
        c.world.factory,
        token=c.world.token,
        original_user_id=c.world.state["member_id"],
        original_source_session_id=c.world.state["source_id"],
    )
    c.collab_id = str(uuid4())
    c.room_key = make_fresh_whiteboard_room_key(c.board_id)
    with Session(c.engine) as db:
        db.execute(
            text("UPDATE public.whiteboards SET owner_id=:owner WHERE id=:board"),
            {"owner": c.execution.actor_user_id, "board": c.board_id},
        )
        db.add(
            WhiteboardCollabDocument(
                id=c.collab_id,
                room_key=c.room_key,
                whiteboard_id=c.board_id,
                yjs_state=b"original",
                snapshot_scene={"original": True},
            )
        )
        db.commit()
    try:
        yield c
    finally:
        c.core_engine.dispose()
        c.source_engine.dispose()


def content(c):
    with c.connect() as conn:
        return conn.execute(
            "SELECT content_incarnation_id,content_revision,yjs_state,snapshot_scene,updated_at FROM public.whiteboard_collab_documents WHERE id=%s",
            (c.collab_id,),
        ).fetchone()


def ledger(c, attempt):
    with c.connect() as conn:
        return conn.execute(
            "SELECT state,result_incarnation_id,result_revision,request_digest FROM public.whiteboard_checked_attempts WHERE attempt_id=%s",
            (attempt.attempt_id,),
        ).fetchone()


def seal(
    c,
    *,
    attempt_id=None,
    contributors=None,
    yjs=b"checked-change",
    snapshot=None,
    commit=True,
    db=None,
    **overrides,
):
    live = content(c)
    kwargs = dict(
        writer=c.core_writer,
        attempt_id=attempt_id or uuid4(),
        source_role_oid=c.source_writer.role_oid,
        source_role_name=c.source_writer.role_name,
        whiteboard_id=c.board_id,
        collab_id=c.collab_id,
        room_key=c.room_key,
        content_incarnation_id=live[0],
        base_revision=live[1],
        yjs_state=yjs,
        snapshot_scene={"checked": True} if snapshot is None else snapshot,
        cohort_cutoff=1,
        contributors=(c.execution,) if contributors is None else contributors,
    )
    kwargs.update(overrides)
    if db is not None:
        return runtime.seal_whiteboard_checked_attempt(db, **kwargs)
    with Session(c.core_engine) as owned:
        result = runtime.seal_whiteboard_checked_attempt(owned, **kwargs)
        if commit:
            owned.commit()
        else:
            owned.rollback()
        return result


def stage(c, db, attempt, **overrides):
    return runtime.stage_whiteboard_checked_save(
        db, writer=overrides.get("writer", c.source_writer), attempt=attempt
    )


def resolve(c, db, attempt, **overrides):
    return runtime.resolve_whiteboard_checked_attempt(
        db, writer=overrides.get("writer", c.core_writer), attempt=attempt
    )
