"""Server-owned linked worktrees and app-subtree checkpoints using native Git."""

import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from . import app_checkpoints as checkpoints
from . import app_sources, app_starters, git
from .errors import ConsoleError

OID = re.compile(r"[0-9a-f]{40}")


def sdk_import(entries, modes):
    """Import only an exact owned SDK, recording any v2-to-v3 migration."""
    from . import toolchain_profiles

    current = toolchain_profiles._sdk_pin()
    prefix = "vendor/miy-app-sdk/"
    required = {"package.json", "src/index.mjs", "src/file-picker.mjs", "src/index.test.mjs"}
    names = {name[len(prefix) :] for name in entries if name.startswith(prefix)}
    if names not in (required, required | {"README.md"}):
        raise ConsoleError("workspace_source_invalid", 422)

    def matches(pin):
        return all(
            hashlib.sha256(entries[prefix + name]).hexdigest()
            == pin["source_inputs"]["packages/app-sdk/" + name]
            for name in names
        )

    if matches(current):
        return current
    previous = toolchain_profiles._sdk_pin(toolchain_profiles.LEGACY_SDK_PROFILE)
    if not matches(previous) or "SDK_IMPORT.md" in entries:
        raise ConsoleError("workspace_source_invalid", 422)
    starter = app_starters.bundle()["templates"]["basic"]["files"]
    root = Path(__file__).resolve().parents[4]
    verify = sdk_verifier()
    for name in sorted(names):
        path = prefix + name
        value = (
            verify.regular_bytes(root / "packages/app-sdk/README.md", git.MAX_BYTES)
            if name == "README.md"
            else starter[path].encode()
        )
        if (
            hashlib.sha256(value).hexdigest()
            != current["source_inputs"]["packages/app-sdk/" + name]
        ):
            raise ConsoleError("app_setup_bundle_invalid", 503)
        entries[path] = value
    entries["SDK_IMPORT.md"] = (
        "# 기존 앱 SDK 가져오기 기록\n\n"
        "이 작업환경 사본의 검증된 공개 SDK를 현재 관리형 개발 환경에 맞춰 전환했습니다.\n"
        "원본 저장소, 앱 업무 코드, 권한, 의존성 선언은 변경하지 않았습니다.\n\n"
        f"- 이전 SDK: `{previous['toolchain_id']}`\n"
        f"- 이전 pin SHA256: `{toolchain_profiles.LEGACY_SDK_PIN_SHA256}`\n"
        f"- 현재 SDK: `{current['toolchain_id']}`\n"
        f"- 현재 pin SHA256: `{toolchain_profiles.SDK_PIN_SHA256}`\n\n"
        "교체한 공개 파일:\n\n" + "".join(f"- `{prefix + name}`\n" for name in sorted(names))
    ).encode()
    modes["SDK_IMPORT.md"] = b"100644"
    return current


def sdk_verifier():
    """Reuse the owned source-mount verifier; never import app code."""
    path = Path(__file__).resolve().parents[4] / "scripts/verify-native-sdk-toolchain.py"
    spec = importlib.util.spec_from_file_location("workspace_sdk_verify", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration(root, metadata):
    """Allow native worktreeConfig while checking each owned settings file."""
    commands = [("config", "--local", "--no-includes", "--name-only", "--list")]
    path = metadata / "config.worktree"
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    if info is not None:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o022
            or info.st_size > 65536
        ):
            raise ConsoleError("workspace_repository_denied", 403)
        commands.append(("config", "--file", str(path), "--no-includes", "--name-only", "--list"))
    for command in commands:
        keys = git.git(root, *command, limit=65536).decode().lower().splitlines()
        if any(
            key.startswith(("include.", "includeif.")) or key == "core.worktree" for key in keys
        ):
            raise ConsoleError("workspace_repository_denied", 403)
    # Merged native settings include both shared and enabled worktree scopes;
    # the existing conversion-helper/partial-clone policy remains unchanged.
    app_sources.require_git_policy(root)


def revision(root):
    value = git.git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if not OID.fullmatch(value):
        raise ConsoleError("workspace_source_invalid", 422)
    return value


