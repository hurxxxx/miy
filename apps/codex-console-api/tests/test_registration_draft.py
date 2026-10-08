"""Registration drafts expose current local metadata without authority or mutation."""

import hashlib
import json
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_app_sources import app_checkout as app_checkout
from test_app_sources import bind, command

from codex_console import app_sources, git
from codex_console.models import AppSourceBinding, AppSourceSetup, Task, WorkbenchProject


def project(client, *, reuse="new"):
    result = client.post(
        "/api/workbench/projects",
        json={
            "app_id": "sample-app",
            "title": "Draft app",
            "summary": "Prepare registration",
            "reuse_decision": reuse,
            "reuse_notes": "An independent source is selected",
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def bound_project(client, app_checkout):
    row = project(client)
    assert bind(client, app_checkout).status_code == 200
    return row


def draft(client, row):
    return client.get(f"/api/workbench/projects/{row['id']}/registration-draft")


def commit(root, name):
    command(root, "add", "--all")
    command(root, "commit", "-m", name)


def test_draft_is_current_normalized_metadata_without_setup_record_or_side_effects(
    client, app_checkout, bound_project
):
    initial = command(app_checkout, "rev-parse", "HEAD")
    manifest_path = app_checkout / "app.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["display"]["name"] = "현재 앱 이름"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    commit(app_checkout, "later personal change")
    current = command(app_checkout, "rev-parse", "HEAD")
    assert current != initial
    metadata = {
        name: (app_checkout / ".git" / name).read_bytes() for name in ("HEAD", "index", "config")
    }
    with client.app.state.factory() as db:
        binding = db.get(AppSourceBinding, "sample-app")
        before = (binding.version, binding.manifest_digest, binding.updated_at)
        assert db.scalars(select(AppSourceSetup)).all() == []
    response = draft(client, bound_project)
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {
        "schema_version",
        "project_id",
        "binding_version",
        "app_id",
        "source_revision",
        "source_manifest_digest",
        "definition_digest",
        "definition",
    }
    assert value["schema_version"] == 1 and value["binding_version"] == 1
    assert value["source_revision"] == current
    assert value["definition"]["display"]["name"] == "현재 앱 이름"
    raw_digest = "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    canonical = json.dumps(value["definition"], sort_keys=True, separators=(",", ":"))
    assert value["source_manifest_digest"] == raw_digest
    assert value["definition_digest"] == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    assert value["source_manifest_digest"] != value["definition_digest"]
    assert str(app_checkout) not in response.text and "operation_id" not in value
    assert client.app.state.runtime.rpc is None
    with client.app.state.factory() as db:
        binding = db.get(AppSourceBinding, "sample-app")
        assert (binding.version, binding.manifest_digest, binding.updated_at) == before
        assert db.scalars(select(Task)).all() == []
    assert metadata == {name: (app_checkout / ".git" / name).read_bytes() for name in metadata}


def test_existing_independent_project_uses_same_read_only_draft(client, app_checkout):
    assert bind(client, app_checkout).status_code == 200
    row = project(client, reuse="extend")
    assert draft(client, row).status_code == 200


@pytest.mark.parametrize("kind", ["tracked", "staged", "untracked", "hidden-manifest"])
def test_dirty_source_cannot_be_exported_as_a_committed_draft(
    client, app_checkout, bound_project, kind
):
    if kind == "hidden-manifest":
        command(app_checkout, "update-index", "--assume-unchanged", "app.manifest.json")
        path = app_checkout / "app.manifest.json"
        manifest = json.loads(path.read_text())
        manifest["display"]["name"] = "Hidden uncommitted change"
        path.write_text(json.dumps(manifest))
        assert not git.status(app_checkout)["changed"]
    else:
        (app_checkout / ("new.txt" if kind == "untracked" else "README.md")).write_text("Changed")
        if kind == "staged":
            command(app_checkout, "add", "README.md")
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_dirty"


def test_draft_requires_owner_and_existing_project_binding(client, app_checkout):
    assert draft(client, {"id": str(uuid4())}).status_code == 404
    row = project(client)
    assert draft(client, row).json()["code"] == "app_source_unavailable"
    assert bind(client, app_checkout).status_code == 200
    client.headers.pop("x-csrf-token")
    assert draft(client, row).status_code == 200  # GET does not grant write authority.
    client.cookies.clear()
    assert draft(client, row).status_code == 401


def test_changed_source_directory_requires_an_explicit_binding_refresh(
    client, app_checkout, bound_project
):
    path = app_checkout / "app.manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source"]["directory"] = "another"
    (app_checkout / "another").mkdir()
    (app_checkout / "another" / "README.md").write_text("Changed source identity")
    path.write_text(json.dumps(manifest))
    commit(app_checkout, "change source directory")
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_changed"


@pytest.mark.parametrize("change", ["version", "root", "manifest", "project"])
def test_binding_change_during_git_read_cannot_return_a_stale_draft(
    client, app_checkout, bound_project, monkeypatch, change
):
    original = git.status
    calls = 0

    def status(root):
        nonlocal calls
        result = original(root)
        calls += 1
        if calls == 1:
            with client.app.state.factory.begin() as db:
                binding = db.get(AppSourceBinding, "sample-app")
                if change == "version":
                    binding.version += 1
                elif change == "root":
                    binding.repository_root = str(app_checkout.parent / "replacement")
                elif change == "manifest":
                    binding.manifest = {**binding.manifest, "sdk_version": 2}
                else:
                    db.get(WorkbenchProject, bound_project["id"]).app_id = "another-app"
        return result

    monkeypatch.setattr(git, "status", status)
    result = draft(client, bound_project)
    assert result.status_code in (409, 422)
    assert result.json()["code"] in ("app_source_changed", "app_source_unavailable")


@pytest.mark.parametrize("location", ["root", "git"])
def test_replacing_a_directory_with_identical_files_during_read_is_rejected(
    client, app_checkout, bound_project, monkeypatch, location
):
    original = git.status
    calls = 0

    def status(root):
        nonlocal calls
        result = original(root)
        calls += 1
        if calls == 1:
            target = app_checkout if location == "root" else app_checkout / ".git"
            retained = app_checkout.parent / ("retained-" + location)
            target.rename(retained)
            shutil.copytree(retained, target)
        return result

    monkeypatch.setattr(git, "status", status)
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_changed"
    assert (app_checkout.parent / ("retained-" + location)).exists()


def test_new_commit_during_read_is_not_mixed_with_previous_revision(
    client, app_checkout, bound_project, monkeypatch
):
    original = git.status
    calls = 0

    def status(root):
        nonlocal calls
        result = original(root)
        calls += 1
        if calls == 1:
            (app_checkout / "README.md").write_text("A concurrent committed change")
            commit(app_checkout, "concurrent change")
        return result

    monkeypatch.setattr(git, "status", status)
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_changed"
    assert (app_checkout / "README.md").read_text() == "A concurrent committed change"


def test_manifest_change_during_read_cannot_return_old_public_metadata(
    client, app_checkout, bound_project, monkeypatch
):
    original = app_sources.read_manifest
    calls = 0

    def read(*args):
        nonlocal calls
        result = original(*args)
        calls += 1
        if calls == 1:
            path = app_checkout / "app.manifest.json"
            manifest = json.loads(path.read_text())
            manifest["display"]["name"] = "Changed while reading"
            path.write_text(json.dumps(manifest))
        return result

    monkeypatch.setattr(app_sources, "read_manifest", read)
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_changed"


@pytest.mark.parametrize(
    "kind", ["missing", "credentials", "directory-link", "root-link", "policy"]
)
def test_missing_or_unsafe_source_has_typed_failure_without_exposing_input(
    client, app_checkout, bound_project, kind
):
    marker = app_checkout.parent / "filter-ran"
    if kind == "missing":
        (app_checkout / "app.manifest.json").unlink()
        commit(app_checkout, "manifest removed")
    elif kind == "credentials":
        path = app_checkout / "app.manifest.json"
        manifest = json.loads(path.read_text())
        manifest["source"]["repository"] = (
            "https://synthetic-secret@example.test/team/sample-app.git"
        )
        path.write_text(json.dumps(manifest))
        commit(app_checkout, "invalid repository URL")
    elif kind == "directory-link":
        path = app_checkout / "app.manifest.json"
        manifest = json.loads(path.read_text())
        manifest["source"]["directory"] = "linked"
        (app_checkout / "linked").symlink_to(app_checkout.parent, target_is_directory=True)
        path.write_text(json.dumps(manifest))
        commit(app_checkout, "linked source directory")
    elif kind == "root-link":
        moved = app_checkout.with_name("retained-source")
        app_checkout.rename(moved)
        app_checkout.symlink_to(moved, target_is_directory=True)
    else:
        command(app_checkout, "config", "filter.custom.clean", "touch " + str(marker))
        (app_checkout / ".gitattributes").write_text("README.md filter=custom\n")
    result = draft(client, bound_project)
    assert result.status_code in (403, 404, 422)
    assert result.json()["code"] in (
        "reference_not_found",
        "app_source_invalid",
        "path_denied",
        "app_source_denied",
        "app_source_git_policy",
    )
    assert "synthetic-secret" not in result.text and not marker.exists()


def test_revoked_source_root_is_rechecked_after_binding(
    client, settings, app_checkout, bound_project
):
    settings.app_source_roots = []
    result = draft(client, bound_project)
    assert result.status_code == 403 and result.json()["code"] == "app_source_denied"


def test_canonical_defaults_and_unicode_are_included_without_losing_permission_order(
    client, app_checkout, bound_project
):
    path = app_checkout / "app.manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("entrypoints", None)
    manifest.pop("runtime_profile", None)
    manifest["display"]["name"] = "메모 📋"
    manifest["requested_permissions"] = ["identity:read"]
    path.write_text(json.dumps(manifest, ensure_ascii=False))
    commit(app_checkout, "canonical defaults")
    result = draft(client, bound_project)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["definition"]["runtime_profile"] == "web-api-v1"
    assert value["definition"]["entrypoints"] == {"ui": "/", "api": "/api", "health": "/healthz"}
    assert value["definition"]["requested_permissions"] == ["identity:read"]


def test_ignored_manifest_not_present_in_head_is_not_a_registration_source(
    client, app_checkout, bound_project
):
    command(app_checkout, "rm", "--cached", "app.manifest.json")
    (app_checkout / ".gitignore").write_text("app.manifest.json\n")
    commit(app_checkout, "manifest is no longer committed")
    assert not git.status(app_checkout)["changed"]
    result = draft(client, bound_project)
    assert result.status_code == 409 and result.json()["code"] == "app_source_dirty"


def test_float_integer_versions_share_core_canonical_definition_digest(
    client, app_checkout, bound_project
):
    original = draft(client, bound_project).json()
    path = app_checkout / "app.manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(schema_version=1.0, sdk_version=1.0)
    path.write_text(json.dumps(manifest))
    commit(app_checkout, "JSON integer versions expressed as floats")
    response = draft(client, bound_project)
    assert response.status_code == 200, response.text
    value = response.json()
    assert type(value["definition"]["schema_version"]) is int
    assert type(value["definition"]["sdk_version"]) is int
    assert value["definition_digest"] == original["definition_digest"]
    assert value["source_manifest_digest"] != original["source_manifest_digest"]
