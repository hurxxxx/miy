"""Real source coverage for the canonical Docs app and its PMS link boundary."""

from alembic.script import ScriptDirectory
from dev_accounts import configure_company_app_access
from fastapi import HTTPException
import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import DBAPIError

from miy_api.core.db import Base
from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.security import new_id
from miy_api.domains.docs import models as docs_models
from miy_api.domains.docs.collab import (
    _persist_docs_runtime_state_sync,
    make_page_ref,
    make_room_key,
)
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state
from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
from miy_api.domains.groups.models import Group
from miy_api.domains.official_apps.projection_contracts import WRITER_TRANSPORT_TABLES
from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES, SUITE_SCOPE
from miy_api.domains.rag.contracts import RagSyncOperation
from miy_api.domains.recording.models import RecordingPublication
from miy_api.domains.retrieval.models import RetrievalProjectionEvent, RetrievalProjectionHead
from test_alembic_migrations import _migration_config
from test_docs_collab import _paragraph_blocks
from test_docs_hub import _create_task, _create_task_list, _create_user
from test_official_writer_fence import change, fenced, writer as writer
from test_recording_targets import (
    _complete_recording_result,
    _import_recording,
    _install_fake_recording_storage,
)


@pytest.fixture
def docs_source(client, writer):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(db, app_ids=["docs", "pms"])
    headers = {"Authorization": "Bearer " + admin["token"]}
    response = client.post("/api/v1/docs/items", headers=headers, json={"title": "Fenced source"})
    assert response.status_code == 201
    doc = response.json()
    response = client.get(f"/api/v1/docs/items/{doc['id']}/pages", headers=headers)
    assert response.status_code == 200
    page = response.json()["items"][0]
    return factory, admin, headers, doc, page


def test_current_inventory_includes_every_docs_model_and_matches_frozen_migration():
    import_all_models()
    covered = set(COVERED_SOURCE_TABLES)
    assert len(covered) == 88
    assert {
        table.name for table in Base.metadata.tables.values() if "writer_scope" in table.c
    } == covered | set(WRITER_TRANSPORT_TABLES)
    docs_tables = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.class_.__module__ == docs_models.__name__
    }
    assert len(docs_tables) == 10
    assert docs_tables <= covered

    revision = ScriptDirectory.from_config(_migration_config()).get_revision(
        "official_writer_fence_20261006"
    )
    addition = ScriptDirectory.from_config(_migration_config()).get_revision(
        "official_widget_writer_20261006"
    )
    assert len(revision.module._SOURCES) == 12
    assert set(revision.module._SOURCES) == set(addition.module._EXISTING_SOURCES)
    planner = ScriptDirectory.from_config(_migration_config()).get_revision(
        "official_planner_writer_20261006"
    )
    previous = set(revision.module._SOURCES) | set(addition.module._SOURCES)
    assert previous == set(planner.module._EXISTING_SOURCES)
    dm = ScriptDirectory.from_config(_migration_config()).get_revision(
        "official_dm_writer_20261007"
    )
    assert previous | set(planner.module._SOURCES) == set(dm.module._EXISTING_SOURCES)
    complete = ScriptDirectory.from_config(_migration_config()).get_revision(
        "official_source_writer_20261007"
    )
    assert set(dm.module._EXISTING_SOURCES) | set(dm.module._SOURCES) == set(
        complete.module._EXISTING_SOURCES
    )
    assert len(complete.module._SOURCES) == 69
    assert set(complete.module._EXISTING_SOURCES) | set(complete.module._SOURCES) == covered
    for name in covered:
        column = Base.metadata.tables[name].c.writer_scope
        assert not column.nullable and str(column.server_default.arg) == SUITE_SCOPE
        assert {fk.target_fullname for fk in column.foreign_keys} == {
            "official_runtime_ownership.scope"
        }
        assert {constraint.name for constraint in column.constraints} == {f"ck_{name}_writer_scope"}


