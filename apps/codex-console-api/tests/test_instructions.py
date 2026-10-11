import hashlib
import os
import shutil
import subprocess

import pytest

from codex_console import instructions


@pytest.fixture(autouse=True)
def document_roots(monkeypatch, repository, tmp_path):
    locations = {
        "project": repository,
        "personal": tmp_path / "personal",
        "global": tmp_path / "codex-home",
        "admin": tmp_path / "machine/skills",
        "system": tmp_path / "codex-home/skills/.system",
        "plugins": tmp_path / "codex-home/plugins/cache",
    }
    monkeypatch.setattr(instructions, "roots", lambda settings: locations)
    return locations


def save(client, path="AGENTS.md", content="# Rules\n\n  Keep whitespace.\n", **extra):
    return client.put(
        "/api/instructions/document",
        json={
            "scope": "project",
            "path": path,
            "content": content,
            "revision": None,
            **extra,
        },
    )


def read(client, path="AGENTS.md", scope="project"):
    return client.get("/api/instructions/document", params={"scope": scope, "path": path})


@pytest.mark.parametrize("client_role", ["combined", "management"], indirect=True)
def test_authoring_is_offline_and_preserves_exact_content(client, repository):
    body = "# 작업 지침\n\n  trailing spaces  \n\n"
    result = save(client, content=body)
    assert result.status_code == 200
    original = result.json()
    assert original["content"] == body
    assert (repository / "AGENTS.md").read_text() == body
    assert read(client).json() == original
    assert original["revision"] == hashlib.sha256(body.encode()).hexdigest()
    assert client.get("/api/instructions").json()["entries"] == [
        {
            "scope": "project",
            "path": "AGENTS.md",
            "kind": "instructions",
            "editable": True,
        }
    ]
    assert save(client, content="clobber").status_code == 409
    os.chmod(repository / "AGENTS.md", 0o644)
    assert save(client, content="", revision=original["revision"]).status_code == 200
    assert (repository / "AGENTS.md").stat().st_mode & 0o777 == 0o644
    assert read(client).json()["exists"] is True
    client.headers.pop("x-csrf-token")
    assert save(client).status_code == 401
    client.cookies.clear()
    assert read(client).status_code == 401
    assert client.get("/api/instructions").status_code == 401


def test_conflict_preserves_an_external_edit(client, repository):
    original = save(client).json()
    (repository / "AGENTS.md").write_text("External change\n")
    assert save(client, content="My draft\n", revision=original["revision"]).status_code == 409
    assert (repository / "AGENTS.md").read_text() == "External change\n"
    assert not list(repository.glob(".console-document-*"))


def test_documents_are_portable_between_unrelated_repositories(
    client, repository, tmp_path, document_roots
):
    from codex_console.config import Settings

    for project in ("order-book", "research-notebooks"):
        root = tmp_path / project
        shutil.copytree(repository, root)
        subprocess.run(["git", "-C", str(root), "branch", "-m", "primary"], check=True)
        settings = Settings(
            **{**client.app.state.settings.model_dump(), "workspace": root}, _env_file=None
        )
        client.app.state.settings = settings
        document_roots["project"] = root
        assert save(client, "components/AGENTS.override.md", f"# {project}\n").status_code == 200
        path = "components/.agents/skills/quality-check/SKILL.md"
        content = "---\nname: quality-check\ndescription: Check local quality\n---\n"
        assert save(client, path, content).status_code == 200
        catalog = client.get("/api/instructions").json()
        assert catalog["roots"]["project"] == str(root)
        assert {entry["path"] for entry in catalog["entries"]} == {
            "components/AGENTS.override.md", path
        }
        assert read(client, "components/AGENTS.override.md").json()["content"] == f"# {project}\n"
    assert (tmp_path / "order-book/components/AGENTS.override.md").read_text() == "# order-book\n"


