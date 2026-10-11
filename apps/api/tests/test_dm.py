from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from dev_accounts import auth_headers, create_company_user_session, dev_login


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_dm_spoofed_image_attachment_is_not_previewable(
    client: TestClient,
    in_memory_object_storage: None,
) -> None:
    sender = dev_login(client, "administrator")
    recipient = dev_login(client, "delivery-hub-member")

    create_response = client.post(
        "/api/v1/dm/conversations",
        headers=auth_headers(sender["token"]),
        json={"recipient_user_id": recipient["user"]["id"]},
    )
    assert create_response.status_code == 201, create_response.text
    conversation_id = create_response.json()["id"]

    upload_response = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/attachments",
        headers=auth_headers(sender["token"]),
        files={"file": ("spoof.png", b"not really an image", "image/png")},
    )
    assert upload_response.status_code == 201, upload_response.text
    attachment = upload_response.json()
    assert attachment["content_type"] == "application/octet-stream"
    assert attachment["is_image"] is False
    assert "preview_url" not in attachment
    assert "download_url" not in attachment

    preview_response = client.get(
        f"/api/v1/dm/attachments/{attachment['id']}/preview",
        headers=auth_headers(sender["token"]),
    )
    assert preview_response.status_code == 415, preview_response.text


def test_group_dm_management_tracks_membership_lifecycle(client: TestClient) -> None:
    owner = dev_login(client, "administrator")
    member = dev_login(client, "delivery-hub-member")
    removable = dev_login(client, "delivery-hub-admin")
    added = create_company_user_session(
        client,
        login_id="dmadded",
        email="dm-added@miy.local",
        full_name="DM Added",
    )
    member_added = create_company_user_session(
        client,
        login_id="dmmemberadded",
        email="dm-member-added@miy.local",
        full_name="DM Member Added",
    )

    create_response = client.post(
        "/api/v1/dm/conversations",
        headers=auth_headers(owner["token"]),
        json={
            "title": "Original Room",
            "participant_user_ids": [member["user"]["id"], removable["user"]["id"]],
        },
    )
    assert create_response.status_code == 201, create_response.text
    conversation_id = create_response.json()["id"]

    update_response = client.patch(
        f"/api/v1/dm/conversations/{conversation_id}",
        headers=auth_headers(owner["token"]),
        json={"title": "Updated Room"},
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["title"] == "Updated Room"

    member_update_response = client.patch(
        f"/api/v1/dm/conversations/{conversation_id}",
        headers=auth_headers(member["token"]),
        json={"title": "Member Rename"},
    )
    assert member_update_response.status_code == 403, member_update_response.text

    send_response = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/messages",
        headers=auth_headers(owner["token"]),
        json={"body": "Before add"},
    )
    assert send_response.status_code == 200, send_response.text
    first_message_id = send_response.json()["id"]

    foreign_thread = client.post(
        "/api/v1/dm/conversations",
        headers=auth_headers(owner["token"]),
        json={"recipient_user_id": added["user"]["id"]},
    )
    assert foreign_thread.status_code == 201, foreign_thread.text
    foreign_message = client.post(
        f"/api/v1/dm/conversations/{foreign_thread.json()['id']}/messages",
        headers=auth_headers(owner["token"]),
        json={"body": "Other thread"},
    )
    assert foreign_message.status_code == 200, foreign_message.text
    denied_reply = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/messages",
        headers=auth_headers(owner["token"]),
        json={"body": "Wrong thread reply", "reply_to_message_id": foreign_message.json()["id"]},
    )
    assert denied_reply.status_code == 404

    add_response = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/participants",
        headers=auth_headers(owner["token"]),
        json={"user_ids": [added["user"]["id"]]},
    )
    assert add_response.status_code == 200, add_response.text
    added_snapshot = add_response.json()
    assert added_snapshot["participant_count"] == 4
    assert {item["user"]["id"] for item in added_snapshot["participants"]} == {
        owner["user"]["id"],
        member["user"]["id"],
        removable["user"]["id"],
        added["user"]["id"],
    }

    added_conversations_response = client.get(
        "/api/v1/dm/conversations",
        headers=auth_headers(added["token"]),
    )
    assert added_conversations_response.status_code == 200, added_conversations_response.text
    added_conversation = added_conversations_response.json()["items"][0]
    assert added_conversation["id"] == conversation_id
    assert added_conversation["unread_count"] == 0
    assert added_conversation["last_read_message_id"] == first_message_id

    reply_response = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/messages",
        headers=auth_headers(owner["token"]),
        json={
            "body": "Reply after add",
            "reply_to_message_id": first_message_id,
        },
    )
    assert reply_response.status_code == 200, reply_response.text
    reply_message = reply_response.json()
    assert reply_message["reply_to"]["id"] == first_message_id

    added_messages_response = client.get(
        f"/api/v1/dm/conversations/{conversation_id}/messages",
        headers=auth_headers(added["token"]),
    )
    assert added_messages_response.status_code == 200, added_messages_response.text
    added_messages = added_messages_response.json()["items"]
    assert [item["id"] for item in added_messages] == [reply_message["id"]]
    assert added_messages[0]["reply_to"] is None

    member_add_response = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/participants",
        headers=auth_headers(member["token"]),
        json={"user_ids": [member_added["user"]["id"]]},
    )
    assert member_add_response.status_code == 200, member_add_response.text
    assert member_add_response.json()["participant_count"] == 5

    remove_response = client.delete(
        f"/api/v1/dm/conversations/{conversation_id}/participants/{removable['user']['id']}",
        headers=auth_headers(owner["token"]),
    )
    assert remove_response.status_code == 200, remove_response.text
    assert remove_response.json()["participant_count"] == 4

    removed_conversations_response = client.get(
        "/api/v1/dm/conversations",
        headers=auth_headers(removable["token"]),
    )
    assert removed_conversations_response.status_code == 200, removed_conversations_response.text
    assert removed_conversations_response.json()["items"] == []

    rejoined = client.post(
        f"/api/v1/dm/conversations/{conversation_id}/participants",
        headers=auth_headers(owner["token"]),
        json={"user_ids": [removable["user"]["id"]]},
    )
    assert rejoined.status_code == 200, rejoined.text
    history = client.get(
        f"/api/v1/dm/conversations/{conversation_id}/messages",
        headers=auth_headers(removable["token"]),
    )
    assert history.status_code == 200 and history.json()["items"] == []
    read = client.patch(
        f"/api/v1/dm/conversations/{conversation_id}/read",
        headers=auth_headers(removable["token"]),
    )
    assert read.status_code == 200, read.text
    assert read.json()["last_read_message_id"] is None

    leave_response = client.delete(
        f"/api/v1/dm/conversations/{conversation_id}/participants/me",
        headers=auth_headers(owner["token"]),
    )
    assert leave_response.status_code == 204, leave_response.text

    member_conversations_response = client.get(
        "/api/v1/dm/conversations",
        headers=auth_headers(member["token"]),
    )
    assert member_conversations_response.status_code == 200, member_conversations_response.text
    member_conversation = member_conversations_response.json()["items"][0]
    assert member_conversation["participant_count"] == 4
    assert any(
        item["user"]["id"] == member["user"]["id"] and item["role"] == "owner"
        for item in member_conversation["participants"]
    )