def reviewed_merge_tree(item, saved, merged):
    """Prove the normal, unsquashed merge of the exact reviewed commits."""
    from .app_checkpoints import _git

    root = Path(item.repository_root)
    source, target = saved.get("source_revision"), saved.get("target_revision")
    if not all(OID.fullmatch(value or "") for value in (merged, source, target)):
        raise ConsoleError("workspace_operation_unknown", 409)
    try:
        parents = _git(root, "rev-list", "--parents", "-n", "1", merged).decode().split()
        if parents != [merged, target, source]:
            raise ValueError
        keys = git.git(root, "config", "--name-only", "--list", limit=65536).decode().lower()
        if any(re.fullmatch(r"merge\..*\.driver", key) for key in keys.splitlines()):
            # Tree verification must never run a repository-defined external driver.
            raise ValueError
        expected = _git(root, "merge-tree", "--write-tree", "--no-messages", target, source)
        actual = _git(root, "rev-parse", "--verify", merged + "^{tree}")
        tree = expected.decode().strip()
        if not OID.fullmatch(tree) or actual.decode().strip() != tree:
            raise ValueError
        _git(root, "merge-base", "--is-ancestor", merged, "refs/remotes/origin/dev")
        return tree
    except (ConsoleError, ValueError, UnicodeError):
        raise ConsoleError("workspace_operation_unknown", 409) from None


def repository(settings):
    root = settings.workspace
    settings.require_allowed_paths(root)
    if root.resolve() != root or git.repository_root(root) != root:
        raise ConsoleError("workspace_repository_denied", 403)
    metadata = root / ".git"
    if metadata.is_symlink() or not metadata.is_dir() or metadata.stat().st_uid != os.getuid():
        raise ConsoleError("workspace_repository_denied", 403)
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        actual = Path(git.git(root, "rev-parse", "--path-format=absolute", flag).decode().strip())
        if actual != metadata or actual.resolve() != metadata:
            raise ConsoleError("workspace_repository_denied", 403)
    configuration(root, metadata)
    return root


