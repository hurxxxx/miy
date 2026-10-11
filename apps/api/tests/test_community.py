from __future__ import annotations


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import User
from miy_api.domains.auth.security import new_id
from miy_api.domains.community import service
from miy_api.domains.community.models import (
    CommunityChannel,
    CommunityComment,
    CommunityPost,
    CommunityPostRead,
)
from miy_api.domains.dm.models import (
    DmConversation,
    DmConversationParticipant,
    DmMessage,
    DmMessageAttachment,
)
from miy_api.domains.content_access.grants import ContentGrantIssuer
from miy_api.domains.media import content_access as media_content_access
from miy_api.domains.media.models import MediaFile
from miy_api.domains.pms.models import Notification
from dev_accounts import auth_headers, dev_login


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    for table in (
        User.__table__,
        CommunityChannel.__table__,
        CommunityPost.__table__,
        CommunityPostRead.__table__,
        CommunityComment.__table__,
        MediaFile.__table__,
        Notification.__table__,
        DmConversation.__table__,
        DmMessage.__table__,
        DmConversationParticipant.__table__,
        DmMessageAttachment.__table__,
    ):
        table.create(engine, checkfirst=True)
    with Session(engine) as session:
        yield session


def _make_user(db: Session, name: str) -> User:
    user = User(
        id=new_id(),
        login_id=name,
        email=f"{name}@miy.local",
        full_name=name,
        display_name=name,
        password_hash="x",
    )
    db.add(user)
    db.commit()
    return user


def _content_grant_issuer(user: User) -> ContentGrantIssuer:
    return ContentGrantIssuer(user_id=user.id, session_id="test-session")


