from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.core.principal import user_principal
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.docs import service as docs_service
from miy_api.domains.docs.models import NativeDocPage
from miy_api.domains.docs.page_mutations import (
    CreateNativePageCommand,
    DeleteNativePageCommand,
    UpdateNativePageCommand,
    create_native_page,
    delete_native_page,
    update_native_page,
)
from dev_accounts import dev_login


def test_create_native_page_module_preserves_approved_call_id_idempotency(
    client: TestClient,
) -> None:
    session = dev_login(client, "delivery-hub-admin")
    with get_session_factory()() as db:
        user = _load_user(db, session["user"]["id"])
        doc, _page = docs_service.create_native_doc_for_user(
            db,
            owner_id=user.id,
            title="Idempotent doc",
        )
        db.commit()
        principal = user_principal(
            user_id=user.id,
            source="test.docs.page_mutations.idempotent",
        )

        created = create_native_page(
            db,
            principal=principal,
            user=user,
            command=CreateNativePageCommand(
                item_id=doc.id,
                title="Created once",
                content_format="block",
                content_blocks=[{"type": "paragraph", "content": "hello"}],
                content_blocks_present=True,
                page_id="approved-page-1",
            ),
        )
        replayed = create_native_page(
            db,
            principal=principal,
            user=user,
            command=CreateNativePageCommand(
                item_id=doc.id,
                title="Created once",
                content_format="block",
                content_blocks=[{"type": "paragraph", "content": "hello"}],
                content_blocks_present=True,
                page_id="approved-page-1",
            ),
        )
        rows = list(db.scalars(select(NativeDocPage).where(NativeDocPage.id == "approved-page-1")))

        child = create_native_page(
            db,
            principal=principal,
            user=user,
            command=CreateNativePageCommand(
                item_id=doc.id, title="Child", parent_id=created.page_id
            ),
        )
        with pytest.raises(HTTPException) as cycle:
            update_native_page(
                db,
                user=user,
                command=UpdateNativePageCommand(
                    page_id=created.page_id,
                    parent_id=child.page_id,
                    parent_id_present=True,
                ),
            )
        assert cycle.value.status_code == 409
        assert cycle.value.detail.code == "docs.page_parent_cycle"
        assert db.get(NativeDocPage, created.page_id).parent_id is None
        removed = delete_native_page(
            db,
            user=user,
            command=DeleteNativePageCommand(page_id=created.page_id),
        )
        assert removed.page_id == created.page_id
        assert db.get(NativeDocPage, created.page_id).trashed_at is not None
        assert db.get(NativeDocPage, child.page_id).trashed_at is not None
        with pytest.raises(HTTPException) as denied:
            docs_service.read_page(db, user=user, page_id=child.page_id)
        assert denied.value.status_code == 403

    assert created.created is True
    assert replayed.created is False
    assert replayed.page_id == created.page_id
    assert len(rows) == 1


def _load_user(db, user_id: str):
    user = load_user_graph(db, user_id)
    assert user is not None
    return user
