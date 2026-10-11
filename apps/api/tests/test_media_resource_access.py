from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from company_admission_fixture import company_authority_tables, seed_company_app_access
from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.pms.space_models import Team, TeamMember
from miy_api.domains.docs.models import NativeDocGroupShare
from miy_api.domains.pms.space_models import SpaceGroupBinding
from miy_api.domains.docs.models import (
    DocMeetingAccess,
    DocsCollection,
    NativeDoc,
    NativeDocTarget,
    NativeDocPage,
    NativeDocUserShare,
)
from miy_api.domains.community.models import (
    CommunityChannel,
    CommunityComment,
    CommunityPost,
)
from miy_api.domains.media.models import MediaFile
from miy_api.domains.media.resource_access import (
    can_resolve_media,
)
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.pms.models import Folder, Milestone, Task, TaskList, TaskUserAccess


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            *company_authority_tables(),
            Team.__table__,
            TeamMember.__table__,
            Folder.__table__,
            TaskList.__table__,
            Milestone.__table__,
            Task.__table__,
            TaskUserAccess.__table__,
            DocsCollection.__table__,
            NativeDoc.__table__,
            NativeDocGroupShare.__table__,
            SpaceGroupBinding.__table__,
            NativeDocPage.__table__,
            NativeDocTarget.__table__,
            NativeDocUserShare.__table__,
            Meeting.__table__,
            DocMeetingAccess.__table__,
            CommunityChannel.__table__,
            CommunityPost.__table__,
            CommunityComment.__table__,
            MediaFile.__table__,
        ],
    )
    session = Session(engine)
    seed_company_app_access(session)
    return session


def _user(user_id: str) -> User:
    return User(
        id=user_id,
        login_id=user_id,
        email=f"{user_id}@miy.local",
        full_name=user_id.title(),
        password_hash="hash",
        status="active",
    )


def _media(**overrides: object) -> MediaFile:
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "storage_key": "media/uploader/media-1/fixture.png",
        "filename": "fixture.png",
        "content_type": "image/png",
        "size_bytes": 128,
        "uploaded_by_id": "uploader",
        "resource_type": None,
        "resource_id": None,
    }
    defaults.update(overrides)
    return MediaFile(**defaults)


def test_can_resolve_only_unlinked_media_for_uploader_and_rejects_unknown_sources() -> None:
    uploader = SimpleNamespace(id="uploader")
    outsider = SimpleNamespace(id="outsider")

    assert can_resolve_media(None, uploader, _media()) is True
    assert can_resolve_media(None, outsider, _media()) is False
    assert (
        can_resolve_media(
            None,
            uploader,
            _media(resource_type="legacy_unknown", resource_id="resource-1"),
        )
        is False
    )
    assert (
        can_resolve_media(
            None,
            outsider,
            _media(resource_type="legacy_unknown", resource_id="resource-1"),
        )
        is False
    )