def test_skill_bundle_markdown_search_and_read_only_sources(client, document_roots):
    paths = {
        ("project", ".agents/skills/review/DESIGN.md"): "# Design\n\nSemantic needle.\n",
        ("project", ".agents/skills/review/notes/deep.md"): "# Nested reference\n",
        ("project", ".agents/skills/review/scripts/check.py"): "print('example')\n",
        ("project", "apps/CLAUDE.md"): "@AGENTS.md\n",
        ("project", ".github/copilot-instructions.md"): "Read AGENTS.md\n",
        ("system", "review/SKILL.md"): "---\nname: review\ndescription: Review\n---\n",
        ("admin", "company-review/SKILL.md"): "# Machine managed\n",
        ("plugins", "vendor/plugin/1.0/skills/review/SKILL.md"): "# Installed\n",
    }
    for (scope, path), content in paths.items():
        target = document_roots[scope] / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    entries = client.get("/api/instructions").json()["entries"]
    assert {(e["scope"], e["path"]) for e in entries} == set(paths)
    for entry in entries:
        response = read(client, entry["path"], entry["scope"])
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == paths[(entry["scope"], entry["path"])]
        editable = entry["kind"] == "reference"
        assert data["editable"] == editable
        if not editable:
            assert (
                save(
                    client,
                    entry["path"],
                    "changed",
                    scope=entry["scope"],
                    revision=data["revision"],
                ).status_code
                == 403
            )
    found = client.get("/api/instructions", params={"q": "SEMANTIC needle", "scope": "project"})
    assert [e["path"] for e in found.json()["entries"]] == [".agents/skills/review/DESIGN.md"]
    assert (
        client.get("/api/instructions", params={"q": "needle", "scope": "system"}).json()["entries"]
        == []
    )


def test_installed_scope_rejects_links_and_arbitrary_files(client, document_roots, tmp_path):
    root = document_roots["system"]
    (root / "review").mkdir(parents=True)
    private = tmp_path / "private.md"
    private.write_text("private")
    (root / "review/SKILL.md").symlink_to(private)
    assert read(client, "review/SKILL.md", "system").status_code == 403
    assert read(client, "../AGENTS.md", "system").status_code == 403
    assert read(client, "vendor/auth.json", "plugins").status_code == 403
    assert read(client, "review/.env.md", "system").status_code == 403
    assert client.get("/api/instructions?scope=system").json()["entries"] == []


def test_discovery_reports_native_enabled_state_and_fails_closed(client, repository, monkeypatch):
    from conftest import FakeRPC

    original = FakeRPC.call
    payload = {
        "data": [
            {
                "cwd": str(repository),
                "skills": [
                    {
                        "name": "review",
                        "description": "Review code",
                        "path": str(repository / ".agents/skills/review/SKILL.md"),
                        "enabled": False,
                    }
                ],
                "errors": [],
            }
        ]
    }
    config = {
        "project_doc_fallback_filenames": ["TEAM_GUIDE.md", ".agents.md"],
        "project_doc_max_bytes": 65536,
        "unrelated_private_setting": "not-for-the-browser",
    }

    async def call(self, method, params):
        if method == "skills/list":
            assert params == {"cwds": [str(repository)], "forceReload": True}
            return payload
        if method == "config/read":
            assert params == {"cwd": str(repository), "includeLayers": False}
            return {"config": config}
        return await original(self, method, params)

    monkeypatch.setattr(FakeRPC, "call", call)
    response = client.get("/api/codex/skills")
    assert response.status_code == 200
    assert response.json()["skills"][0]["enabled"] is False
    assert response.json()["guidance"] == {
        "fallback_filenames": ["TEAM_GUIDE.md", ".agents.md"],
        "max_bytes": 65536,
    }
    assert "not-for-the-browser" not in response.text
    config["project_doc_max_bytes"] = "not-an-integer"
    response = client.get("/api/codex/skills")
    assert response.status_code == 200
    assert response.json()["guidance"] is None
    assert response.json()["skills"][0]["enabled"] is False
    payload["data"][0]["skills"][0]["enabled"] = "false"
    assert client.get("/api/codex/skills").status_code == 502
    assert client.get("/api/codex/skills?directory_name=../private").status_code == 403
    client.cookies.clear()
    assert client.get("/api/codex/skills").status_code == 401


