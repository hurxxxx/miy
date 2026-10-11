"""Real source coverage for the canonical Docs app and its PMS link boundary."""

import pytest
from dev_accounts import configure_company_app_access
from test_official_writer_fence import writer as writer


@pytest.fixture
def docs_source(client, writer):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(db, app_ids=["docs", "pms"])
    headers = {"Authorization": "Bearer " + admin["token"]}
    response = client.post("/api/v1/docs/items", headers=headers, json={"title": "Fenced source"})
    assert response.status_code == 201
    doc = response.json()
    response = client.get(f"/api/v1/docs/items/{doc['id']}/pages", headers=headers)
    assert response.status_code == 200
    page = response.json()["items"][0]
    return factory, admin, headers, doc, page