def test_installed_trigger_event_coverage_and_fixed_source_control_contract(writer):
    factory, _, _ = writer
    with factory() as db:
        rows = db.execute(
            text("""
            SELECT c.relname, t.tgtype, t.tgenabled, p.proname, p.prosecdef,
                   encode(t.tgargs, 'escape')
            FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE n.nspname = 'public' AND t.tgname = 'miy_official_source_writer'
        """)
        ).all()
    assert {row[0] for row in rows} == set((*COVERED_SOURCE_TABLES, *WRITER_TRANSPORT_TABLES))
    for row in rows:
        assert tuple(row[1:]) == (
            62,
            "O",
            "miy_guard_official_source_writer",
            False,
            SUITE_SCOPE + r"\000",
        )  # Statement BEFORE INSERT/DELETE/UPDATE/TRUNCATE, invoker authority.
    inspector = inspect(factory.kw["bind"])
    for table in COVERED_SOURCE_TABLES:
        column = next(c for c in inspector.get_columns(table) if c["name"] == "writer_scope")
        assert not column["nullable"] and SUITE_SCOPE in column["default"]
        assert any(
            fk["constrained_columns"] == ["writer_scope"]
            and fk["referred_table"] == "official_runtime_ownership"
            for fk in inspector.get_foreign_keys(table)
        )
        assert any(
            c["name"] == f"ck_{table}_writer_scope" and SUITE_SCOPE in c["sqltext"]
            for c in inspector.get_check_constraints(table)
        )


def test_all_covered_sources_reject_actual_direct_insert_update_delete_in_drain(writer):
    factory, admin, _ = writer
    with factory.begin() as db:
        change(db, admin)
    for table in COVERED_SOURCE_TABLES:
        # Trusted test inventory identifiers, never request-controlled SQL.
        for sql in (
            f"INSERT INTO {table} DEFAULT VALUES",
            f"UPDATE {table} SET writer_scope = writer_scope WHERE false",
            f"DELETE FROM {table} WHERE false",
        ):
            fenced(text(sql), factory)
    fenced(text("TRUNCATE docs_collab_documents"), factory)


def test_parent_foreign_key_cascade_cannot_bypass_docs_share_fence(docs_source):
    factory, admin, _, doc, _ = docs_source
    group_id = new_id()
    with factory.begin() as db:
        db.add(Group(id=group_id, source="local", name="Cascade fixture"))
        db.flush()
        db.add(
            docs_models.NativeDocGroupShare(
                doc_id=doc["source_id"],
                group_id=group_id,
                access_level="read",
                created_by_id=admin["user"]["id"],
            )
        )
    with factory.begin() as db:
        change(db, admin)
    fenced(delete(Group).where(Group.id == group_id), factory)
    with factory() as db:
        assert db.get(Group, group_id) is not None
        assert db.get(docs_models.NativeDocGroupShare, (doc["source_id"], group_id)) is not None


@pytest.mark.parametrize(
    "operation",
    [
        "collection",
        "page",
        "user_share",
        "link",
        "company",
        "favorite",
        "view",
        "collab_session",
        "collab_snapshot",
        "pms_link",
    ],
)
def test_docs_http_write_families_keep_source_state_and_return_503(client, docs_source, operation):
    factory, admin, headers, doc, page = docs_source
    item = f"/api/v1/docs/items/{doc['id']}"
    page_ref = make_page_ref(page["source_type"], page["source_page_id"])
    method, path, body = {
        "collection": ("POST", "/api/v1/docs/collections", {"name": "Blocked", "scope": "private"}),
        "page": ("PATCH", f"/api/v1/docs/pages/{page['id']}", {"title": "Blocked"}),
        "link": ("PUT", item + "/sharing/link", {"access_level": "read"}),
        "company": (
            "PUT",
            item + "/sharing/company",
            {"enabled": True, "company_admin_read_acknowledged": True},
        ),
        "favorite": ("PATCH", item + "/favorite", None),
        "view": ("POST", item + "/view", {}),
        "collab_session": ("GET", f"/api/v1/docs/collab/pages/{page_ref}/session", None),
        "collab_snapshot": (
            "PUT",
            f"/api/v1/docs/collab/pages/{page_ref}/snapshot",
            {"content_blocks": _paragraph_blocks("Blocked")},
        ),
        "user_share": (None, None, None),
        "pms_link": (None, None, None),
    }[operation]
    if operation == "user_share":
        user = _create_user(
            client, admin["token"], email="writer-viewer@example.test", full_name="Viewer"
        )
        method, path, body = (
            "PUT",
            item + f"/sharing/users/{user['user']['id']}",
            {"access_level": "read"},
        )
    if operation == "pms_link":
        task_list = _create_task_list(client, admin["token"], key="FENCE", name="Fence")
        task = _create_task(client, admin["token"], task_list["id"], title="Task")
        method, path, body = "POST", item + "/pms-tasks", {"task_id": task["id"]}
    with factory() as db:
        before = {
            name: db.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
            for name in COVERED_SOURCE_TABLES
        }
    with factory.begin() as db:
        change(db, admin)
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    denied = client.request(method, path, **kwargs)
    assert denied.status_code == 503
    assert denied.json()["code"] == "official_apps.writer_unavailable"
    assert denied.headers["Retry-After"] == "5"
    assert client.get(item, headers=headers).status_code == 200
    with factory() as db:
        assert {
            name: db.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
            for name in COVERED_SOURCE_TABLES
        } == before
        source = db.get(docs_models.NativeDoc, doc["source_id"])
        assert source.title == "Fenced source" and not source.company_visible
        source_page = db.get(docs_models.NativeDocPage, page["source_page_id"])
        assert source_page.title == page["title"] and source_page.content_blocks == []


