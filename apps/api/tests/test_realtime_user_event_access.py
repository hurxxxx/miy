from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from starlette.websockets import WebSocketDisconnect

from dev_accounts import auth_headers, dev_login
from miy_api.core.db import get_session_factory
from miy_api.core.realtime import InProcessAppRealtimeHub, realtime_user_topic
from miy_api.domains.community.models import CommunityPost
from miy_api.domains.dm.models import DmMessage
from miy_api.domains.pms.models import Notification
from miy_api.domains.realtime import router
from test_notifications import _create_notification


def _deliver_queued(event, recipient):
    async def exercise():
        hub = InProcessAppRealtimeHub(instance_id="queued-user-event")
        await hub.startup()
        outbound = asyncio.Queue()
        subscription = router._subscribe_topic(
            hub, realtime_user_topic(recipient["user"]["id"]), outbound
        )
        outbound.put_nowait(router.OutboundEvent(event, subscription))
        outbound.put_nowait(router.OutboundEvent({"type": "test.barrier", "data": {}}))

        class Probe:
            headers = {}
            sent = []

            async def send_json(self, item):
                if item["type"] == "test.barrier":
                    raise WebSocketDisconnect()
                self.sent.append(item)

        probe = Probe()
        try:
            with pytest.raises(WebSocketDisconnect):
                await asyncio.wait_for(
                    router._send_outbound_events(
                        probe,
                        outbound,
                        hub=hub,
                        subscriptions={},
                        token=recipient["token"],
                        user_id=recipient["user"]["id"],
                    ),
                    timeout=3,
                )
            return probe.sent
        finally:
            router._unsubscribe_topic(hub, subscription)
            await hub.shutdown()

    return asyncio.run(exercise())


def test_queued_dm_content_follows_current_membership_and_rejoin_history(client, monkeypatch):
    owner = dev_login(client, "administrator")
    reader = dev_login(client, "delivery-hub-member")
    outside = dev_login(client, "delivery-hub-admin")
    teammate = dev_login(client, "knowledge-base-admin")
    captured = []
    monkeypatch.setattr(
        client.app.state.app_realtime,
        "publish_user",
        lambda user_id, event: captured.append((user_id, event)),
    )
    created = client.post(
        "/api/v1/dm/conversations",
        headers=auth_headers(owner["token"]),
        json={
            "title": "Private group",
            "participant_user_ids": [reader["user"]["id"], teammate["user"]["id"]],
        },
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    url = f"/api/v1/dm/conversations/{conversation_id}"
    response = client.post(
        url + "/messages",
        headers=auth_headers(owner["token"]),
        json={"body": "old private history"},
    )
    assert response.status_code == 200
    old_message_id = response.json()["id"]
    event = next(
        event
        for user_id, event in reversed(captured)
        if user_id == reader["user"]["id"] and event["type"] == "dm.message.created"
    )
    with get_session_factory()() as db:
        db.get(DmMessage, old_message_id).body = "current canonical content"
        db.commit()
    current = _deliver_queued(deepcopy(event), reader)
    assert len(current) == 1
    assert current[0]["data"]["message"]["body"] == "current canonical content"
    assert "old private history" not in str(current)
    removed_event = {
        "type": "dm.conversation.removed",
        "data": {"conversation_id": conversation_id},
    }
    assert _deliver_queued(deepcopy(event), outside) == [removed_event]

    removed = client.delete(
        url + f"/participants/{reader['user']['id']}", headers=auth_headers(owner["token"])
    )
    assert removed.status_code == 200
    assert _deliver_queued(deepcopy(event), reader) == [removed_event]
    joined = client.post(
        url + "/participants",
        headers=auth_headers(owner["token"]),
        json={"user_ids": [reader["user"]["id"]]},
    )
    assert joined.status_code == 200
    previous = _deliver_queued(deepcopy(event), reader)
    assert len(previous) == 1 and previous[0]["type"] == "dm.conversation.updated"
    assert "message" not in previous[0]["data"]
    assert previous[0]["data"]["conversation"]["last_message"] is None
    assert "current canonical content" not in str(previous)
    reply = client.post(
        url + "/messages",
        headers=auth_headers(owner["token"]),
        json={"body": "new visible reply", "reply_to_message_id": old_message_id},
    )
    assert reply.status_code == 200
    new_event = deepcopy(
        next(
            event
            for user_id, event in reversed(captured)
            if user_id == reader["user"]["id"] and event["type"] == "dm.message.created"
        )
    )
    new_event["data"]["message"]["reply_to"] = {"body_preview": "current canonical content"}
    visible = _deliver_queued(new_event, reader)
    assert len(visible) == 1
    assert visible[0]["data"]["message"]["body"] == "new visible reply"
    assert visible[0]["data"]["message"]["reply_to"] is None
    assert "current canonical content" not in str(visible)


def test_queued_notification_rechecks_recipient_then_read_state_and_source_revocation(client):
    recipient = dev_login(client, "delivery-hub-member")
    commenter = dev_login(client, "administrator")
    notification_id = _create_notification(
        client,
        author_token=recipient["token"],
        commenter_token=commenter["token"],
        title="Source private notification",
    )
    event = {
        "type": "notification.created",
        "data": {
            "notification": {
                "id": notification_id,
                "title": "stale private notification",
                "body": "stale body",
            },
            "unread_count": 999,
        },
    }
    current = _deliver_queued(deepcopy(event), recipient)
    assert len(current) == 1
    assert current[0]["data"]["notification"]["id"] == notification_id
    assert current[0]["data"]["notification"]["is_read"] is False
    assert current[0]["data"]["unread_count"] == 1
    assert "stale private notification" not in str(current) and "stale body" not in str(current)
    other = _deliver_queued(deepcopy(event), commenter)
    assert len(other) == 1 and other[0]["data"] == {"notification": None, "unread_count": 0}
    with get_session_factory()() as db:
        db.get(Notification, notification_id).is_read = True
        db.commit()
    read = _deliver_queued(deepcopy(event), recipient)
    assert len(read) == 1 and read[0]["data"]["notification"]["is_read"] is True
    assert read[0]["data"]["unread_count"] == 0
    with get_session_factory()() as db:
        notification = db.get(Notification, notification_id)
        notification.is_read = False
        db.get(CommunityPost, notification.source_id).channel.admin_only_content = True
        db.commit()
    revoked = _deliver_queued(deepcopy(event), recipient)
    assert len(revoked) == 1 and revoked[0]["data"] == {"notification": None, "unread_count": 0}
