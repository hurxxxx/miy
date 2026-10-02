import hashlib
import os

import pytest

from codex_console import instructions


@pytest.fixture(autouse=True)
def document_roots(monkeypatch, repository, tmp_path):
    locations = {
        "project": repository,
        "personal": tmp_path / "personal",
        "global": tmp_path / "codex-home",
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
