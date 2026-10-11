from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from dev_accounts import auth_headers, dev_login
from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import CompanyAppControl
from miy_api.domains.realtime import router
from miy_api.domains.realtime.resource_subscriptions import (
    requested_resource_subscription,
)


def _resource(client, app):
    owner = dev_login(client, "delivery-hub-admin")
    reader = dev_login(client, "delivery-hub-member")
    response = client.post(
        f"/api/v1/{app}/items",
        headers=auth_headers(owner["token"]),
        json={"title": "Private source"},
    )
    assert response.status_code == 201, response.text
    item_id = response.json()["id"]
    link = client.put(
        f"/api/v1/{app}/items/{item_id}/sharing/link",
        headers=auth_headers(owner["token"]),
        json={"access_level": "edit", "active": True},
    )
    assert link.status_code == 200, link.text
    return owner, reader, item_id, link.json()["link_share"]["token"]


def _connect(socket, token):
    socket.send_json({"type": "auth", "token": token})
    assert socket.receive_json()["type"] == "realtime.auth.ok"
    assert socket.receive_json()["type"] == "notification.snapshot"


def _subscribe(socket, app, item_id, share_token):
    socket.send_json(
        {
            "type": "subscribe",
            "topic": f"{app}.pages" if app == "docs" else "whiteboard.access",
            "key": item_id,
            "share_token": share_token,
        }
    )


def _control(app, item_id):
    return {
        "type": f"{app}.access.changed",
        "data": {"doc_id" if app == "docs" else "whiteboard_id": item_id},
    }


def _assert_initial(socket, app, item_id):
    initial = socket.receive_json()
    if app == "docs":
        assert initial["type"] == "docs.pages.snapshot"
        assert initial["data"]["doc_id"] == item_id
    else:
        assert initial == _control(app, item_id)


