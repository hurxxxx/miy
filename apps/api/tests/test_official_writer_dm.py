"""DM's four source tables and accepted attachment transaction share one writer."""

from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_fence import writer as writer
from test_official_writer_roles import (
    role_template as role_template,
)
from test_official_writer_roles import (
    sa_dsn,
)
from test_official_writer_roles import (
    world as world,
)

from alembic import command
from miy_api.domains.auth.models import AuthSession, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.dm import attachment_persistence, attachment_storage
from miy_api.domains.dm import router as dm_router
from miy_api.domains.dm.models import (
    DmConversation,
    DmConversationParticipant,
    DmMessage,
    DmMessageAttachment,
)

MODELS = (DmConversation, DmConversationParticipant, DmMessage, DmMessageAttachment)
SOURCES = tuple(model.__tablename__ for model in MODELS)
REVISION = "official_dm_writer_20261007"
PREVIOUS = "registration_auth_20261007"
OLD_SOURCES = tuple(
    ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module._EXISTING_SOURCES
)


class Objects:
    def __init__(self):
        self.values = {}
        self.puts = []
        self.removes = []

    def put(self, *, storage_key, content, size_bytes, content_type):
        self.values[storage_key] = content.read()
        self.puts.append(storage_key)

    def remove(self, *, storage_key):
        self.removes.append(storage_key)
        self.values.pop(storage_key, None)


def snapshot(factory):
    with factory() as db:
        return {
            model.__tablename__: sorted(
                [tuple(row) for row in db.execute(select(model.__table__))], key=repr
            )
            for model in MODELS
        }


@pytest.fixture
def dm(client, writer, monkeypatch):
    factory, admin, _ = writer
    peers = []
    with factory.begin() as db:
        for index in range(3):
            user_id, token = str(uuid4()), "dm-fixture-" + uuid4().hex
            db.add(
                User(
                    id=user_id,
                    login_id=user_id,
                    email=f"{user_id}@example.test",
                    full_name=f"Peer {index}",
                    password_hash="synthetic",
                )
            )
            db.flush()
            db.add(
                AuthSession(
                    id=str(uuid4()),
                    user_id=user_id,
                    token_hash=hash_token(token),
                    expires_at=utcnow_naive() + timedelta(hours=1),
                )
            )
            peers.append({"id": user_id, "headers": {"Authorization": "Bearer " + token}})
    headers = {"Authorization": "Bearer " + admin["token"]}
    events, objects = Mock(), Objects()
    monkeypatch.setattr(dm_router, "_dm_events", lambda *args: events)
    monkeypatch.setattr(attachment_storage, "dm_attachment_storage", lambda: objects)
    response = client.post(
        "/api/v1/dm/conversations",
        headers=headers,
        json={"participant_user_ids": [p["id"] for p in peers[:2]], "title": "Original"},
    )
    assert response.status_code == 201, response.text
    base = "/api/v1/dm/conversations/" + response.json()["id"]
    message = client.post(
        base + "/messages", headers=peers[0]["headers"], json={"body": "Original message"}
    )
    assert message.status_code == 200, message.text
    attachment = client.post(
        base + "/attachments",
        headers=headers,
        files={"file": ("synthetic.txt", b"synthetic", "text/plain")},
    )
    assert attachment.status_code == 201, attachment.text
    events.reset_mock()
    return SimpleNamespace(
        factory=factory,
        admin=admin,
        headers=headers,
        peers=peers,
        base=base,
        attachment=attachment.json(),
        events=events,
        objects=objects,
    )


def seed(conn, user_id):
    conn.execute(
        "INSERT INTO dm_conversations(id,conversation_type,title,created_by_id,message_seq,created_at,updated_at) VALUES ('dm-conversation','group','Original',%s,1,now(),now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_conversation_participants(id,conversation_id,user_id,role,joined_at,created_at) VALUES ('dm-member','dm-conversation',%s,'owner',now(),now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_messages(id,conversation_id,sequence,sender_id,body,created_at) VALUES ('dm-message','dm-conversation',1,%s,'Original message',now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO dm_message_attachments(id,conversation_id,message_id,uploader_id,filename,content_type,size_bytes,storage_key,created_at) VALUES ('dm-attachment','dm-conversation','dm-message',%s,'Original.txt','text/plain',9,'dm/synthetic/original',now())",
        [user_id],
    )
    conn.execute("UPDATE dm_conversation_participants SET last_read_message_id='dm-message'")


def contents(conn):
    return {
        table: conn.execute(
            f"SELECT to_jsonb(row)-'writer_scope' FROM {table} row ORDER BY id"
        ).fetchall()
        for table in SOURCES
    }


def old_schema(world):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)


def assert_revision(world, revision, *, fenced):
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
    for table in SOURCES:
        assert (
            "writer_scope" in {c["name"] for c in inspect(world.engine).get_columns(table)}
        ) is fenced


@pytest.mark.parametrize("accepted", [False, True])
def test_dm_attachment_commit_response_loss_preserves_committed_object(world, accepted):
    with world.connect() as conn:
        seed(conn, world.user_id)
    objects = Objects()
    with Session(world.engine) as db:
        actual_commit = db.commit

        def lose_commit_response():
            if accepted:
                actual_commit()
            raise OSError("synthetic commit response lost")

        db.commit = lose_commit_response
        row = DmMessageAttachment(
            id="accepted-attachment",
            conversation_id="dm-conversation",
            uploader_id=world.user_id,
            filename="accepted.txt",
            content_type="text/plain",
            size_bytes=8,
            storage_key="dm/synthetic/accepted",
        )
        with pytest.raises(HTTPException) as error:
            attachment_persistence.persist_created_attachment(
                db,
                row=row,
                object_write=attachment_persistence.DmAttachmentObjectWrite(
                    storage_key=row.storage_key,
                    content=BytesIO(b"accepted"),
                    size_bytes=8,
                    content_type="text/plain",
                ),
                object_storage=objects,
            )
        assert error.value.status_code == 500
        assert error.value.detail.code == "dm.attachment_save_unknown"
        assert error.value.__cause__ is None and error.value.__suppress_context__
    with world.connect() as conn:
        stored = conn.execute(
            "SELECT storage_key FROM dm_message_attachments WHERE id='accepted-attachment'"
        ).fetchone()
        assert stored == (("dm/synthetic/accepted",) if accepted else None)
    assert objects.removes == []
    assert objects.values == {"dm/synthetic/accepted": b"accepted"}