def validate(settings, item):
    root = Path(item.worktree_root)
    common = Path(item.common_dir)
    original = repository(settings)
    expected_root = settings.worktree_root / "managed" / item.id
    if (
        root != expected_root
        or root.resolve() != root
        or Path(item.repository_root) != original
        or common != original / ".git"
        or git.repository_root(root) != root
    ):
        raise ConsoleError("workspace_source_changed", 409)
    settings.require_allowed_paths(root, common)
    metadata = Path(git.git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    actual_common = Path(
        git.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    )
    if (
        actual_common != common
        or actual_common.resolve() != common
        or metadata.resolve() != metadata
        or metadata.parent != common / "worktrees"
        or str(metadata) != item.git_dir
        or git.read_worktree_file(metadata, "gitdir", missing_ok=False).decode().strip()
        != str(root / ".git")
        or gitfile(root) != "gitdir: " + str(metadata)
        or git.git(root, "symbolic-ref", "HEAD").decode().strip() != "refs/heads/" + item.branch
    ):
        raise ConsoleError("workspace_source_changed", 409)
    configuration(root, metadata)
    remote = git.git(root, "remote", "get-url", "origin", limit=4096).decode().strip()
    if app_sources.repository_identity(remote) != app_sources.repository_identity(item.repository):
        raise ConsoleError("workspace_source_changed", 409)
    return root, git.safe_path(root, item.source_directory), metadata


def gitfile(root):
    try:
        fd = os.open(root / ".git", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_mode & 0o022
                or info.st_size > 4096
            ):
                raise ValueError
            return source.read(4097).decode().strip()
    except (OSError, ValueError, UnicodeError):
        raise ConsoleError("workspace_source_changed", 409) from None


def create(settings, item, project):
    original = repository(settings)
    root = Path(item.worktree_root)
    if (
        item.base_revision is not None
        or item.source_revision is not None
        or item.git_dir is not None
    ):
        raise ConsoleError("workspace_source_changed", 409)
    registered = git.git(original, "worktree", "list", "--porcelain", "-z").split(b"\0")
    branch = git.git(
        original, "for-each-ref", "--format=%(refname)", "refs/heads/" + item.branch
    ).strip()
    if (
        root.exists()
        or root.is_symlink()
        or branch
        or os.fsencode("worktree " + str(root)) in registered
    ):
        raise ConsoleError("workspace_source_collision", 409)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.parent.resolve() != root.parent or root.parent.stat().st_uid != os.getuid():
        raise ConsoleError("workspace_source_collision", 409)
    # Fetch only the authorized permanent integration branch, never current dev files.
    git.git(
        original,
        "fetch",
        "--no-tags",
        "origin",
        "refs/heads/dev:refs/remotes/origin/dev",
        transport=True,
    )
    base = (
        git.git(original, "rev-parse", "--verify", "refs/remotes/origin/dev^{commit}")
        .decode()
        .strip()
    )
    if not OID.fullmatch(base):
        raise ConsoleError("workspace_source_invalid", 422)
    git.git(original, "worktree", "add", "-b", item.branch, str(root), base)
    item.base_revision = item.source_revision = base
    item.git_dir = git.git(root, "rev-parse", "--absolute-git-dir").decode().strip()
    _, app, _ = validate(settings, item)
    if not app.exists():
        if getattr(project, "initial_source", None):
            import_source(settings, item, project.initial_source)
        elif project.reuse_decision != "new":
            raise ConsoleError("workspace_app_missing", 422)
        else:
            app.mkdir(parents=True, mode=0o700)
            from .app_source_setup import copy_files, directory

            entries = app_starters.render(
                "basic",
                app_id=item.app_id,
                title=project.title,
                repository=item.repository,
                expected_digest=app_starters.bundle()["bundle_digest"],
            )
            definition = json.loads(entries["app.manifest.json"])
            definition["source"]["directory"] = item.source_directory
            entries["app.manifest.json"] = (
                json.dumps(definition, ensure_ascii=False, indent=2) + "\n"
            ).encode()
            with directory(app) as descriptor:
                copy_files(descriptor, entries)
    result = checkpoint(settings, item)
    return {**result, "base_revision": base, "git_dir": item.git_dir}


def import_source(settings, item, selected):
    """Copy a bounded clean committed app snapshot, preserving its independent repo."""
    source = app_sources.require_source_root(settings, selected["repository_root"])
    if git.status(source)["changed"]:
        raise ConsoleError("app_source_dirty", 409)
    head = revision(source)
    relative = selected["directory"]
    if not isinstance(relative, str) or len(relative) > 200:
        raise ConsoleError("workspace_source_invalid", 422)
    selected_tree = head
    if relative != ".":
        if (
            not relative
            or relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
        ):
            raise ConsoleError("workspace_source_invalid", 422)
        git.safe_path(source, relative)
        selected_entries = git.git(source, "ls-tree", "-z", head, "--", relative).split(b"\0")
        if len(selected_entries) != 2 or selected_entries[-1]:
            raise ConsoleError("workspace_source_invalid", 422)
        header, raw = selected_entries[0].split(b"\t", 1)
        mode, kind, oid = header.split()
        if raw.decode("utf-8") != relative or mode != b"040000" or kind != b"tree":
            raise ConsoleError("workspace_source_invalid", 422)
        selected_tree = oid.decode()
    prefix = "" if relative == "." else relative + "/"
    entries, modes, total = {}, {}, 0

    def add(entry, *, root_manifest=False):
        nonlocal total
        header, raw = entry.split(b"\t", 1)
        mode, kind, oid = header.split()
        name = raw.decode("utf-8")
        if (
            mode not in (b"100644", b"100755")
            or kind != b"blob"
            or not OID.fullmatch(oid.decode())
            or (root_manifest and name != "app.manifest.json")
        ):
            raise ConsoleError("app_checkpoint_path_denied", 403)
        if name in entries:
            # Root and subtree declarations are ambiguous even if identical.
            raise ConsoleError("workspace_source_invalid", 422)
        git.safe_path(source, name if root_manifest else prefix + name)
        data = git.git(source, "cat-file", "blob", oid.decode())
        if len(data) > (65536 if name == "app.manifest.json" else git.MAX_BYTES):
            raise ConsoleError("workspace_source_invalid", 422)
        total += len(data)
        if total > checkpoints.MAX_TOTAL_BYTES or len(entries) >= checkpoints.MAX_FILES:
            raise ConsoleError("app_checkpoint_too_large", 422)
        entries[name] = data
        modes[name] = mode

    if relative != ".":
        for entry in git.git(source, "ls-tree", "-z", head, "--", "app.manifest.json").split(b"\0"):
            if entry:
                add(entry, root_manifest=True)
    for entry in git.git(source, "ls-tree", "-r", "-z", selected_tree).split(b"\0"):
        if entry:
            add(entry)
    try:
        definition = json.loads(entries["app.manifest.json"])
        app_sources.validator().validate(definition)
        original = definition["source"]
        remote = git.git(source, "remote", "get-url", "origin", limit=4096).decode().strip()
        if (
            definition["app_id"] != item.app_id
            or original.get("directory", ".") != relative
            or urlsplit(original["repository"]).scheme != "https"
            or app_sources.repository_identity(original["repository"])
            != app_sources.repository_identity(remote)
        ):
            raise ValueError
        definition["source"] = {"repository": item.repository, "directory": item.source_directory}
        app_sources.validator().validate(definition)
        entries["app.manifest.json"] = (
            json.dumps(definition, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        if len(entries["app.manifest.json"]) > 65536:
            raise ValueError
        if sum(map(len, entries.values())) > checkpoints.MAX_TOTAL_BYTES:
            raise ConsoleError("app_checkpoint_too_large", 422)
    except (ValueError, KeyError, TypeError, RecursionError, app_sources.ValidationError):
        raise ConsoleError("workspace_source_invalid", 422) from None
    pin = sdk_import(entries, modes)
    if (
        len(entries) > checkpoints.MAX_FILES
        or sum(map(len, entries.values())) > checkpoints.MAX_TOTAL_BYTES
        or any(len(value) > git.MAX_BYTES for value in entries.values())
    ):
        raise ConsoleError("app_checkpoint_too_large", 422)
    app = git.safe_path(Path(item.worktree_root), item.source_directory)
    app.mkdir(parents=True, mode=0o700)
    from .app_source_setup import DIRECTORY_FLAGS, copy_files, directory

    with directory(app) as descriptor:
        copy_files(descriptor, entries)
        # Git owns only the executable distinction. Keep it without copying
        # group/other access, set-id bits or original filesystem permissions.
        for name, mode in modes.items():
            with ExitStack() as stack:
                parent = descriptor
                for part in Path(name).parts[:-1]:
                    parent = os.open(part, DIRECTORY_FLAGS, dir_fd=parent)
                    stack.callback(os.close, parent)
                file = os.open(
                    Path(name).name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=parent,
                )
                stack.callback(os.close, file)
                info = os.fstat(file)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise ConsoleError("app_checkpoint_path_denied", 403)
                os.fchmod(file, 0o700 if mode == b"100755" else 0o600)
                os.fsync(file)
        os.fsync(descriptor)
    dependencies = app / "node_modules"
    if not dependencies.exists():
        dependencies.mkdir(mode=0o700)
    verify = sdk_verifier()
    try:
        verify.verify_source_mounts(app, pin, managed=True)
    except (verify.ToolchainRefused, OSError):
        raise ConsoleError("workspace_source_invalid", 422) from None


def manifest(settings, item):
    root, _, _ = validate(settings, item)
    raw = git.read_worktree_file(
        root, item.source_directory + "/app.manifest.json", missing_ok=False
    )
    if len(raw) > 65536:
        raise ConsoleError("workspace_source_invalid", 422)
    try:
        value = json.loads(raw)
        app_sources.validator().validate(value)
        if (
            value["app_id"] != item.app_id
            or value["source"].get("directory", ".") != item.source_directory
            or app_sources.repository_identity(value["source"]["repository"])
            != app_sources.repository_identity(item.repository)
        ):
            raise ValueError
        return value, "sha256:" + hashlib.sha256(raw).hexdigest()
    except (ValueError, KeyError, TypeError, RecursionError, app_sources.ValidationError):
        raise ConsoleError("workspace_source_invalid", 422) from None


def checkpoint(settings, item, *, check=None):
    """Keep the full HEAD tree, replacing only bounded regular files in this app."""
    root, app, metadata = validate(settings, item)
    if check:
        check()
    prefix = item.source_directory + "/"
    with ExitStack() as stack:
        index_fd = stack.enter_context(checkpoints._lock(metadata / "index.lock"))
        head_file = git.read_worktree_file(metadata, "HEAD", missing_ok=False)
        head = revision(root)
        if head != item.source_revision:
            raise ConsoleError("workspace_source_changed", 409)
        # Any staged change, including an external one, is evidence to hold, not rewrite.
        checkpoints._git(root, "diff", "--cached", "--quiet", "HEAD", "--")
        checkpoints._git(
            root, "diff", "--quiet", "HEAD", "--", ".", ":(exclude)" + item.source_directory
        )
        baseline = {}
        for entry in checkpoints._git(
            root, "ls-tree", "-r", "-z", head, "--", item.source_directory
        ).split(b"\0"):
            if not entry:
                continue
            header, path = entry.split(b"\t", 1)
            mode, kind, oid = header.split()
            name = path.decode("utf-8")
            if (
                not name.startswith(prefix)
                or mode not in (b"100644", b"100755")
                or kind != b"blob"
                or not checkpoints._OID.fullmatch(oid)
            ):
                raise ConsoleError("app_checkpoint_path_denied", 403)
            baseline[name[len(prefix) :]] = (mode, oid)
        original = checkpoints._snapshot(app, baseline)
        with tempfile.TemporaryDirectory(prefix="miy-checkpoint-", dir=metadata) as temporary:
            index = Path(temporary) / "index"
            checkpoints._git(root, "read-tree", head, index=index)
            entries = bytearray()
            for deleted in sorted(set(baseline) - set(original)):
                entries.extend(b"0 " + b"0" * 40 + b"\t" + (prefix + deleted).encode() + b"\0")
            for number, (relative, (mode, data)) in enumerate(original.items()):
                blob = Path(temporary) / str(number)
                blob.write_bytes(data)
                oid = checkpoints._git(root, "hash-object", "-w", "--no-filters", str(blob)).strip()
                if not checkpoints._OID.fullmatch(oid):
                    raise ConsoleError("app_checkpoint_conflict", 409)
                entries.extend(mode + b" " + oid + b"\t" + (prefix + relative).encode() + b"\0")
            checkpoints._git(
                root, "update-index", "-z", "--index-info", data=bytes(entries), index=index
            )
            tree = checkpoints._git(root, "write-tree", index=index).strip()
            if original != checkpoints._snapshot(app, baseline):
                raise ConsoleError("app_checkpoint_changed", 409)
            definition, digest = manifest(settings, item)
            if tree == checkpoints._git(root, "rev-parse", "HEAD^{tree}").strip():
                return {
                    "source_revision": head,
                    "created": False,
                    "source_manifest": definition,
                    "source_digest": digest,
                }
            content = git.read_worktree_file(Path(temporary), "index", missing_ok=False)
            with os.fdopen(os.dup(index_fd), "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            commit = checkpoints._git(
                root,
                "commit-tree",
                tree.decode(),
                "-p",
                head,
                data=b"MIY workspace app checkpoint\n",
            ).strip()
            if check:
                check()
            checkpoints._update_head(
                root, "refs/heads/" + item.branch, commit, head.encode(), head_file, metadata
            )
            os.replace(metadata / "index.lock", metadata / "index")
            return {
                "source_revision": commit.decode(),
                "created": True,
                "source_manifest": definition,
                "source_digest": digest,
            }


def remove(settings, item):
    """Exact owned removal tolerates an acknowledged worktree removal before ref CAS."""
    original = repository(settings)
    root = Path(item.worktree_root)
    expected = settings.worktree_root / "managed" / item.id
    if (
        root != expected
        or Path(item.repository_root) != original
        or Path(item.common_dir) != original / ".git"
    ):
        raise ConsoleError("workspace_source_changed", 409)
    if root.exists() or root.is_symlink():
        root, _, _ = validate(settings, item)
        if git.status(root)["changed"] or revision(root) != item.source_revision:
            raise ConsoleError("workspace_source_dirty", 409)
        git.git(original, "worktree", "remove", str(root))
    else:
        metadata = Path(item.git_dir)
        if (
            metadata.parent != original / ".git/worktrees"
            or metadata.exists()
            or metadata.is_symlink()
        ):
            raise ConsoleError("workspace_source_changed", 409)
        registrations = git.git(original, "worktree", "list", "--porcelain", "-z")
        if ("worktree " + str(root)).encode() in registrations.split(b"\0"):
            raise ConsoleError("workspace_source_changed", 409)
    ref = "refs/heads/" + item.branch
    refs = (
        git.git(original, "for-each-ref", "--format=%(objectname) %(refname)", ref).decode().split()
    )
    if not refs:
        return
    if refs != [item.source_revision, ref]:
        raise ConsoleError("workspace_remote_branch_changed", 409)
    # Native expected object CAS preserves any newer ref.
    git.git(original, "update-ref", "-d", ref, item.source_revision)
