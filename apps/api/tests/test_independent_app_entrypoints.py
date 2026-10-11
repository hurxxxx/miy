from test_independent_app_delivery import (
    delivery_app as delivery_app,
)


BASE = "/api/v1/independent-apps"


def catalog_installation(client, app, installation_id=None):
    response = client.get(BASE + "/catalog", headers=app[1])
    assert response.status_code == 200
    data = response.json()
    item = next(
        item
        for item in data["items"]
        if item["definition"]["definition"]["app_id"] == "sample-independent"
    )
    installation = next(
        entry for entry in item["installations"] if entry["id"] == (installation_id or app[3]["id"])
    )
    return installation, data["catalog_revision"], item["definition"]


def register_ui(client, app, previous, revision, ui):
    definition = previous["definition"] | {
        "entrypoints": previous["definition"]["entrypoints"] | {"ui": ui}
    }
    response = client.put(
        BASE + "/definitions",
        headers=app[1],
        json={
            "definition": definition,
            "source_revision": revision,
            "expected_digest": previous["definition_digest"],
            "expected_source_revision": previous["source_revision"],
        },
    )
    assert response.status_code == 200
    return response.json()