def test_queued_docs_content_is_redacted_after_revocation_and_stale_envelopes_discarded(client):
    _owner, reader, item_id, link = _resource(client, "docs")
    from miy_api.domains.docs.models import NativeDocLinkShare
    from miy_api.core.realtime import InProcessAppRealtimeHub

    async def exercise():
        hub = InProcessAppRealtimeHub(instance_id="queued-revocation")
        await hub.startup()
        outbound = asyncio.Queue()
        payload = {"topic": "docs.pages", "key": item_id, "share_token": link}
        resource = requested_resource_subscription(payload)
        subscription = router._subscribe_topic(
            hub, resource.channel, outbound, client_payload=payload, resource=resource
        )
        subscriptions = {router._subscription_id(resource.topic, resource.key, link): subscription}
        # Both frames are already queued before the canonical ACL changes.
        for value in ("first secret", "second secret"):
            outbound.put_nowait(
                router.OutboundEvent(
                    {"type": "docs.pages.changed", "data": {"doc_id": item_id, "pages": [value]}},
                    subscription,
                )
            )
        with get_session_factory()() as db:
            stored_link = db.scalar(
                select(NativeDocLinkShare).where(NativeDocLinkShare.token == link)
            )
            stored_link.active = False
            db.commit()

        class Probe:
            headers = {}
            sent = []

            async def send_json(self, event):
                self.sent.append(event)
                if event["type"] == "test.barrier":
                    raise WebSocketDisconnect()

        probe = Probe()
        outbound.put_nowait(router.OutboundEvent({"type": "test.barrier", "data": {}}))
        try:
            with pytest.raises(WebSocketDisconnect):
                await asyncio.wait_for(
                    router._send_outbound_events(
                        probe,
                        outbound,
                        hub=hub,
                        subscriptions=subscriptions,
                        token=reader["token"],
                        user_id=reader["user"]["id"],
                    ),
                    timeout=3,
                )
            assert probe.sent == [_control("docs", item_id), {"type": "test.barrier", "data": {}}]
            assert not subscription.active
            assert not subscriptions
            assert not hub._queues
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_direct_and_shared_link_subscriptions_keep_distinct_authority_and_refcounts(client):
    owner, _reader, item_id, link = _resource(client, "docs")
    from miy_api.core.realtime import InProcessAppRealtimeHub
    from miy_api.domains.docs.models import NativeDocLinkShare

    async def exercise():
        hub = InProcessAppRealtimeHub(instance_id="distinct-link-contexts")
        await hub.startup()
        outbound = asyncio.Queue()
        subscriptions = {}
        direct_payload = {"type": "subscribe", "topic": "docs.pages", "key": item_id}
        link_payload = {**direct_payload, "share_token": link}
        for payload in (direct_payload, link_payload, link_payload):
            await router._handle_subscribe(
                payload,
                hub=hub,
                outbound=outbound,
                subscriptions=subscriptions,
                token=owner["token"],
                user_id=owner["user"]["id"],
            )
        direct_id = router._subscription_id("docs.pages", item_id)
        link_id = router._subscription_id("docs.pages", item_id, link)
        assert len(subscriptions) == 2
        assert subscriptions[direct_id].ref_count == 1
        assert subscriptions[link_id].ref_count == 2
        router._handle_unsubscribe(link_payload, hub=hub, subscriptions=subscriptions)
        assert subscriptions[link_id].ref_count == 1
        assert subscriptions[direct_id].active
        # Discard only initial snapshots; the following frames model a queued
        # content update with separate original authority bindings.
        while not outbound.empty():
            outbound.get_nowait()
        direct = subscriptions[direct_id]
        linked = subscriptions[link_id]
        content = {
            "type": "docs.pages.changed",
            "data": {"doc_id": item_id, "pages": ["owner content"]},
        }
        outbound.put_nowait(router.OutboundEvent(content, direct))
        outbound.put_nowait(router.OutboundEvent(content, linked))
        with get_session_factory()() as db:
            stored = db.scalar(select(NativeDocLinkShare).where(NativeDocLinkShare.token == link))
            stored.active = False
            db.commit()
        outbound.put_nowait(router.OutboundEvent({"type": "test.barrier", "data": {}}))

        class Probe:
            headers = {}
            sent = []

            async def send_json(self, event):
                if event["type"] == "test.barrier":
                    raise WebSocketDisconnect()
                self.sent.append(event)

        probe = Probe()
        try:
            with pytest.raises(WebSocketDisconnect):
                await asyncio.wait_for(
                    router._send_outbound_events(
                        probe,
                        outbound,
                        hub=hub,
                        subscriptions=subscriptions,
                        token=owner["token"],
                        user_id=owner["user"]["id"],
                    ),
                    timeout=3,
                )
            assert probe.sent == [content, _control("docs", item_id)]
            assert link not in str(probe.sent)
            assert list(subscriptions) == [direct_id]
            assert direct.active and not linked.active
            router._handle_unsubscribe(direct_payload, hub=hub, subscriptions=subscriptions)
            assert not subscriptions
        finally:
            router._unsubscribe_topic(hub, direct)
            router._unsubscribe_topic(hub, linked)
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("app", ["docs"])
def test_periodic_resource_recheck_sends_control_and_detaches_if_invalidation_was_lost(
    client, monkeypatch, app
):
    _owner, reader, item_id, link = _resource(client, app)
    monkeypatch.setattr(router, "REALTIME_ACCESS_RECHECK_SECONDS", 0.02)
    with client.websocket_connect("/api/v1/realtime/ws") as socket:
        _connect(socket, reader["token"])
        _subscribe(socket, app, item_id, link)
        _assert_initial(socket, app, item_id)
        with get_session_factory()() as db:
            db.get(CompanyAppControl, app).enabled = False
            db.commit()
        assert socket.receive_json() == _control(app, item_id)
        hub = client.app.state.app_realtime
        hub.publish_user(reader["user"]["id"], {"type": "test.barrier", "data": {}})
        assert socket.receive_json()["type"] == "test.barrier"
        socket.close()


@pytest.mark.parametrize("query", ["token=legacy-query-secret"])
def test_realtime_rejects_query_token_authentication(client, query):
    with client.websocket_connect(f"/api/v1/realtime/ws?{query}") as socket:
        with pytest.raises(WebSocketDisconnect) as denied:
            socket.receive_json()
        assert denied.value.code == 1008
