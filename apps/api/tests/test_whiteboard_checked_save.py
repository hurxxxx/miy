"""Inactive C1 contracts against pure descriptors and real synthetic migrated PG.

No live native/factory/config activation. Staging remains caller-owned; every
saved assertion follows actual COMMIT. Missing APIs are readiness failures.
"""

from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from _migration_revision_fixtures import migration_revision_world
import psycopg
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from miy_api.domains.official_apps import whiteboard_checked_writer_roles as roles
from miy_api.domains.whiteboard import checked_save as runtime
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, move
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as current_head_http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_actor_acl_writer import acl_boundary as acl_boundary  # noqa: F401
from test_whiteboard_actor_writer import (
    _capture_before_actor_revision,
    actor_boundary as actor_boundary,  # noqa: F401
)
from whiteboard_checked_fixture import (
    checked_boundary as checked_boundary,  # noqa: F401
    checked_prepared as checked_prepared,  # noqa: F401
    content,
    ledger,
    resolve,
    seal,
    stage,
)


REVISION = "wb_checked_cas_20261009"


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


def _pure_writer(kind="source"):
    return roles.WhiteboardCheckedProfile(1, "checked_synthetic", ACTIVE, kind, 2, 3, 4, 5, 6, 7, 8)


def _pure_ref():
    return runtime.WhiteboardCheckedAttemptRef(
        uuid4(), "a" * 64, "synthetic_database", 42, None, None
    )


def _guarded_c1_upgrade_snapshot(engine):
    """Compare existing synthetic authority and data, excluding only C1 additions."""
    with engine.connect() as db:
        return {
            "payload": db.execute(
                text(
                    "SELECT id,whiteboard_id,room_key,yjs_state,snapshot_scene,last_snapshot_at,created_at,updated_at,writer_scope "
                    "FROM public.whiteboard_collab_documents ORDER BY id"
                )
            ).all(),
            "guards": db.execute(
                text(
                    "SELECT c.relname,t.oid,t.tgfoid,t.tgenabled,t.tgtype,t.tgnargs,t.tgargs,"
                    "p.proname,p.proowner,p.prosrc,p.proacl::text,p.proconfig "
                    "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid "
                    "WHERE n.nspname='public' AND t.tgname='miy_official_source_writer' ORDER BY c.relname"
                )
            ).all(),
            "prior_functions": db.execute(
                text(
                    "SELECT p.oid,p.proname,p.proowner,p.prosrc,p.proacl::text,p.proconfig,"
                    "p.prosecdef,p.proargnames,p.proargmodes,pg_catalog.pg_get_function_identity_arguments(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname NOT IN "
                    "('miy_whiteboard_seal_checked','miy_whiteboard_save_checked','miy_whiteboard_resolve_checked',"
                    "'miy_whiteboard_content_revision','miy_whiteboard_checked_immutable') ORDER BY p.oid"
                )
            ).all(),
            "existing_table_authority": db.execute(
                text(
                    "SELECT c.oid,c.relname,c.relowner,c.relacl::text,a.attnum,a.attname,a.attacl::text "
                    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
                    "AND c.relname NOT IN ('whiteboard_checked_attempts','whiteboard_checked_contributors') "
                    "AND NOT (c.relname='whiteboard_collab_documents' "
                    "AND a.attname IN ('content_incarnation_id','content_revision')) ORDER BY c.oid,a.attnum"
                )
            ).all(),
            "principals": db.execute(
                text("SELECT * FROM public.official_writer_principals ORDER BY role_oid")
            ).all(),
            "ownership": db.execute(
                text("SELECT * FROM public.official_runtime_ownership ORDER BY scope")
            ).all(),
            "roles": db.execute(
                text(
                    "SELECT oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                    "rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil,rolconfig "
                    "FROM pg_catalog.pg_roles ORDER BY oid"
                )
            ).all(),
            "memberships": db.execute(
                text(
                    "SELECT roleid,member,grantor,admin_option,inherit_option,set_option "
                    "FROM pg_catalog.pg_auth_members ORDER BY oid"
                )
            ).all(),
            "default_acl": db.execute(
                text(
                    "SELECT oid,defaclrole,defaclnamespace,defaclobjtype,defaclacl::text "
                    "FROM pg_catalog.pg_default_acl ORDER BY oid"
                )
            ).all(),
        }


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_checked_attempt_commit_rollback_and_history_preservation(checked_prepared):
    c = checked_prepared
    with c.connect(c.source) as conn:
        with pytest.raises(psycopg.Error) as denied_source:
            conn.execute("UPDATE whiteboard_collab_documents SET yjs_state=NULL WHERE false")
        assert denied_source.value.sqlstate == "42501"
        conn.rollback()
    with c.connect(c.core_sealer) as conn:
        with pytest.raises(psycopg.Error) as denied_core:
            conn.execute("SELECT yjs_state FROM whiteboard_collab_documents")
        assert denied_core.value.sqlstate == "42501"
        conn.rollback()
    c = checked_prepared
    before = content(c)
    attempt = seal(c)
    with Session(c.source_engine) as db:
        conn = db.connection()
        transaction = db.get_transaction()
        receipt = stage(c, db, attempt)
        assert type(receipt) is runtime.WhiteboardCheckedStage
        assert (
            receipt.content_incarnation_id == before[0]
            and receipt.content_revision == before[1] + 1
        )
        assert db.connection() is conn and db.get_transaction() is transaction
        assert ledger(c, attempt)[0] == "sealed" and content(c) == before
        db.commit()
    assert content(c)[0:4] == (before[0], before[1] + 1, b"checked-change", {"checked": True})
    assert ledger(c, attempt)[0:3] == ("committed", before[0], before[1] + 1)
    with Session(c.core_engine) as db:
        outcome = resolve(c, db, attempt)
        db.commit()
    assert outcome.state == "committed" and outcome.receipt == receipt
    c = checked_prepared
    before = content(c)
    attempt = seal(c)
    with Session(c.source_engine) as db:
        stage(c, db, attempt)
        db.rollback()
    assert content(c) == before and ledger(c, attempt)[0] == "sealed"
    with Session(c.core_engine) as db:
        result = resolve(c, db, attempt)
        assert result.state == "cancelled_not_committed" and result.receipt is None
        assert ledger(c, attempt)[0] == "sealed"
        db.commit()
    assert ledger(c, attempt)[0] == "cancelled_not_committed"
    with Session(c.source_engine) as db:
        with pytest.raises(runtime.WhiteboardCheckedWriterRefused):
            stage(c, db, attempt)
        db.rollback()
    assert content(c) == before
    c = checked_prepared
    attempt = seal(c)
    with Session(c.core_engine) as db:
        resolve(c, db, attempt)
        db.commit()
    drained = move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation > ACTIVE.generation
    before = ledger(c, attempt)
    with pytest.raises(RuntimeError, match="whiteboard_checked_history_requires_retirement"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)),
            "wb_actor_acl_20261009",
        )
    assert ledger(c, attempt) == before
