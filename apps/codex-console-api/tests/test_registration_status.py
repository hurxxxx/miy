"""Current source/registration comparison never supplies execution authority."""

import json
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_app_sources import app_checkout as app_checkout
from test_registration_draft import bound_project as bound_project
from test_registration_draft import command, commit, draft

from codex_console import workbench_sources as sources
from codex_console.models import AppSourceBinding, Task, WorkbenchProject, now


def status(client, project):
    return client.get(f"/api/workbench/projects/{project['id']}/registration-status")


def page(items, **changes):
    return {
        "schema_version": 1,
        "registration_status_version": 1,
        "items": items,
        "total": len(items),
        "page": 1,
        "page_size": 200,
        "catalog_revision": "a" * 64,
        "generated_at": now().isoformat(),
        **changes,
    }


@pytest.fixture
def remote(client, bound_project, monkeypatch):
    client.app.state.settings.miy_api_origin = "https://platform.example.test"
    local = draft(client, bound_project).json()
    data = {
        "app_id": local["app_id"],
        "title": "Registered app",
        "enabled": False,
        "runtime_ai": False,
        "release_unit": "independent-app:sample-app",
        "installed_revision": None,
        "registered_source_revision": local["source_revision"],
        "definition_digest": local["definition_digest"],
        "source_repository": local["definition"]["source"]["repository"],
        "source_directory": local["definition"]["source"]["directory"],
    }
    result = {"state": "ready", "page": page([data]), "calls": [], "during": None}

    async def get(settings, path):
        result["calls"].append(path)
        if result["during"]:
            result["during"]()
        return result["state"], result["page"]

    monkeypatch.setattr(sources, "miy_get", get)
    return result


def test_registered_disabled_app_matches_without_installation_or_executor_authority(
    client, app_checkout, bound_project, remote
):
    metadata = {
        name: (app_checkout / ".git" / name).read_bytes() for name in ("HEAD", "index", "config")
    }
    result = status(client, bound_project)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["state"] == "matching"
    assert value["definition_matches"] is value["revision_matches"] is True
    assert value["registered_source_revision"] == command(app_checkout, "rev-parse", "HEAD")
    assert value["platform_checked_at"] and value["platform_state"] == "ready"
    assert "installation_id" not in value and "executor" not in value
    assert len(remote["calls"]) == 1
    assert client.app.state.runtime.rpc is None
    with client.app.state.factory() as db:
        assert db.scalars(select(Task)).all() == []
    assert metadata == {name: (app_checkout / ".git" / name).read_bytes() for name in metadata}


@pytest.mark.parametrize("field", ["definition_digest", "registered_source_revision", "both"])
def test_definition_and_commit_difference_are_reported_independently(
    client, bound_project, remote, field
):
    item = remote["page"]["items"][0]
    if field in ("definition_digest", "both"):
        item["definition_digest"] = "sha256:" + "b" * 64
    if field in ("registered_source_revision", "both"):
        item["registered_source_revision"] = "b" * 40
    value = status(client, bound_project).json()
    assert value["state"] == "different"
    assert value["definition_matches"] == (field == "registered_source_revision")
    assert value["revision_matches"] == (field == "definition_digest")


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_repository", "https://elsewhere.test/another.git"),
        ("source_directory", "another"),
    ],
)
def test_same_id_with_different_source_is_a_collision(client, bound_project, remote, field, value):
    remote["page"]["items"][0][field] = value
    result = status(client, bound_project).json()
    assert result["state"] == "collision"
    assert result["definition_matches"] is result["revision_matches"] is None


def test_confirmed_absence_needs_fresh_complete_versioned_catalog(client, bound_project, remote):
    assert status(client, bound_project).json()["state"] == "matching"
    remote["page"] = page([])
    assert status(client, bound_project).json()["state"] == "unregistered"
    assert len(remote["calls"]) == 2  # Explicit check bypasses the existing 15s cache.
    remote["page"].pop("catalog_revision")
    assert status(client, bound_project).json()["state"] == "unknown"


@pytest.mark.parametrize("capability", [None, 2, True])
@pytest.mark.parametrize("empty", [False, True])
def test_legacy_or_unknown_capability_never_means_unregistered(
    client, bound_project, remote, capability, empty
):
    if empty:
        remote["page"] = page([])
    if capability is None:
        remote["page"].pop("registration_status_version")
    else:
        remote["page"]["registration_status_version"] = capability
    value = status(client, bound_project).json()
    assert value["state"] == "unknown"
    assert value["definition_matches"] is value["revision_matches"] is None


def test_capability_must_be_consistent_across_all_pages(client, bound_project, remote, monkeypatch):
    target = remote["page"]["items"][0]
    entries = [target] + [{**target, "app_id": f"other-{index}"} for index in range(200)]

    async def get(settings, path):
        number = 1 if "page=1&" in path else 2
        return "ready", page(
            entries[(number - 1) * 200 : number * 200],
            total=201,
            page=number,
            registration_status_version=1 if number == 1 else None,
        )

    monkeypatch.setattr(sources, "miy_get", get)
    result = status(client, bound_project).json()
    assert result["state"] == "unknown" and result["platform_state"] == "unsupported"


