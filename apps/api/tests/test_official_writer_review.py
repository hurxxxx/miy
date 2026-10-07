"""Independent review of the real legacy HTTP mutation boundary."""

import pytest
from sqlalchemy import select

from miy_api.domains.announcements.models import Announcement
from test_official_writer_fence import change, writer as writer


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    ("locale", "detail"),
    [
        ("ko-KR", "현재 변경 내용을 저장할 수 없습니다. 잠시 후 다시 시도해 주세요."),
        ("en-US", "Changes cannot be saved right now. Please try again shortly."),
    ],
)
def test_legacy_http_commits_cannot_bypass_announcements_drain(
    client, writer, method, locale, detail
):
    factory, admin, announcement_id = writer
    headers = {"Authorization": "Bearer " + admin["token"], "X-MIY-Locale": locale}
    path = "/api/v1/announcements"
    with factory.begin() as db:
        change(db, admin)
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(f"{path}/{announcement_id}", headers=headers).status_code == 200
    # Every service commit reaches the trigger. The request session rolls back
    # and exposes only a translated stable code, never driver/SQL/parameter text.
    kwargs = {"headers": headers}
    if method != "POST":
        path = f"{path}/{announcement_id}"
    if method != "DELETE":
        kwargs["json"] = {"title": "Must not commit"}
    denied = client.request(method, path, **kwargs)
    assert denied.status_code == 503
    assert denied.json() == {"detail": detail, "code": "official_apps.writer_unavailable"}
    assert denied.headers["X-MIY-Error-Code"] == "official_apps.writer_unavailable"
    assert denied.headers["Retry-After"] == "5"
    assert client.get("/api/v1/announcements", headers=headers).status_code == 200
    with factory() as db:
        rows = db.scalars(select(Announcement)).all()
        assert len(rows) == 1
        assert rows[0].id == announcement_id
        assert rows[0].title == "Writer fixture"
