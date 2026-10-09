"""Inactive C1 contracts against pure descriptors and real synthetic migrated PG.

No live native/factory/config activation. Staging remains caller-owned; every
saved assertion follows actual COMMIT. Missing APIs are readiness failures.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command
from _migration_revision_fixtures import migration_revision_world
import psycopg
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.official_apps import whiteboard_checked_writer_roles as roles
from miy_api.domains.official_apps.whiteboard_actor_writer import CapturedWhiteboardWriteExecution
from miy_api.domains.official_apps.whiteboard_checked_models import (
    WhiteboardCheckedAttempt,
    WhiteboardCheckedContributor,
)
from miy_api.domains.whiteboard import checked_save as runtime
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
from miy_api.domains.whiteboard.scene_state import make_fresh_whiteboard_room_key
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, BASE, PASSWORD, move
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as current_head_http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_actor_acl_writer import acl_boundary as acl_boundary  # noqa: F401
from test_whiteboard_actor_writer import actor_boundary as actor_boundary  # noqa: F401
from whiteboard_checked_fixture import (
    checked_boundary as checked_boundary,  # noqa: F401
    checked_prepared as checked_prepared,  # noqa: F401
    content,
    contract_kwargs,
    install,
    ledger,
    prepare,
    resolve,
    seal,
    stage,
)


REVISION = "wb_checked_cas_20261009"


@pytest.fixture
def http_world(current_head_http_world, request, tmp_path, monkeypatch):  # noqa: F811
    if getattr(request, "param", None) is None:
        return current_head_http_world
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


def test_pure_private_original_attempt_and_receipt_are_frozen_without_digest_repr():
    attempt = _pure_ref()
    receipt = runtime.WhiteboardCheckedStage(attempt, uuid4(), 1)
    resolution = runtime.WhiteboardCheckedResolution(attempt, "committed", receipt)
    for value in (attempt, receipt, resolution):
        assert attempt.request_digest not in repr(value)
        assert not hasattr(value, "model_dump") and not hasattr(value, "to_json")
        with pytest.raises(FrozenInstanceError):
            value.extra = True
    with pytest.raises(runtime.WhiteboardCheckedWriterRefused) as caught:
        replace(attempt, request_digest="secret malformed digest")
    assert str(caught.value) == "whiteboard_checked_writer_refused"
    assert "secret" not in repr(caught.value)


@pytest.mark.parametrize(
    "model", [WhiteboardCheckedAttempt, WhiteboardCheckedContributor, WhiteboardCollabDocument]
)
def test_pure_checked_models_cannot_route_to_another_engine_before_sql(model):
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    calls = []
    for engine in (first, second):
        event.listen(engine, "before_cursor_execute", lambda *_: calls.append(1))
    try:
        with Session(bind=first, binds={model: second}) as db:
            with pytest.raises(runtime.WhiteboardCheckedWriterRefused) as caught:
                runtime.stage_whiteboard_checked_save(
                    db, writer=_pure_writer(), attempt=_pure_ref()
                )
            assert caught.value.reason == "single_caller_engine_required"
            assert calls == [] and not db.in_transaction()
    finally:
        first.dispose()
        second.dispose()


def test_pure_content_columns_do_not_expand_existing_full_entity_select_or_eager_defaults():
    selected = select(WhiteboardCollabDocument).compile().string
    assert "content_revision" not in selected and "content_incarnation_id" not in selected
    assert WhiteboardCollabDocument.__mapper__.eager_defaults is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("contributors", ()),
        ("contributors", [1]),
        ("contributors", (None,)),
        ("yjs_state", bytearray(b"x")),
        ("yjs_state", b"x" * (runtime.MAX_PAYLOAD_BYTES + 1)),
        ("snapshot_scene", {"bad": float("nan")}),
        ("base_revision", True),
        ("cohort_cutoff", 0),
    ],
    ids=[
        "empty-cohort",
        "mutable-cohort",
        "nonoriginal-contributor",
        "mutable-payload",
        "oversized-payload",
        "nonfinite-snapshot",
        "boolean-revision",
        "missing-cutoff",
    ],
)
def test_pure_seal_refuses_unbounded_or_nonoriginal_input_before_sql(field, value, monkeypatch):
    engine = create_engine("sqlite://")
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *_: calls.append(1))
    capture = CapturedWhiteboardWriteExecution(
        "a" * 64,
        "user",
        "session",
        "installation",
        1,
        "binding",
        "release",
        "proof",
        "sha256:" + "a" * 64,
        "https://app.example.test",
        "dev",
        "synthetic_database",
        42,
        None,
        None,
    )
    kwargs = dict(
        writer=_pure_writer("core"),
        attempt_id=uuid4(),
        source_role_oid=9,
        source_role_name="original_source",
        whiteboard_id="board",
        collab_id="collab",
        room_key="room",
        content_incarnation_id=uuid4(),
        base_revision=0,
        yjs_state=b"x",
        snapshot_scene={},
        cohort_cutoff=1,
        contributors=(capture,),
    )
    kwargs[field] = value
    try:
        with Session(engine) as db:
            with pytest.raises(runtime.WhiteboardCheckedWriterRefused):
                runtime.seal_whiteboard_checked_attempt(db, **kwargs)
            assert calls == [] and not db.in_transaction()
    finally:
        engine.dispose()


def test_genuine_sealed_attempt_has_exact_payload_and_original_full_cohort(checked_prepared):
    c = checked_prepared
    second = replace(c.execution, delegated_token_digest="d" * 64)
    attempt = seal(
        c,
        contributors=(c.execution, second),
        yjs=b"exact-content",
        snapshot={"unicode": "한글"},
        cohort_cutoff=37,
    )
    with c.connect() as conn:
        row = conn.execute(
            "SELECT source_role_oid,source_role_name,seal_role_oid,seal_role_name,yjs_state,snapshot_scene,cohort_cutoff,contributor_count,composition_epoch,state FROM whiteboard_checked_attempts WHERE attempt_id=%s",
            (attempt.attempt_id,),
        ).fetchone()
        assert row == (
            c.source_writer.role_oid,
            c.source,
            c.core_writer.role_oid,
            c.core_sealer,
            b"exact-content",
            {"unicode": "한글"},
            37,
            2,
            "whiteboard_checked_cas_v1",
            "sealed",
        )
        cohort = conn.execute(
            "SELECT ordinal,delegated_token_digest,actor_user_id,source_session_id FROM whiteboard_checked_contributors WHERE attempt_id=%s ORDER BY ordinal",
            (attempt.attempt_id,),
        ).fetchall()
        assert cohort == [
            (
                1,
                c.execution.delegated_token_digest,
                c.execution.actor_user_id,
                c.execution.source_session_id,
            ),
            (2, "d" * 64, c.execution.actor_user_id, c.execution.source_session_id),
        ]
    before = content(c)
    with Session(c.source_engine) as db:
        with pytest.raises(runtime.WhiteboardCheckedWriterRefused):
            stage(c, db, attempt)
        db.rollback()
    assert content(c) == before and ledger(c, attempt)[0] == "sealed"


def test_genuine_stage_and_durable_receipt_share_actual_caller_commit(checked_prepared):
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


def test_genuine_source_rollback_keeps_content_and_receipt_uncommitted_then_core_cancels(
    checked_prepared,
):
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


def test_genuine_exact_seal_replay_has_no_writes_and_mismatched_intent_never_repairs(
    checked_prepared,
):
    c = checked_prepared
    attempt_id = uuid4()
    attempt = seal(c, attempt_id=attempt_id)
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(c.core_engine, "before_cursor_execute", observe)
    try:
        assert seal(c, attempt_id=attempt_id) == attempt
        assert set(commands) <= {"SELECT", "SET", "SHOW"}
        before = ledger(c, attempt)
        with pytest.raises(runtime.WhiteboardCheckedWriterRefused):
            seal(c, attempt_id=attempt_id, yjs=b"replaced-intent")
        assert ledger(c, attempt) == before
    finally:
        event.remove(c.core_engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "kind,statement",
    [
        ("source", "SELECT request_digest FROM public.whiteboard_checked_attempts"),
        ("source", "UPDATE public.whiteboard_collab_documents SET yjs_state=decode('00','hex')"),
        ("core", "SELECT actor_user_id FROM public.whiteboard_checked_contributors"),
        ("core", "UPDATE public.whiteboard_checked_attempts SET state='committed'"),
        (
            "source",
            "SELECT public.miy_whiteboard_resolve_checked(gen_random_uuid(),repeat('a',64))",
        ),
        (
            "source",
            "SELECT public.miy_whiteboard_seal_checked(gen_random_uuid(),1::bigint,'no_role',1,'x','b','c','r',gen_random_uuid(),0::bigint,NULL,NULL,1::bigint,'[]'::jsonb)",
        ),
        ("core", "SELECT public.miy_whiteboard_save_checked(gen_random_uuid(),repeat('a',64))"),
    ],
)
def test_genuine_source_and_core_logins_cannot_bypass_private_capability_boundary(
    checked_prepared, kind, statement
):
    c = checked_prepared
    role = c.source if kind == "source" else c.core_sealer
    with c.connect(role) as conn:
        with pytest.raises(psycopg.Error) as caught:
            conn.execute(statement)
        assert caught.value.sqlstate == "42501"
        conn.rollback()


def test_genuine_exact_preparation_and_guard_replay_have_no_mutations(checked_prepared):
    c = checked_prepared
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(c.engine, "before_cursor_execute", observe)
    try:
        with Session(c.engine) as db:
            assert prepare(c, db, role_name=c.source, kind="source").writer == c.source_writer
            assert prepare(c, db, role_name=c.core_sealer, kind="core").writer == c.core_writer
            db.commit()
        assert set(commands) <= {"SELECT", "SET", "SHOW"}
    finally:
        event.remove(c.engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("kind", ["source", "core"])
def test_genuine_role_profile_is_exact_login_dml0_and_fixed_owner_column_closure(
    checked_prepared, kind
):
    c = checked_prepared
    role = c.source if kind == "source" else c.core_sealer
    owner = c.checked_source_owner if kind == "source" else c.checked_core_owner
    manifests = {
        "SELECT": roles.SOURCE_READ_COLUMNS if kind == "source" else roles.CORE_READ_COLUMNS,
        "UPDATE": roles.SOURCE_UPDATE_COLUMNS if kind == "source" else roles.CORE_UPDATE_COLUMNS,
        "INSERT": {} if kind == "source" else roles.CORE_INSERT_COLUMNS,
    }
    with c.connect() as conn:
        for tested, expected in (
            (role, set()),
            (
                owner,
                {
                    (table, column, privilege)
                    for privilege, manifest in manifests.items()
                    for table, columns in manifest.items()
                    for column in columns
                },
            ),
        ):
            effective = set()
            rows = conn.execute(
                "SELECT n.nspname,c.relname,a.attname,has_column_privilege(%s,c.oid,a.attnum,'SELECT'),has_column_privilege(%s,c.oid,a.attnum,'INSERT'),has_column_privilege(%s,c.oid,a.attnum,'UPDATE'),has_column_privilege(%s,c.oid,a.attnum,'REFERENCES') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind IN ('r','p','v','m','f')",
                (tested,) * 4,
            )
            for schema, table, column, *grants in rows:
                for privilege, granted in zip(
                    ("SELECT", "INSERT", "UPDATE", "REFERENCES"), grants, strict=True
                ):
                    if granted:
                        assert schema == "public"
                        effective.add((table, column, privilege))
            assert effective == expected
        executable = conn.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prosecdef AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY 1",
            (role,),
        ).fetchall()
        assert executable == (
            [("miy_whiteboard_save_checked",)]
            if kind == "source"
            else [("miy_whiteboard_resolve_checked",), ("miy_whiteboard_seal_checked",)]
        )
    with Session(c.source_engine) as db:
        roles.whiteboard_checked_contract(db, **contract_kwargs(c))
        db.rollback()


def test_genuine_legacy_content_writes_advance_revision_and_noop_preserves_timestamp(
    checked_prepared,
):
    c = checked_prepared
    before = content(c)
    with c.connect() as conn:
        conn.execute(
            "UPDATE whiteboard_collab_documents SET yjs_state=%s,updated_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
            (before[2], c.collab_id),
        )
    assert content(c) == before
    with c.connect() as conn:
        conn.execute(
            "UPDATE whiteboard_collab_documents SET snapshot_scene=%s::json,updated_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
            ('{"new_snapshot":true}', c.collab_id),
        )
    changed = content(c)
    assert (
        changed[0] == before[0]
        and changed[1] == before[1] + 1
        and changed[2] == before[2]
        and changed[3] == {"new_snapshot": True}
    )
    assert changed[4] > before[4]
    with c.connect() as conn:
        with pytest.raises(psycopg.Error) as caught:
            conn.execute(
                "UPDATE whiteboard_collab_documents SET content_incarnation_id=%s WHERE id=%s",
                (uuid4(), c.collab_id),
            )
        assert caught.value.sqlstate == "55000"
        conn.rollback()
    assert content(c) == changed


def test_genuine_existing_source8_native_save_still_works_without_grant_expansion(checked_prepared):
    from miy_api.domains.official_apps.whiteboard_source_writer_roles import (
        prepare_whiteboard_source_writer_principal,
    )
    from miy_api.domains.whiteboard.scene_state import persist_runtime_yjs_state

    c = checked_prepared
    legacy = c.role()
    with Session(c.engine) as db:
        prepare_whiteboard_source_writer_principal(
            db,
            c.actor,
            role_name=legacy,
            identity=ACTIVE,
            expected=ACTIVE,
            expected_state="active",
            capability_owner_oid=c.service_capability_owner_oid,
            producer_owner_oid=c.producer_owner_oid,
            source_guard_owner_oid=c.source_guard_owner_oid,
        )
        db.commit()
    engine = create_engine(c.engine.url.set(username=legacy, password=PASSWORD))
    before = content(c)
    try:
        result = persist_runtime_yjs_state(
            lambda: Session(engine),
            whiteboard_id=c.board_id,
            yjs_state=b"legacy-source8-change",
            expected_room_key=c.room_key,
            expected_collab_id=c.collab_id,
        )
        assert result.status == "acknowledged"
        after = content(c)
        assert (
            after[0] == before[0]
            and after[1] == before[1] + 1
            and after[2] == b"legacy-source8-change"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_genuine_empty_legacy_c1_migration_roundtrip_preserves_existing_columns_and_guards(
    http_world,
):
    with http_world.core() as db:
        engine = db.get_bind()
        before = db.execute(
            text(
                "SELECT id,whiteboard_id,room_key,yjs_state,snapshot_scene,created_at,updated_at,writer_scope FROM whiteboard_collab_documents ORDER BY id"
            )
        ).all()
    config = _migration_config(engine.url.render_as_string(hide_password=False))
    command.downgrade(config, "wb_actor_acl_20261009")
    command.upgrade(config, "wb_checked_cas_20261009")
    with Session(engine) as db:
        assert (
            db.execute(
                text(
                    "SELECT id,whiteboard_id,room_key,yjs_state,snapshot_scene,created_at,updated_at,writer_scope FROM whiteboard_collab_documents ORDER BY id"
                )
            ).all()
            == before
        )
        assert db.scalar(text("SELECT count(*) FROM whiteboard_checked_attempts")) == 0


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_genuine_actual_hardened_active_c1_downgrade_refuses_without_changes(checked_prepared):
    c = checked_prepared
    before = content(c)
    with pytest.raises(RuntimeError, match="whiteboard_checked_requires_draining"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)),
            "wb_actor_acl_20261009",
        )
    assert content(c) == before
    with Session(c.source_engine) as db:
        roles.whiteboard_checked_contract(db, **contract_kwargs(c))
        db.rollback()


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_genuine_drained_downgrade_never_discards_even_cancelled_attempt_history(checked_prepared):
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


def test_genuine_exact_guard_install_replay_under_drain_is_observation_only(checked_boundary):
    c = checked_boundary
    with Session(c.engine) as db:
        assert install(c, db) is None
        db.commit()
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(c.engine, "before_cursor_execute", observe)
    try:
        with Session(c.engine) as db:
            assert install(c, db) is None
            db.commit()
        assert set(commands) <= {"SELECT", "SET", "SHOW"}
    finally:
        event.remove(c.engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("http_world", [REVISION], indirect=True)
def test_genuine_empty_drained_rollback_removes_only_c1_and_preserves_roles_payload_guards(
    checked_prepared,
):
    c = checked_prepared
    move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)

    def snapshot():
        with c.connect() as conn:
            payload = conn.execute(
                "SELECT id,whiteboard_id,room_key,yjs_state,snapshot_scene,created_at,updated_at,writer_scope FROM whiteboard_collab_documents ORDER BY id"
            ).fetchall()
            principals = conn.execute(
                "SELECT * FROM official_writer_principals ORDER BY role_oid"
            ).fetchall()
            prior = conn.execute(
                "SELECT p.proname,p.proowner::bigint,p.prosrc,p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN ('miy_recording_lock_producer','miy_whiteboard_lock_source_writer','miy_whiteboard_lock_owner_actor','miy_whiteboard_lock_edit_actor','miy_guard_official_source_writer_by_role') ORDER BY 1"
            ).fetchall()
            return payload, principals, prior

    before = snapshot()
    command.downgrade(
        _migration_config(c.engine.url.render_as_string(hide_password=False)),
        "wb_actor_acl_20261009",
    )
    assert snapshot() == before
    with c.connect() as conn:
        assert conn.execute(
            "SELECT to_regclass('public.whiteboard_checked_attempts'),to_regclass('public.whiteboard_checked_contributors'),to_regprocedure(%s)",
            (roles.SAVE_CAPABILITY,),
        ).fetchone() == (None, None, None)


def test_pure_stage_refuses_nested_savepoint_without_issuing_sql_or_owning_cleanup():
    engine = create_engine("sqlite://")
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *_: calls.append(1))
    try:
        with Session(engine) as db:
            nested = db.begin_nested()
            with pytest.raises(runtime.WhiteboardCheckedWriterRefused) as caught:
                runtime.stage_whiteboard_checked_save(
                    db, writer=_pure_writer(), attempt=_pure_ref()
                )
            assert caught.value.reason == "caller_outer_transaction_required"
            assert calls == [] and db.get_nested_transaction() is nested
            nested.rollback()
    finally:
        engine.dispose()


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
@pytest.mark.parametrize("guard_kind", ["legacy", "hardened"])
@pytest.mark.parametrize("populated", [False, True], ids=["empty", "existing_rows"])
def test_genuine_draining_c1_upgrade_initializes_rows_without_business_dml(
    http_world, request, guard_kind, populated
):
    if guard_kind == "hardened":
        c = request.getfixturevalue("checked_prepared")
        engine, control, expected = c.engine, c.control, ACTIVE
        with Session(engine) as db:
            db.execute(
                text("DELETE FROM public.whiteboard_collab_documents WHERE id=:id"),
                {"id": c.collab_id},
            )
            db.commit()
    else:
        with http_world.core() as db:
            engine = db.get_bind()
            admin = resolve_auth_context_from_token(
                db, http_world.state["admin"]["token"], update_last_seen=False
            )
            db.expunge_all()
        control, expected = SimpleNamespace(engine=engine, actor=admin), BASE

    with Session(engine) as db:
        assert db.scalar(text("SELECT count(*) FROM public.whiteboard_collab_documents")) == 0
        if populated:
            for index in range(2):
                board_id = str(uuid4())
                db.add(
                    Whiteboard(
                        id=board_id,
                        owner_id=http_world.state["member_id"],
                        title="Synthetic guarded migration board",
                    )
                )
                db.flush()
                db.add(
                    WhiteboardCollabDocument(
                        id=str(uuid4()),
                        whiteboard_id=board_id,
                        room_key=make_fresh_whiteboard_room_key(board_id),
                        yjs_state=b"\x00guarded-migration" if index == 0 else None,
                        snapshot_scene={"synthetic": index} if index == 0 else None,
                        last_snapshot_at=datetime(2026, 10, 9, 1, 2, 3),
                        created_at=datetime(2026, 10, 8, 1, 2, 3),
                        updated_at=datetime(2026, 10, 8, 4, 5, 6),
                    )
                )
        db.commit()

    drained = move(control, expected, "active", state="draining", artifact=expected.artifact)
    assert drained.generation == expected.generation + 1
    config = _migration_config(engine.url.render_as_string(hide_password=False))
    command.downgrade(config, "wb_actor_acl_20261009")
    before = _guarded_c1_upgrade_snapshot(engine)
    assert len(before["payload"]) == (2 if populated else 0)
    assert len(before["guards"]) == 90
    assert {row[7] for row in before["guards"]} == {
        "miy_guard_official_source_writer_by_role"
        if guard_kind == "hardened"
        else "miy_guard_official_source_writer"
    }
    # Statement guards must still reject a zero-row UPDATE under drain.
    with Session(engine) as db:
        with pytest.raises(DBAPIError) as refused:
            db.execute(
                text(
                    "UPDATE public.whiteboard_collab_documents SET yjs_state=yjs_state WHERE false"
                )
            )
        assert refused.value.orig.sqlstate == "55000"
        assert refused.value.orig.diag.message_primary == "official_writer_fenced"
        db.rollback()

    unsafe = []

    def observe(_conn, _cursor, statement, *_):
        upper = statement.lstrip().upper()
        if upper.startswith("UPDATE ") and not upper.startswith("UPDATE ALEMBIC_VERSION "):
            unsafe.append("business_update")
        if upper.startswith("ALTER ") and "DISABLE TRIGGER" in upper:
            unsafe.append("disable_trigger")
        if upper.startswith("SET ") and any(
            marker in upper
            for marker in ("SESSION_REPLICATION_ROLE", "ROLE ", "SESSION AUTHORIZATION")
        ):
            unsafe.append("session_authority")

    event.listen(Engine, "before_cursor_execute", observe)
    try:
        command.upgrade(config, REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert unsafe == []
    assert _guarded_c1_upgrade_snapshot(engine) == before
    with engine.connect() as db:
        incarnations = db.execute(
            text(
                "SELECT content_incarnation_id,content_revision FROM public.whiteboard_collab_documents ORDER BY id"
            )
        ).all()
        assert all(
            isinstance(incarnation, UUID) and incarnation != UUID(int=0) and revision == 0
            for incarnation, revision in incarnations
        )
        assert len({row[0] for row in incarnations}) == len(incarnations)
        assert (
            db.execute(
                text(
                    "SELECT content_incarnation_id,content_revision FROM public.whiteboard_collab_documents ORDER BY id"
                )
            ).all()
            == incarnations
        )
        assert db.execute(
            text(
                "SELECT a.attname,a.attnotnull,pg_catalog.format_type(a.atttypid,a.atttypmod),"
                "pg_catalog.pg_get_expr(d.adbin,d.adrelid) FROM pg_catalog.pg_attribute a "
                "JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                "WHERE a.attrelid='public.whiteboard_collab_documents'::regclass "
                "AND a.attname IN ('content_incarnation_id','content_revision') ORDER BY a.attname"
            )
        ).all() == [
            (
                "content_incarnation_id",
                True,
                "uuid",
                "'00000000-0000-0000-0000-000000000000'::uuid",
            ),
            ("content_revision", True, "bigint", "0"),
        ]
        assert db.scalar(text("SELECT count(*) FROM public.whiteboard_checked_attempts")) == 0
        assert db.scalar(text("SELECT count(*) FROM public.whiteboard_checked_contributors")) == 0
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname IN "
                    "('miy_whiteboard_seal_checked','miy_whiteboard_save_checked','miy_whiteboard_resolve_checked',"
                    "'miy_whiteboard_content_revision','miy_whiteboard_checked_immutable') "
                    "AND NOT EXISTS(SELECT 1 FROM pg_catalog.aclexplode("
                    "COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee<>p.proowner)"
                )
            )
            == 5
        )
