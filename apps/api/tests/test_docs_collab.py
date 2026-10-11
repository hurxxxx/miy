from __future__ import annotations

import asyncio
import base64

from fastapi.testclient import TestClient
import pytest
import y_py as Y

from dev_accounts import content_headers
from miy_api.domains.docs.collab import (
    CollabPageContext,
    DocsCollabHub,
    RedisCollabBus,
    make_page_ref,
    make_room_key,
    materialize_collab_room_state,
)
from miy_api.domains.collaboration import CollabConnectionLimitExceeded
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state, yjs_state_to_blocks
from miy_api.domains.auth.security import new_id
from miy_api.domains.media import content_access as media_content_access
from miy_api.domains.media.models import MediaFile
from miy_api.domains.media.object_storage import MediaObjectStorage
from miy_api.core.db import get_session_factory
from test_docs_hub import (
    _add_task_list_member,
    _auth_headers,
    _create_doc_page,
    _create_space_doc,
    _create_task_list,
)
from test_meeting import _bootstrap_admin_session, _create_meeting, _create_company_user, _login


def _paragraph_blocks(text: str) -> list[dict]:
    return [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }
    ]


def _encode_test_yjs_state(text: str) -> str:
    doc = Y.YDoc()
    with doc.begin_transaction() as txn:
        doc.get_text("prosemirror").extend(txn, text)
    return base64.b64encode(Y.encode_state_as_update(doc)).decode("ascii")


def _create_unlinked_media(uploaded_by_id: str) -> dict[str, str]:
    media_id = new_id()
    db = get_session_factory()()
    try:
        db.add(
            MediaFile(
                id=media_id,
                storage_key=f"media/{uploaded_by_id}/{media_id}/fixture.png",
                filename="fixture.png",
                content_type="image/png",
                size_bytes=128,
                uploaded_by_id=uploaded_by_id,
            )
        )
        db.commit()
    finally:
        db.close()

    return {"id": media_id}


def _resolve_media_url(client: TestClient, token: str, media_id: str) -> str:
    resolve_response = client.post(
        "/api/v1/media/resolve",
        headers=_auth_headers(token),
        json={"urls": [f"media:{media_id}"]},
    )
    assert resolve_response.status_code == 200, resolve_response.text
    return resolve_response.json()["resolved"][f"media:{media_id}"]


def _create_native_doc_page(
    client: TestClient,
    token: str,
) -> tuple[dict, dict]:
    create_doc_response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(token),
        json={"title": "Realtime Notes"},
    )
    assert create_doc_response.status_code == 201, create_doc_response.text
    doc = create_doc_response.json()

    pages_response = client.get(
        f"/api/v1/docs/items/{doc['id']}/pages",
        headers=_auth_headers(token),
    )
    assert pages_response.status_code == 200, pages_response.text
    page = pages_response.json()["items"][0]
    assert page["realtime_collab"] is True
    return doc, page