def test_official_scoped_files_and_skill_references(client, document_roots):
    cases = [
        ("project", "module/AGENTS.override.md", "# Scoped\n"),
        (
            "project",
            "module/.agents/skills/review/SKILL.md",
            "---\nname: review\ndescription: Review changes\n---\n\n# Review\n",
        ),
        (
            "project",
            "module/.agents/skills/review/agents/openai.yaml",
            "policy:\n  allow_implicit_invocation: false\n",
        ),
        ("project", "module/.agents/skills/review/references/checks.md", "# Checks\n"),
        (
            "personal",
            "skills/my-skill/SKILL.md",
            "---\nname: my-skill\ndescription: Check things\n---\n\n# Steps\n",
        ),
        ("global", "AGENTS.md", "# Defaults\n"),
        (
            "global",
            "skills/legacy/SKILL.md",
            "---\nname: legacy\ndescription: Do something\n---\n\n# Steps\n",
        ),
    ]
    for scope, path, content in cases:
        result = save(client, path, content, scope=scope)
        assert result.status_code == 200
        assert (document_roots[scope] / path).read_text() == content
    entries = client.get("/api/instructions").json()["entries"]
    assert {(entry["scope"], entry["path"]) for entry in entries} == {
        (scope, path) for scope, path, _ in cases
    }
    assert save(client, ".agents/skills/broken/SKILL.md", "# No metadata").status_code == 422
    assert (
        save(
            client, ".agents/skills/broken/SKILL.md", "---\nname:\ndescription: Example\n---\n"
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path",
    [
        "../AGENTS.md",
        "/tmp/AGENTS.md",
        "hello.txt",
        ".env",
        ".git/AGENTS.md",
        "secrets/AGENTS.md",
        ".auth_info/AGENTS.md",
        ".agents/skills/test/scripts/run.py",
        ".agents/skills/.system/SKILL.md",
        "a//AGENTS.md",
        "a/./AGENTS.md",
        "a\\AGENTS.md",
    ],
)
def test_only_document_paths_are_authorized(client, path):
    assert save(client, path).status_code == 403
    assert read(client, path).status_code == 403


def test_links_devices_size_and_encoding_are_rejected(client, repository, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "AGENTS.md"
    secret.write_text("outside")
    (repository / "linked").symlink_to(outside, target_is_directory=True)
    assert save(client, "linked/AGENTS.md").status_code == 403
    target = repository / "AGENTS.md"
    target.symlink_to(secret)
    assert read(client).status_code == 403
    assert save(client).status_code == 403
    target.unlink()
    os.link(secret, target)
    assert read(client).status_code == 403
    assert save(client).status_code == 403
    target.unlink()
    os.mkfifo(target)
    assert read(client).status_code == 403
    target.unlink()
    target.write_bytes(b"\xff")
    assert read(client).status_code == 422
    target.write_bytes(b"a" * (instructions.MAX_BYTES + 1))
    assert read(client).status_code == 413
    target.unlink()
    assert save(client, content="가" * 30000).status_code == 413
    assert not target.exists()
    assert secret.read_text() == "outside"


def test_protected_roots_and_ancestor_symlinks_fail_closed(client, document_roots, tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    client.app.state.settings.protected_workspaces = [protected]
    document_roots["global"] = protected / "codex"
    assert save(client, scope="global").status_code == 403
    document_roots["global"] = tmp_path / "link" / "codex"
    (tmp_path / "link").symlink_to(protected, target_is_directory=True)
    assert save(client, scope="global").status_code == 403


def test_descriptor_revalidation_rejects_replaced_parent(client, repository, tmp_path, monkeypatch):
    (repository / "module").mkdir()
    (repository / "module/AGENTS.md").write_text("original")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("private")
    real_target = instructions.target

    def replaced_target(*args):
        result = real_target(*args)
        (repository / "module/AGENTS.md").unlink()
        (repository / "module").rmdir()
        (repository / "module").symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(instructions, "target", replaced_target)
    assert read(client, "module/AGENTS.md").status_code == 403
    assert (outside / "AGENTS.md").read_text() == "private"
