from test_company_content_boundaries import _enable as _enable, _group as _group, _user as _user
from test_company_groups import _setup as _setup


def test_doc_sharing_invalidates_only_that_resource_without_content_or_unrelated_users(
    client, monkeypatch
):
    admin, _ = _setup(client)
    for app in ("docs", "pms"):
        _enable(client, admin, app)
    owner, _ = _user(client, admin, "invalidationowner")
    reader, reader_id = _user(client, admin, "invalidationreader")
    group_id = _group(client, admin, [reader_id])
    space = client.post("/api/v1/pms/spaces", headers=owner, json={"name": "Project"})
    assert space.status_code == 201
    created = client.post("/api/v1/docs/items", headers=owner, json={"title": "Private title"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    doc_id = item_id.split("__")[-1]
    url = f"/api/v1/docs/items/{item_id}"
    events = []
    monkeypatch.setattr(
        client.app.state.app_realtime,
        "publish",
        lambda topic, event: events.append((topic, event)),
    )

    def changed(method, suffix, body=None):
        events.clear()
        response = client.request(method, f"{url}{suffix}", headers=owner, json=body)
        assert response.status_code in (200, 204), response.text
        assert events == [
            (f"docs.pages:{doc_id}", {"type": "docs.access.changed", "data": {"doc_id": doc_id}})
        ]
        return response

    changed("PUT", f"/sharing/users/{reader_id}", {"access_level": "edit"})
    assert client.get(url, headers=reader).json()["can_edit"]
    changed("PUT", f"/sharing/users/{reader_id}", {"access_level": "read"})
    assert not client.get(url, headers=reader).json()["can_edit"]
    changed("DELETE", f"/sharing/users/{reader_id}")
    assert client.get(url, headers=reader).status_code == 404

    changed("PUT", "/sharing/link", {"active": True, "access_level": "edit"})
    changed(
        "PUT", "/sharing/link", {"active": True, "access_level": "read", "regenerate_token": True}
    )
    changed("DELETE", "/sharing/link")
    changed("PUT", f"/sharing/groups/{group_id}", {"access_level": "read"})
    assert client.get(url, headers=reader).status_code == 200
    changed("DELETE", f"/sharing/groups/{group_id}")
    assert client.get(url, headers=reader).status_code == 404
    changed("PUT", "/sharing/company", {"enabled": True, "company_admin_read_acknowledged": True})
    assert client.get(url, headers=reader).status_code == 200
    changed("PUT", "/sharing/company", {"enabled": False})
    assert client.get(url, headers=reader).status_code == 404
    changed(
        "PUT",
        "/target",
        {
            "app": "pms",
            "type": "space",
            "id": space.json()["id"],
            "company_admin_read_acknowledged": True,
        },
    )
    changed("DELETE", "/target")
    changed("PUT", f"/sharing/users/{reader_id}", {"access_level": "read"})
    assert client.get(url, headers=reader).status_code == 200
    changed("DELETE", "")
    assert client.get(url, headers=reader).status_code == 404
    assert client.get(url, headers=owner).json()["trashed_at"] is not None