def test_projection_changes_rollback_with_fenced_source_in_same_transaction(docs_source):
    factory, admin, _, doc, _ = docs_source
    with factory() as db:
        before_events = db.scalar(select(func.count()).select_from(RetrievalProjectionEvent))
        head = db.scalar(
            select(RetrievalProjectionHead).where(
                RetrievalProjectionHead.resource_id == doc["source_id"]
            )
        )
        before_version = head.projection_version
    with factory.begin() as db:
        change(db, admin)
    with factory() as db:
        source = db.get(docs_models.NativeDoc, doc["source_id"])
        source.title = "Must roll back with projection"
        # The owned source intent now checks the writer before creating any
        # Core projection. The previously later source flush cannot be bypassed.
        with pytest.raises(DBAPIError) as denied:
            enqueue_native_doc_rag_sync(db, doc=source, operation=RagSyncOperation.UPSERT)
            db.commit()
        assert denied.value.orig.sqlstate == "55000"
        db.rollback()
    with factory() as db:
        assert db.get(docs_models.NativeDoc, doc["source_id"]).title == "Fenced source"
        assert (
            db.scalar(select(func.count()).select_from(RetrievalProjectionEvent)) == before_events
        )
        assert (
            db.scalar(
                select(RetrievalProjectionHead).where(
                    RetrievalProjectionHead.resource_id == doc["source_id"]
                )
            ).projection_version
            == before_version
        )


def test_background_collaboration_persistence_cannot_bypass_source_fence(docs_source):
    factory, admin, _, doc, page = docs_source
    with factory.begin() as db:
        change(db, admin)
    with pytest.raises(HTTPException) as denied:
        _persist_docs_runtime_state_sync(
            factory,
            source_type=page["source_type"],
            source_page_id=page["source_page_id"],
            room_key=make_room_key(page["source_type"], page["source_page_id"]),
            fallback_actor_user_id=admin["user"]["id"],
            actor_user_id=admin["user"]["id"],
            yjs_state=blocks_to_yjs_state(_paragraph_blocks("Background blocked")),
        )
    assert denied.value.status_code == 503
    assert denied.value.detail.code == "official_apps.writer_unavailable"
    with factory() as db:
        assert db.get(docs_models.NativeDocPage, page["source_page_id"]).content_blocks == []
        assert db.get(docs_models.NativeDoc, doc["source_id"]).title == "Fenced source"
        assert db.scalar(select(func.count()).select_from(docs_models.DocsCollabDocument)) == 0


def test_recording_publication_keeps_same_transaction_and_rolls_back_on_docs_fence(
    client, writer, monkeypatch
):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(db, app_ids=["docs", "recording"])
    _install_fake_recording_storage(monkeypatch)
    recording = _import_recording(client, admin["token"], title="Fenced recording")
    _complete_recording_result(recording["id"])
    with factory.begin() as db:
        before_docs = db.scalar(select(func.count()).select_from(docs_models.NativeDoc))
        before_publications = db.scalar(select(func.count()).select_from(RecordingPublication))
        change(db, admin)
    response = client.post(
        f"/api/v1/recording/recordings/{recording['id']}/publications/docs",
        headers={"Authorization": "Bearer " + admin["token"]},
    )
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(docs_models.NativeDoc)) == before_docs
        assert (
            db.scalar(select(func.count()).select_from(RecordingPublication)) == before_publications
        )
