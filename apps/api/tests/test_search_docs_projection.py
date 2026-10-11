from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.auth.models import User
from miy_api.domains.pms.space_models import Team
from miy_api.domains.docs.models import (
    DocMeetingAccess,
    DocsCollection,
    NativeDoc,
    NativeDocTarget,
    NativeDocLinkShare,
    NativeDocPage,
    NativeDocUserShare,
    NativeDocGroupShare,
)
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.pms.models import Folder, Task, TaskList
from miy_api.domains.retrieval.models import RetrievalPartition


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RuntimeOwnership.__table__,
            User.__table__,
            Team.__table__,
            Folder.__table__,
            TaskList.__table__,
            Task.__table__,
            RetrievalPartition.__table__,
            DocsCollection.__table__,
            NativeDoc.__table__,
            NativeDocPage.__table__,
            NativeDocTarget.__table__,
            NativeDocUserShare.__table__,
            NativeDocGroupShare.__table__,
            NativeDocLinkShare.__table__,
            Meeting.__table__,
            DocMeetingAccess.__table__,
            FileManagerCorpus.__table__,
            FileManagerFile.__table__,
            FileManagerFileSourceMetadata.__table__,
        ],
    )
    session = Session(engine)
    session.add(
        RuntimeOwnership(
            scope="official.suite", active_owner="legacy", generation=1, state="active"
        )
    )
    session.commit()
    return session


def _add_user(session: Session) -> None:
    session.add(
        User(
            id="user-1",
            login_id="docs-owner",
            email="docs-owner@miy.local",
            full_name="Docs Owner",
            password_hash="hash",
            status="active",
        )
    )


def _add_native_doc(session: Session, *, trashed_at: datetime | None = None) -> None:
    created_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC).replace(tzinfo=None)
    session.add(
        NativeDoc(
            id="doc-1",
            owner_id="user-1",
            title="Budget Review",
            source_app="docs",
            source_kind="manual",
            source_ref="source-1",
            created_at=created_at,
            updated_at=created_at,
            trashed_at=trashed_at,
        )
    )
    session.add(
        NativeDocPage(
            id="page-2",
            doc_id="doc-1",
            parent_id=None,
            title="Second Page",
            content_format="block",
            content_blocks=[
                {"type": "paragraph", "content": [{"type": "text", "text": "later content"}]}
            ],
            sort_order=2,
            created_by_id="user-1",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.add(
        NativeDocPage(
            id="page-1",
            doc_id="doc-1",
            parent_id=None,
            title="First Page",
            content_format="block",
            content_blocks=[
                {"type": "paragraph", "content": [{"type": "text", "text": "budget risk"}]}
            ],
            sort_order=1,
            created_by_id="user-1",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.add(
        NativeDocTarget(
            id="target-1",
            doc_id="doc-1",
            target_app="pms",
            target_type="space",
            target_id="team-1",
            is_primary=True,
        )
    )
    session.add(
        NativeDocUserShare(
            id="share-1",
            doc_id="doc-1",
            user_id="user-1",
            access_level="read",
            created_by_id="user-1",
        )
    )
