from __future__ import annotations

import io
import hashlib
import json
import subprocess
import tarfile
import zlib
from pathlib import Path

import pytest

from miy_api.domains.independent_apps import builds
from miy_api.domains.independent_apps.contracts import AppDefinition


IMAGE = "sha256:" + "a" * 64
ARTIFACT = "sha256:" + "b" * 64


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as result:
        for name, value in entries:
            info = tarfile.TarInfo(name)
            if isinstance(value, bytes):
                info.size = len(value)
                result.addfile(info, io.BytesIO(value))
            else:
                info.type, info.linkname = value
                result.addfile(info)
    return output.getvalue()


def repo(tmp_path):
    source = tmp_path / "app"
    source.mkdir()
    definition = AppDefinition.model_validate(
        {
            "app_id": "build-app",
            "display": {"name": "Build app"},
            "source": {"repository": "https://example.test/team/build-app.git"},
        }
    )
    (source / "app.manifest.json").write_text(definition.model_dump_json())
    (source / "api.py").write_text("value = 1\n")

    def git(*args):
        return (
            subprocess.check_output(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "user.name=Build test",
                    "-c",
                    "user.email=build@example.test",
                    "-c",
                    "commit.gpgsign=false",
                    "-C",
                    str(source),
                    *args,
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

    git("init")
    git("remote", "add", "origin", definition.source.repository)
    git("add", ".")
    git("commit", "-m", "Synthetic build fixture")
    return source, git("rev-parse", "HEAD"), definition, git


@pytest.mark.parametrize(
    "entry",
    [
        ("../escape", b"bad"),
        ("/absolute", b"bad"),
        (".env", b"SECRET=value"),
        (".codex/auth.json", b"secret"),
        ("node_modules/cache", b"bad"),
        ("link", (tarfile.SYMTYPE, "/etc/passwd")),
        ("hard", (tarfile.LNKTYPE, "api.py")),
        ("fifo", (tarfile.FIFOTYPE, "")),
    ],
)
def test_archive_rejects_links_special_files_credentials_and_traversal(tmp_path, entry):
    with pytest.raises(builds.BuildFailure, match="build_archive_unsafe"):
        builds._unpack(archive([entry]), tmp_path)


def test_archive_rejects_duplicate_and_large_files(tmp_path, monkeypatch):
    with pytest.raises(builds.BuildFailure):
        builds._unpack(archive([("same", b"a"), ("same", b"b")]), tmp_path)
    monkeypatch.setattr(builds, "MAX_FILE", 2)
    with pytest.raises(builds.BuildFailure):
        builds._unpack(archive([("large", b"abc")]), tmp_path)


def test_snapshot_uses_approved_commit_and_checks_manifest(tmp_path):
    source, revision, definition, _ = repo(tmp_path)
    (source / "api.py").write_text("dirty source must not ship")
    (source / ".env").write_text("untracked secret must not ship")
    destination = tmp_path / "snapshot"
    destination.mkdir()
    digest = builds._snapshot(source, revision, definition, destination)
    assert len(digest) == 64
    assert (destination / "api.py").read_text() == "value = 1\n"
    assert not (destination / ".env").exists()
    changed = definition.model_copy(
        update={"display": definition.display.model_copy(update={"name": "Changed"})}
    )
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(builds.BuildFailure, match="build_definition_mismatch"):
        builds._snapshot(source, revision, changed, other)


def replace_loose_object(source, oid, kind, content):
    path = source / ".git/objects" / oid[:2] / oid[2:]
    path.unlink()
    path.write_bytes(
        zlib.compress(kind.encode() + b" " + str(len(content)).encode() + b"\0" + content)
    )


@pytest.mark.parametrize("kind", ["blob", "tree", "commit"])
def test_snapshot_rejects_content_under_the_wrong_object_hash(tmp_path, kind):
    source, revision, definition, git = repo(tmp_path)
    oid = {
        "blob": git("rev-parse", "HEAD:api.py"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "commit": revision,
    }[kind]
    original = subprocess.check_output(["git", "-C", str(source), "cat-file", kind, oid])
    changed = {
        "blob": b"value = 999\n",
        "tree": original.replace(b"api.py", b"bad.py"),
        "commit": original.replace(b"Synthetic", b"Different"),
    }[kind]
    replace_loose_object(source, oid, kind, changed)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(
        builds.BuildFailure, match="build_source_object_invalid|build_command_failed"
    ):
        builds._snapshot(source, revision, definition, destination)


def test_snapshot_ignores_replace_refs_and_exports_the_requested_commit(tmp_path):
    source, revision, definition, git = repo(tmp_path)
    (source / "api.py").write_text("value = 999\n")
    git("add", "api.py")
    git("commit", "-m", "Replacement fixture")
    git("replace", revision, git("rev-parse", "HEAD"))
    destination = tmp_path / "out"
    destination.mkdir()
    builds._snapshot(source, revision, definition, destination)
    assert (destination / "api.py").read_text() == "value = 1\n"


@pytest.mark.parametrize("when", ["before_read", "after_read"])
def test_snapshot_validates_the_same_object_bytes_it_exports(tmp_path, monkeypatch, when):
    source, revision, definition, git = repo(tmp_path)
    oid = git("rev-parse", "HEAD:api.py")
    original = builds._command
    observed = []

    def command(argv, **kwargs):
        targeted = argv[-3:] == ["cat-file", "blob", oid]
        if targeted and when == "before_read":
            replace_loose_object(source, oid, "blob", b"value = 999\n")
        result = original(argv, **kwargs)
        if targeted:
            observed.append(True)
            if when == "after_read":
                replace_loose_object(source, oid, "blob", b"value = 999\n")
        return result

    monkeypatch.setattr(builds, "_command", command)
    destination = tmp_path / "out"
    destination.mkdir()
    if when == "before_read":
        with pytest.raises(builds.BuildFailure, match="build_source_object_invalid"):
            builds._snapshot(source, revision, definition, destination)
    else:
        builds._snapshot(source, revision, definition, destination)
        assert (destination / "api.py").read_text() == "value = 1\n"
    assert observed == [True]


def test_snapshot_uses_committed_bytes_without_export_attribute_transformations(tmp_path):
    source, _, definition, git = repo(tmp_path)
    (source / "api.py").write_text("version = '$Format:%H$'\n")
    (source / ".gitattributes").write_text("api.py export-subst\n")
    git("add", ".")
    git("commit", "-m", "Attributes fixture")
    revision = git("rev-parse", "HEAD")
    (source / ".git/info/attributes").write_text("api.py export-ignore\n")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    initial = builds._snapshot(source, revision, definition, first)
    (source / ".git/info/attributes").write_text("api.py export-subst\n")
    repeated = builds._snapshot(source, revision, definition, second)
    assert initial == repeated
    assert (
        (first / "api.py").read_text()
        == (second / "api.py").read_text()
        == "version = '$Format:%H$'\n"
    )


@pytest.mark.parametrize("kind", ["blob", "tree", "commit"])
def test_snapshot_bounds_object_reads(tmp_path, monkeypatch, kind):
    source, revision, definition, git = repo(tmp_path)
    if kind == "tree":
        for index in range(40):
            (source / f"entry-{index:03}").write_text("Small fixture")
        git("add", ".")
        git("commit", "-m", "Large tree fixture")
        revision = git("rev-parse", "HEAD")
        monkeypatch.setattr(builds, "MAX_SOURCE_METADATA", 1024)
    else:
        monkeypatch.setattr(builds, "MAX_FILE" if kind == "blob" else "MAX_SOURCE_METADATA", 4)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(builds.BuildFailure, match="build_output_limit|build_source_object_invalid"):
        builds._snapshot(source, revision, definition, destination)


@pytest.mark.parametrize(
    "invalid",
    [
        b"100644 missing-object\0short",
        b"missing-delimiter",
        b"100644 ../escape\0" + b"a" * 20,
        b"120000 link\0" + b"a" * 20,
    ],
)
def test_snapshot_rejects_malformed_or_unsafe_hash_valid_tree_objects(tmp_path, invalid):
    source, revision, definition, _ = repo(tmp_path)

    def store(kind, content):
        raw = kind.encode() + b" " + str(len(content)).encode() + b"\0" + content
        oid = hashlib.sha1(raw).hexdigest()
        path = source / ".git/objects" / oid[:2] / oid[2:]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(zlib.compress(raw))
        return oid

    tree_oid = store("tree", invalid)
    original = subprocess.check_output(["git", "-C", str(source), "cat-file", "commit", revision])
    revision = store("commit", b"tree " + tree_oid.encode() + b"\n" + original.split(b"\n", 1)[1])
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(
        builds.BuildFailure, match="build_source_object_invalid|build_archive_unsafe"
    ):
        builds._snapshot(source, revision, definition, destination)
    assert list(destination.iterdir()) == []


def test_snapshot_packed_objects_nested_names_and_executable_mode(tmp_path):
    source, _, definition, git = repo(tmp_path)
    nested = source / "공유 자료"
    nested.mkdir()
    (nested / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (nested / "test.sh").chmod(0o755)
    git("add", ".")
    git("commit", "-m", "Nested source fixture")
    revision = git("rev-parse", "HEAD")
    first, second = tmp_path / "loose", tmp_path / "packed"
    first.mkdir()
    second.mkdir()
    initial = builds._snapshot(source, revision, definition, first)
    git("repack", "-ad")
    assert list((source / ".git/objects/pack").glob("*.pack"))
    assert builds._snapshot(source, revision, definition, second) == initial
    assert (second / "공유 자료/test.sh").read_text() == (nested / "test.sh").read_text()
    assert (second / "공유 자료/test.sh").stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_ARCHIVE", "MAX_SOURCE_DEPTH"])
def test_snapshot_preserves_total_entry_byte_and_depth_bounds(tmp_path, monkeypatch, limit):
    source, _, definition, git = repo(tmp_path)
    (source / "one/two").mkdir(parents=True)
    (source / "one/two/file").write_bytes(b"x" * 2048)
    git("add", ".")
    git("commit", "-m", "Bounded source fixture")
    monkeypatch.setattr(builds, limit, 1024 if limit == "MAX_ARCHIVE" else 1)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(builds.BuildFailure, match="build_archive_limit"):
        builds._snapshot(source, git("rev-parse", "HEAD"), definition, destination)


def test_snapshot_denies_git_metadata_redirection_and_repository_mismatch(tmp_path):
    source, revision, definition, git = repo(tmp_path)
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    (redirected / ".git").write_text("gitdir: " + str(source / ".git"))
    with pytest.raises(builds.BuildFailure, match="build_source_denied"):
        builds._snapshot(redirected, revision, definition, tmp_path / "out")
    git("remote", "set-url", "origin", "https://example.test/other.git")
    with pytest.raises(builds.BuildFailure, match="build_source_mismatch"):
        builds._snapshot(source, revision, definition, tmp_path / "out")


def test_source_cannot_supply_archive_command(tmp_path):
    source, revision, definition, git = repo(tmp_path)
    marker = tmp_path / "host-command"
    git("config", "tar.tar.command", "touch " + str(marker))
    with pytest.raises(builds.BuildFailure, match="build_source_git_policy"):
        builds._snapshot(source, revision, definition, tmp_path / "out")
    assert not marker.exists()


def test_snapshot_denies_unapproved_revision_and_committed_credentials(tmp_path):
    source, revision, definition, git = repo(tmp_path)
    with pytest.raises(builds.BuildFailure, match="build_revision_required"):
        builds._snapshot(source, "HEAD", definition, tmp_path / "out")
    (source / ".env").write_text("SYNTHETIC_CREDENTIAL=fixture")
    git("add", ".env")
    git("commit", "-m", "Synthetic credential rejection fixture")
    with pytest.raises(builds.BuildFailure, match="build_archive_unsafe"):
        builds._snapshot(source, git("rev-parse", "HEAD"), definition, tmp_path / "out")


def test_export_ignore_cannot_hide_committed_credentials(tmp_path):
    source, _, definition, git = repo(tmp_path)
    (source / ".env").write_text("SYNTHETIC_CREDENTIAL=fixture")
    (source / ".gitattributes").write_text(".env export-ignore\n")
    git("add", ".env", ".gitattributes")
    git("commit", "-m", "Synthetic hidden credential rejection fixture")
    with pytest.raises(builds.BuildFailure, match="build_archive_unsafe"):
        builds._snapshot(source, git("rev-parse", "HEAD"), definition, tmp_path / "out")


def fake_docker(monkeypatch, *, fail_test=False, malicious_output=False):
    original, calls = builds._command, []
    state = {}

    def command(argv, **kwargs):
        if argv[0] == "git":
            return original(argv, **kwargs)
        calls.append((argv, kwargs))
        args = argv[1:]
        if args[0] == "create":
            state["identity"] = args[args.index("--name") + 1]
            state["labels"] = dict(
                args[i + 1].split("=", 1) for i, value in enumerate(args) if value == "--label"
            )
        if args[:2] == ["container", "inspect"]:
            return 0, json.dumps(
                [{"Id": state["identity"], "Image": IMAGE, "Config": {"Labels": state["labels"]}}]
            ).encode()
        if args[:2] == ["image", "inspect"]:
            if "--format" in args:
                image = ARTIFACT if args[2] == ARTIFACT else IMAGE
                return 0, (image + "\n").encode()
            return 0, json.dumps([{"Id": IMAGE, "Config": {}}]).encode()
        if args[0] == "exec" and list(builds.TEST_COMMAND) == args[2:] and fail_test:
            return 7, b"private app output must not become evidence"
        if args[0] == "exec" and args[-1] == builds.EXPORT_OUTPUT:
            value = (tarfile.SYMTYPE, "/etc/passwd") if malicious_output else b"<html>ok</html>"
            return 0, archive([("dist/index.html", value)])
        if args[0] == "build":
            Path(args[args.index("--iidfile") + 1]).write_text(ARTIFACT)
            recipe = Path(args[args.index("--file") + 1]).read_text()
            assert "RUN " not in recipe
            assert "COPY payload/ ./" in recipe
        return 0, b""

    monkeypatch.setattr(builds, "_command", command)
    return calls


def test_builder_observes_exit_codes_and_never_mounts_checkout_or_credentials(
    tmp_path, monkeypatch
):
    source, revision, definition, _ = repo(tmp_path)
    calls = fake_docker(monkeypatch)
    result = builds.build_app(
        source=source,
        revision=revision,
        expected_definition=definition.model_dump(),
        toolchain_image=IMAGE,
        work_root=tmp_path,
    )
    assert result.artifact_digest == ARTIFACT
    assert result.definition_digest == definition.content_digest()
    assert result.checks == {
        "resource_limits": 0,
        "profile": 0,
        "test": 0,
        "build": 0,
        "package": 0,
    }
    assert result.target_environment == "development"
    create = next(argv for argv, _ in calls if argv[1] == "create")
    assert all(
        flag in create
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--pull=never")
    )
    mount = create[create.index("--mount") + 1]
    assert mount.endswith(",dst=/source,readonly") and f"src={source}," not in mount
    assert all(set(kwargs["env"]) == {"PATH", "DOCKER_CONFIG"} for _, kwargs in calls)
    assert any(argv[1:3] == ["rm", "--force"] for argv, _ in calls)
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("kind", ["test", "output"])
def test_builder_does_not_accept_failed_check_or_unsafe_generated_artifact(
    tmp_path, monkeypatch, kind
):
    source, revision, definition, _ = repo(tmp_path)
    calls = fake_docker(monkeypatch, fail_test=kind == "test", malicious_output=kind == "output")
    with pytest.raises(builds.BuildFailure):
        builds.build_app(
            source=source,
            revision=revision,
            expected_definition=definition.model_dump(),
            toolchain_image=IMAGE,
            work_root=tmp_path,
        )
    assert not any(argv[1] == "build" for argv, _ in calls)
    assert any(argv[1:3] == ["rm", "--force"] for argv, _ in calls)


def test_cleanup_failure_preserves_uncertainty_and_build_identity(tmp_path, monkeypatch):
    source, revision, definition, _ = repo(tmp_path)
    calls = fake_docker(monkeypatch)
    original = builds._command

    def failed_cleanup(argv, **kwargs):
        code, output = original(argv, **kwargs)
        return (1, b"") if argv[1:3] == ["rm", "--force"] else (code, output)

    monkeypatch.setattr(builds, "_command", failed_cleanup)
    build_id = "e4a58f1f-a90f-4a53-b87f-2e1fa4588cad"
    with pytest.raises(builds.BuildFailure, match="build_cleanup_required"):
        builds.build_app(
            source=source,
            revision=revision,
            expected_definition=definition.model_dump(),
            toolchain_image=IMAGE,
            work_root=tmp_path,
            build_id=build_id,
        )
    create = next(argv for argv, _ in calls if argv[1] == "create")
    assert "miy.independent-build=" + build_id in create
    assert "miy-build-" + build_id.replace("-", "") in create


@pytest.mark.parametrize("foreign", [False, True])
def test_lost_create_response_reconciles_owned_identity_without_removing_foreign_container(
    tmp_path, monkeypatch, foreign
):
    source, revision, definition, _ = repo(tmp_path)
    calls = fake_docker(monkeypatch)
    original = builds._command

    def lost_response(argv, **kwargs):
        code, output = original(argv, **kwargs)
        if argv[1] == "create":
            raise builds.BuildFailure("build_timeout")
        if foreign and argv[1:3] == ["container", "inspect"]:
            record = json.loads(output)
            record[0]["Config"]["Labels"]["miy.independent-build"] = "someone-else"
            output = json.dumps(record).encode()
        return code, output

    monkeypatch.setattr(builds, "_command", lost_response)
    with pytest.raises(
        builds.BuildFailure, match="build_cleanup_required" if foreign else "build_timeout"
    ):
        builds.build_app(
            source=source,
            revision=revision,
            expected_definition=definition.model_dump(),
            toolchain_image=IMAGE,
            work_root=tmp_path,
        )
    assert any(argv[1:3] == ["rm", "--force"] for argv, _ in calls) is not foreign