@pytest.mark.parametrize("state", ["unavailable", "unconfigured", "denied", "unsupported"])
def test_failed_refresh_does_not_certify_cached_evidence(client, bound_project, remote, state):
    before = status(client, bound_project).json()
    remote.update(state=state, page=None)
    value = status(client, bound_project).json()
    assert value["state"] == "unknown" and value["platform_state"] == state
    assert value["platform_checked_at"] == before["platform_checked_at"]
    assert value["definition_matches"] is value["revision_matches"] is None


@pytest.mark.parametrize(
    "field",
    [
        "registered_source_revision",
        "definition_digest",
        "source_repository",
        "source_directory",
    ],
)
def test_legacy_missing_identity_is_unknown(client, bound_project, remote, field):
    remote["page"]["items"][0].pop(field)
    assert status(client, bound_project).json()["state"] == "unknown"


@pytest.mark.parametrize("change", ["head", "manifest", "binding", "project", "root"])
def test_source_or_binding_change_while_querying_platform_fails_closed(
    client, app_checkout, bound_project, remote, change
):
    def mutate():
        if change == "head":
            (app_checkout / "README.md").write_text("New code")
            commit(app_checkout, "source changed during lookup")
        elif change == "manifest":
            path = app_checkout / "app.manifest.json"
            value = json.loads(path.read_text())
            value["display"]["name"] = "Changed"
            path.write_text(json.dumps(value))
            commit(app_checkout, "manifest changed during lookup")
        elif change == "root":
            retained = app_checkout.with_name("retained-original")
            app_checkout.rename(retained)
            shutil.copytree(retained, app_checkout)
        else:
            with client.app.state.factory.begin() as db:
                if change == "binding":
                    db.get(AppSourceBinding, "sample-app").version += 1
                else:
                    db.get(WorkbenchProject, bound_project["id"]).app_id = "another-app"

    remote["during"] = mutate
    result = status(client, bound_project)
    assert result.status_code == 409
    assert result.json()["code"] == "app_source_changed"


def test_dirty_source_and_owner_auth_fail_before_remote_read(
    client, app_checkout, bound_project, remote
):
    (app_checkout / "README.md").write_text("Pending edit")
    result = status(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_dirty"
    assert not remote["calls"]
    client.cookies.clear()
    assert status(client, bound_project).status_code == 401
    assert not remote["calls"]


def test_unknown_project_never_contacts_platform(client, remote):
    assert status(client, {"id": str(uuid4())}).status_code == 404
    assert not remote["calls"]


@pytest.mark.parametrize(
    "kind", ["missing-revision", "invalid-revision", "digest", "duplicate", "truncated"]
)
def test_incomplete_or_legacy_metadata_cannot_certify_registration(
    client, bound_project, remote, kind
):
    if kind == "missing-revision":
        remote["page"].pop("catalog_revision")
    elif kind == "invalid-revision":
        remote["page"]["catalog_revision"] = "not-a-snapshot"
    elif kind == "digest":
        remote["page"]["items"][0]["definition_digest"] = "invalid" * 200
    elif kind == "duplicate":
        remote["page"]["items"] *= 2
        remote["page"]["total"] = 2
    else:
        remote["page"]["total"] = 201
    result = status(client, bound_project)
    assert result.status_code == 200
    value = result.json()
    assert value["state"] == "unknown"
    assert value["definition_matches"] is value["revision_matches"] is None
    assert "invalidinvalid" not in result.text


@pytest.mark.parametrize("second_revision", ["a" * 64, "b" * 64, None])
def test_all_pages_share_a_revision_even_when_target_is_on_first_page(
    client, bound_project, remote, monkeypatch, second_revision
):
    target = remote["page"]["items"][0]
    entries = [target] + [{**target, "app_id": f"other-{index}"} for index in range(200)]
    calls = []

    async def get(settings, path):
        number = 1 if "page=1&" in path else 2
        calls.append(number)
        return "ready", page(
            entries[(number - 1) * 200 : number * 200],
            total=201,
            page=number,
            catalog_revision="a" * 64 if number == 1 else second_revision,
        )

    monkeypatch.setattr(sources, "miy_get", get)
    value = status(client, bound_project).json()
    assert calls == [1, 2]
    assert value["state"] == ("matching" if second_revision == "a" * 64 else "unknown")


def test_registered_collision_can_be_rechecked_after_catalog_marks_source_invalid(
    client, bound_project, remote
):
    item = remote["page"]["items"][0]
    original = item["source_repository"]
    item["source_repository"] = "https://elsewhere.test/collision.git"
    assert status(client, bound_project).json()["state"] == "collision"
    catalog = client.get("/api/workbench/catalog").json()
    assert (
        next(row for row in catalog["items"] if row["app_id"] == "sample-app")["source_status"]
        == "invalid"
    )
    item["source_repository"] = original
    assert status(client, bound_project).json()["state"] == "matching"


def test_platform_change_during_read_cannot_compare_another_installation(
    client, bound_project, remote
):
    remote["during"] = lambda: setattr(
        client.app.state.settings, "miy_api_origin", "https://replacement.example.test"
    )
    result = status(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_changed"