def _create_community_post(
    client: TestClient,
    *,
    token: str,
    title: str,
    body: str,
) -> dict:
    response = client.post(
        f"/api/v1/community/channels/{service.DEFAULT_CHANNEL_KEY}/posts",
        headers=auth_headers(token),
        json={
            "title": title,
            "body": body,
            "is_anonymous": False,
            "is_secret": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_admin_channel(
    client: TestClient,
    *,
    token: str,
    key: str,
    name: str,
    read_only: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/community/admin/channels",
        headers=auth_headers(token),
        json={
            "key": key,
            "name": name,
            "description": "",
            "position": 1,
            "active": True,
            "readOnly": read_only,
            "forceAnonymous": False,
            "adminOnlyContent": False,
            "templateTitle": "",
            "templateBody": "",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _channel(db: Session) -> CommunityChannel:
    return service.get_channel_by_key(db, service.DEFAULT_CHANNEL_KEY)


def _media(db: Session, *, media_id: str, user: User) -> MediaFile:
    media = MediaFile(
        id=media_id,
        storage_key=f"media/{user.id}/{media_id}/screenshot.png",
        filename="screenshot.png",
        content_type="image/png",
        size_bytes=128,
        uploaded_by_id=user.id,
    )
    db.add(media)
    db.commit()
    return media


def test_default_channel_and_posts_are_company_scoped(db: Session) -> None:
    author = _make_user(db, "author")
    channel = _channel(db)

    service.create_post(
        db,
        channel=channel,
        author=author,
        title="건의합니다",
        body="첫 회사 게시글 내용",
        is_anonymous=False,
        is_secret=False,
        password=None,
    )

    channels = service.list_channels(db)
    assert [item.key for item in channels.channels] == ["suggestions"]

    page = service.list_posts(
        db,
        channel=channel,
        viewer_id=author.id,
        viewer_is_admin=False,
    )

    assert page.total == 1
    assert page.posts[0].title == "건의합니다"


def test_read_only_channel_disables_regular_author_modifications(
    client: TestClient,
) -> None:
    admin = dev_login(client, "administrator")
    member = dev_login(client, "delivery-hub-member")
    _create_admin_channel(
        client,
        token=admin["token"],
        key="read-only-edits",
        name="Read Only Edits",
        read_only=True,
    )

    with get_session_factory()() as db:
        channel = service.get_channel_by_key(db, "read-only-edits")
        author = db.get(User, member["user"]["id"])
        assert channel is not None
        assert author is not None
        post = service.create_post(
            db,
            channel=channel,
            author=author,
            title="기존 글",
            body="읽기 전용 전환 전 글",
            is_anonymous=False,
            is_secret=False,
            password=None,
        )
        stored_post = db.get(CommunityPost, post.id)
        assert stored_post is not None
        comment = service.create_comment(
            db,
            post=stored_post,
            author=author,
            body="기존 댓글",
            is_anonymous=False,
        )

    detail = client.get(
        f"/api/v1/community/posts/{post.id}",
        headers=auth_headers(member["token"]),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["canModify"] is False
    assert detail.json()["comments"][0]["canModify"] is False

    post_update = client.patch(
        f"/api/v1/community/posts/{post.id}",
        headers=auth_headers(member["token"]),
        json={"title": "수정", "body": "수정"},
    )
    assert post_update.status_code == 403, post_update.text

    comment_update = client.patch(
        f"/api/v1/community/posts/{post.id}/comments/{comment.id}",
        headers=auth_headers(member["token"]),
        json={"body": "수정 댓글"},
    )
    assert comment_update.status_code == 403, comment_update.text

    comment_delete = client.delete(
        f"/api/v1/community/posts/{post.id}/comments/{comment.id}",
        headers=auth_headers(member["token"]),
    )
    assert comment_delete.status_code == 403, comment_delete.text

    post_delete = client.delete(
        f"/api/v1/community/posts/{post.id}",
        headers=auth_headers(member["token"]),
    )
    assert post_delete.status_code == 403, post_delete.text


def test_secret_post_is_masked_until_author_admin_or_password_unlock(
    db: Session,
) -> None:
    author = _make_user(db, "author")
    other = _make_user(db, "other")
    channel = _channel(db)

    created = service.create_post(
        db,
        channel=channel,
        author=author,
        title="비밀 제안",
        body="민감한 내용",
        is_anonymous=False,
        is_secret=True,
        password="secret-pw",
    )
    assert created.locked is False

    page = service.list_posts(
        db,
        channel=channel,
        viewer_id=other.id,
        viewer_is_admin=False,
    )
    masked = page.posts[0]
    assert masked.locked is True
    assert masked.title == ""
    assert masked.body == ""

    locked = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=False,
        viewer_id=other.id,
        viewer_is_admin=False,
    )
    assert locked is not None
    assert locked.locked is True
    assert locked.comments == []

    stored = db.get(CommunityPost, created.id)
    assert service.verify_post_password(stored, "nope") is False
    assert service.verify_post_password(stored, "secret-pw") is True

    author_detail = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=True,
        viewer_id=author.id,
        viewer_is_admin=False,
    )
    assert author_detail is not None
    assert author_detail.body == "민감한 내용"


def test_force_anonymous_channel_masks_names_except_for_admin(db: Session) -> None:
    author = _make_user(db, "author")
    commenter = _make_user(db, "commenter")
    service.create_channel(
        db,
        key="whistleblowing",
        name="Whistleblowing",
        description="",
        position=1,
        active=True,
        force_anonymous=True,
    )
    channel = service.get_channel_by_key(db, "whistleblowing")

    created = service.create_post(
        db,
        channel=channel,
        author=author,
        title="익명 제보",
        body="본문",
        is_anonymous=False,
        is_secret=False,
        password=None,
    )
    stored_post = db.get(CommunityPost, created.id)
    service.create_comment(
        db,
        post=stored_post,
        author=commenter,
        body="댓글",
        is_anonymous=False,
    )

    regular_page = service.list_posts(
        db,
        channel=channel,
        viewer_id=commenter.id,
        viewer_is_admin=False,
    )
    regular_post = regular_page.posts[0]
    assert regular_post.is_anonymous is True
    assert regular_post.author_name is None

    admin_page = service.list_posts(
        db,
        channel=channel,
        viewer_id=commenter.id,
        viewer_is_admin=True,
    )
    assert admin_page.posts[0].is_anonymous is True
    assert admin_page.posts[0].author_name == "author"

    regular_detail = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=True,
        viewer_id=commenter.id,
        viewer_is_admin=False,
    )
    assert regular_detail is not None
    assert regular_detail.comments[0].is_anonymous is True
    assert regular_detail.comments[0].author_name is None
    assert regular_detail.comments[0].anon_seq == 1

    admin_detail = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=True,
        viewer_id=commenter.id,
        viewer_is_admin=True,
    )
    assert admin_detail is not None
    assert admin_detail.author_name == "author"
    assert admin_detail.comments[0].author_name == "commenter"


def test_admin_only_channel_masks_content_and_media_for_regular_viewers(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        media_content_access,
        "media_owner_app_enabled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        media_content_access,
        "can_resolve_media",
        lambda *_args, **_kwargs: True,
    )
    author = _make_user(db, "author")
    reader = _make_user(db, "reader")
    service.create_channel(
        db,
        key="private-report",
        name="Private Report",
        description="",
        position=1,
        active=True,
        admin_only_content=True,
    )
    channel = service.get_channel_by_key(db, "private-report")
    media_id = "00000000-0000-0000-0000-000000000004"
    _media(db, media_id=media_id, user=author)

    created = service.create_post(
        db,
        channel=channel,
        author=author,
        title="비공개 제보",
        body=f"관리자 확인 필요\n\n![첨부](media:{media_id})",
        is_anonymous=False,
        is_secret=True,
        password=None,
    )
    assert created.locked is True
    assert created.locked_reason == service.LOCKED_REASON_ADMIN_ONLY
    assert created.author_name is None
    stored_post = db.get(CommunityPost, created.id)
    assert stored_post.is_secret is False

    regular_page = service.list_posts(
        db,
        channel=channel,
        viewer_id=reader.id,
        viewer_is_admin=False,
    )
    masked = regular_page.posts[0]
    assert masked.locked is True
    assert masked.locked_reason == service.LOCKED_REASON_ADMIN_ONLY
    assert masked.title == ""
    assert masked.body == ""
    assert masked.author_name is None
    regular_search = service.list_posts(
        db,
        channel=channel,
        viewer_id=reader.id,
        viewer_is_admin=False,
        search="제보",
    )
    assert regular_search.total == 0
    admin_search = service.list_posts(
        db,
        channel=channel,
        viewer_id=reader.id,
        viewer_is_admin=True,
        search="제보",
    )
    assert admin_search.total == 1 and admin_search.posts[0].id == created.id

    regular_detail = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=True,
        viewer_id=author.id,
        viewer_is_admin=False,
    )
    assert regular_detail is not None
    assert regular_detail.locked is True
    assert regular_detail.title == ""
    assert regular_detail.author_name is None
    assert regular_detail.comments == []

    with pytest.raises(service.CommunityMediaAccessDeniedError):
        service.resolve_post_media_urls(
            db,
            post=stored_post,
            urls=[f"media:{media_id}"],
            viewer=reader,
            viewer_is_admin=False,
            content_grant_issuer=_content_grant_issuer(reader),
        )

    admin_detail = service.get_post_detail(
        db,
        post_id=created.id,
        unlocked=True,
        viewer_id=reader.id,
        viewer_is_admin=True,
    )
    assert admin_detail is not None
    assert admin_detail.locked is False
    assert admin_detail.title == "비공개 제보"
    assert admin_detail.author_name == "author"

    resolved = service.resolve_post_media_urls(
        db,
        post=stored_post,
        urls=[f"media:{media_id}"],
        viewer=reader,
        viewer_is_admin=True,
        content_grant_issuer=_content_grant_issuer(reader),
    )
    assert f"media:{media_id}" in resolved.resolved


class _StubUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id
