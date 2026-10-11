from __future__ import annotations

from fastapi.testclient import TestClient


_FILES_BASE = "/api/v1/files"


def _create_corpus(
    client: TestClient,
    *,
    headers: dict[str, str],
    name: str,
) -> dict:
    response = client.post(
        f"{_FILES_BASE}/corpora",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    corpus = response.json()
    assert corpus["name"] == name
    assert corpus["access_scope_kind"] == "company"
    assert corpus["metadata_version"] == 1
    assert corpus["retrieval_partition_id"]
    return corpus