def test_docs_collab_session_snapshot_and_rest_patch_stay_in_sync(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _bootstrap_admin_session(client)
    doc, page = _create_native_doc_page(
        client,
        admin["token"],
    )

    page_ref = make_page_ref(page["source_type"], page["source_page_id"])
    session_path = f"/api/v1/docs/collab/pages/{page_ref}/session"
    snapshot_path = f"/api/v1/docs/collab/pages/{page_ref}/snapshot"

    legacy_yjs_state = base64.b64decode(
        "AQus6/3kDAAHAQtwcm9zZW1pcnJvcgMKYmxvY2tHcm91cAcArOv95AwAAw5i"
        "bG9ja0NvbnRhaW5lcgcArOv95AwBAwlwYXJhZ3JhcGgHAKzr/eQMAgYGAKzr"
        "/eQMAwRib2xkAnt9hKzr/eQMBCQwLjQ3LjPsl5DshJwg7KCA7J6l7ZWcIO2V"
        "nOq4gCDrrLjshJyGrOv95AwWBGJvbGQEbnVsbCgArOv95AwCD2JhY2tncm91"
        "bmRDb2xvcgF3B2RlZmF1bHQoAKzr/eQMAgl0ZXh0Q29sb3IBdwdkZWZhdWx0"
        "KACs6/3kDAINdGV4dEFsaWdubWVudAF3BGxlZnQoAKzr/eQMAQJpZAF3EGxl"
        "Z2FjeS1wYXJhZ3JhcGgA"
    )

    legacy_blocks = yjs_state_to_blocks(legacy_yjs_state)

    assert legacy_blocks == [
        {
            "id": "legacy-paragraph",
            "type": "paragraph",
            "props": {
                "backgroundColor": "default",
                "textColor": "default",
                "textAlignment": "left",
            },
            "content": [
                {
                    "type": "text",
                    "text": "0.47.3에서 저장한 한글 문서",
                    "styles": {"bold": True},
                }
            ],
            "children": [],
        }
    ]

    saved_legacy = client.put(
        snapshot_path,
        headers=_auth_headers(admin["token"]),
        json={
            "content_blocks": legacy_blocks,
            "yjs_state": base64.b64encode(legacy_yjs_state).decode("ascii"),
        },
    )
    assert saved_legacy.status_code == 200, saved_legacy.text

    initial_session_response = client.get(
        session_path,
        headers=_auth_headers(admin["token"]),
    )
    assert initial_session_response.status_code == 200, initial_session_response.text
    initial_session = initial_session_response.json()
    assert initial_session["page_ref"] == page_ref
    assert initial_session["room_key"] == f"native_doc_page:{page['id']}"
    assert initial_session["can_edit"] is True
    assert initial_session["realtime_status"] == "enabled"
    assert initial_session["read_only_reason"] is None
    assert initial_session["snapshot_content_blocks"] == legacy_blocks
    assert isinstance(initial_session["yjs_state"], str)
    assert initial_session["yjs_state"]

    collab_blocks = _paragraph_blocks("Synced from collab")
    yjs_state = _encode_test_yjs_state("Synced from collab")

    snapshot_response = client.put(
        snapshot_path,
        headers=_auth_headers(admin["token"]),
        json={
            "content_blocks": collab_blocks,
            "yjs_state": yjs_state,
        },
    )
    assert snapshot_response.status_code == 200, snapshot_response.text

    refreshed_session_response = client.get(
        session_path,
        headers=_auth_headers(admin["token"]),
    )
    assert refreshed_session_response.status_code == 200, refreshed_session_response.text
    refreshed_session = refreshed_session_response.json()
    assert refreshed_session["snapshot_content_blocks"] == collab_blocks
    assert refreshed_session["yjs_state"] == yjs_state

    page_refresh_response = client.get(
        f"/api/v1/docs/items/{doc['id']}/pages",
        headers=_auth_headers(admin["token"]),
    )
    assert page_refresh_response.status_code == 200, page_refresh_response.text
    refreshed_page = next(
        item for item in page_refresh_response.json()["items"] if item["id"] == page["id"]
    )
    assert refreshed_page["content_blocks"] == collab_blocks

    rest_blocks = _paragraph_blocks("Updated through REST")
    rest_patch_response = client.patch(
        f"/api/v1/docs/pages/{page['id']}",
        headers=_auth_headers(admin["token"]),
        json={"content_blocks": rest_blocks},
    )
    assert rest_patch_response.status_code == 200, rest_patch_response.text

    rest_session_response = client.get(
        session_path,
        headers=_auth_headers(admin["token"]),
    )
    assert rest_session_response.status_code == 200, rest_session_response.text
    rest_session = rest_session_response.json()
    assert rest_session["snapshot_content_blocks"] == rest_blocks
    assert isinstance(rest_session["yjs_state"], str)
    assert rest_session["yjs_state"]

    member = _create_company_user(
        client,
        admin["token"],
        email="docs-media-member@miy.local",
        full_name="Docs Media Member",
    )
    member_token = _login(client, member["user"]["email"], member["temporary_password"])

    share_response = client.put(
        f"/api/v1/docs/items/{doc['id']}/sharing/users/{member['user']['id']}",
        headers=_auth_headers(admin["token"]),
        json={"access_level": "edit"},
    )
    assert share_response.status_code == 200, share_response.text

    media = _create_unlinked_media(admin["user"]["id"])
    link_response = client.post(
        "/api/v1/media/link",
        headers=_auth_headers(admin["token"]),
        json={
            "media_ids": [media["id"]],
            "resource_type": "docs_native_page",
            "resource_id": page["id"],
        },
    )
    assert link_response.status_code == 204, link_response.text

    resolve_response = client.post(
        "/api/v1/media/resolve",
        headers=_auth_headers(member_token),
        json={"urls": [f"media:{media['id']}"]},
    )
    assert resolve_response.status_code == 200, resolve_response.text
    resolved_url = resolve_response.json()["resolved"][f"media:{media['id']}"]
    assert resolved_url.startswith("/api/v1/content#grant=")
    assert "127.0.0.1:59000" not in resolved_url

    class FakeMinioObject:
        def __init__(self) -> None:
            self.closed = False
            self.released = False

        def stream(self, chunk_size: int):
            assert chunk_size > 0
            yield b"\x89PNG\r\n\x1a\npng-bytes"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
            self.released = True

    fake_object = FakeMinioObject()

    class FakeMinioClient:
        def get_object(self, bucket_name: str, storage_key: str) -> FakeMinioObject:
            assert bucket_name
            assert storage_key.endswith("/fixture.png")
            return fake_object

    monkeypatch.setattr(
        media_content_access,
        "media_object_storage",
        lambda: MediaObjectStorage(bucket_name="test-bucket", client=FakeMinioClient()),
    )

    content_response = client.get(
        resolved_url,
        headers=content_headers(member_token, resolved_url),
    )
    assert content_response.status_code == 200, content_response.text
    assert content_response.content == b"\x89PNG\r\n\x1a\npng-bytes"
    assert content_response.headers["content-type"] == "image/png"
    assert fake_object.closed is True
    assert fake_object.released is True


def test_docs_collab_stale_runtime_flush_does_not_overwrite_newer_snapshot(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    doc, page = _create_native_doc_page(
        client,
        admin["token"],
    )

    old_state = blocks_to_yjs_state(_paragraph_blocks("Old runtime state"))
    latest_state = blocks_to_yjs_state(_paragraph_blocks("Latest REST snapshot"))
    assert old_state is not None
    assert latest_state is not None
    latest_blocks = yjs_state_to_blocks(latest_state)
    assert latest_blocks is not None

    page_ref = make_page_ref(page["source_type"], page["source_page_id"])
    snapshot_response = client.put(
        f"/api/v1/docs/collab/pages/{page_ref}/snapshot",
        headers=_auth_headers(admin["token"]),
        json={
            "content_blocks": latest_blocks,
            "yjs_state": base64.b64encode(latest_state).decode("ascii"),
        },
    )
    assert snapshot_response.status_code == 200, snapshot_response.text

    db = get_session_factory()()
    try:
        materialize_collab_room_state(
            db,
            source_type=page["source_type"],
            source_page_id=page["source_page_id"],
            room_key=make_room_key(page["source_type"], page["source_page_id"]),
            yjs_state=old_state,
            actor_user_id=page["created_by_id"],
            fallback_actor_user_id=page["created_by_id"],
        )
        db.commit()
    finally:
        db.close()

    page_refresh_response = client.get(
        f"/api/v1/docs/items/{doc['id']}/pages",
        headers=_auth_headers(admin["token"]),
    )
    assert page_refresh_response.status_code == 200, page_refresh_response.text
    refreshed_page = next(
        item for item in page_refresh_response.json()["items"] if item["id"] == page["id"]
    )
    assert refreshed_page["content_blocks"] == latest_blocks


@pytest.mark.external_integration("redis")
def test_docs_collab_bus_recovers_after_transient_relay_failure(redis_url: str) -> None:
    async def wait_until_available(bus: RedisCollabBus) -> None:
        deadline = asyncio.get_running_loop().time() + 5
        while not bus.available and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        assert bus.available

    async def exercise() -> None:
        bus = RedisCollabBus(redis_url, instance_id="test-docs-collab-bus")
        await bus.startup()
        try:
            await wait_until_available(bus)
            bus.mark_failed()
            assert not bus.available
            await wait_until_available(bus)
        finally:
            await bus.shutdown()

    asyncio.run(exercise())


def test_docs_collab_hub_limits_connection_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        context = CollabPageContext(
            page_ref="native_doc_page__slot-test-page",
            source_type="native_doc_page",
            source_page_id="slot-test-page",
            room_key="native_doc_page:slot-test-page",
            can_edit=True,
            content_blocks=[],
            default_actor_user_id="slot-user",
        )
        hub = DocsCollabHub(instance_id="test-docs-slot-limits")
        monkeypatch.setattr(hub._settings, "collab_max_user_room_connections", 2)
        monkeypatch.setattr(hub._settings, "collab_max_room_clients", 10)
        try:
            runtime = await hub.get_room(context, None)
            await hub.acquire_connection_slot(runtime, "slot-user")
            await hub.acquire_connection_slot(runtime, "slot-user")
            with pytest.raises(CollabConnectionLimitExceeded):
                await hub.acquire_connection_slot(runtime, "slot-user")
            assert runtime.active_connection_count == 2
            assert runtime.active_user_connections == {"slot-user": 2}

            await hub.release_connection_slot(runtime, "slot-user")
            await hub.release_connection_slot(runtime, "slot-user")
            assert runtime.active_connection_count == 0
            assert runtime.active_user_connections == {}

            monkeypatch.setattr(hub._settings, "collab_max_room_clients", 2)
            await hub.acquire_connection_slot(runtime, "slot-user-1")
            await hub.acquire_connection_slot(runtime, "slot-user-2")
            with pytest.raises(CollabConnectionLimitExceeded):
                await hub.acquire_connection_slot(runtime, "slot-user-3")
            assert runtime.active_connection_count == 2
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_meeting_notes_collab_session_is_revoked_when_attendee_is_removed(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    attendee = _create_company_user(
        client,
        admin_token,
        email="notes-collab-attendee@miy.local",
        full_name="Notes Collab Attendee",
    )
    attendee_token = _login(
        client,
        attendee["user"]["email"],
        attendee["temporary_password"],
    )

    meeting = _create_meeting(
        client,
        admin_token,
        title="Realtime notes ACL",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
    )

    ensure_response = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/notes/ensure",
        headers=_auth_headers(admin_token),
    )
    assert ensure_response.status_code == 200, ensure_response.text
    notes = ensure_response.json()
    page_ref = make_page_ref("native_doc_page", notes["notes_page_id"])
    session_path = f"/api/v1/docs/collab/pages/{page_ref}/session"

    attendee_session_response = client.get(
        session_path,
        headers=_auth_headers(attendee_token),
    )
    assert attendee_session_response.status_code == 200, attendee_session_response.text
    assert attendee_session_response.json()["can_edit"] is True

    remove_attendee_response = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin_token),
        json={"attendees": []},
    )
    assert remove_attendee_response.status_code == 200, remove_attendee_response.text

    revoked_session_response = client.get(
        session_path,
        headers=_auth_headers(attendee_token),
    )
    assert revoked_session_response.status_code == 403, revoked_session_response.text


def test_pms_target_doc_collab_session_uses_space_acl_and_page_ref(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    task_list = _create_task_list(client, admin_token, key="CLAB", name="Collab List")

    space_doc = _create_space_doc(client, admin_token, task_list["team_id"], title="Space Handbook")
    page = _create_doc_page(client, admin_token, space_doc["id"], title="Overview")
    assert page["realtime_collab"] is True

    member = _create_company_user(
        client,
        admin_token,
        email="space-collab-member@miy.local",
        full_name="Space Collab Member",
    )
    _add_task_list_member(client, admin_token, task_list["id"], member["user"]["id"], "member")
    member_token = _login(
        client,
        member["user"]["email"],
        member["temporary_password"],
    )

    page_ref = make_page_ref("native_doc_page", page["id"])
    session_response = client.get(
        f"/api/v1/docs/collab/pages/{page_ref}/session",
        headers=_auth_headers(member_token),
    )
    assert session_response.status_code == 200, session_response.text
    payload = session_response.json()
    assert payload["page_ref"] == page_ref
    assert payload["source_type"] == "native_doc_page"
    assert payload["source_page_id"] == page["id"]
    assert payload["room_key"] == f"native_doc_page:{page['id']}"
    assert payload["can_edit"] is True
