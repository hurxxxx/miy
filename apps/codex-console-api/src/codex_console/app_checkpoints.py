"""Bounded local app checkpoints; app agents cannot write Git metadata themselves."""

import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import app_sources, git, remote_environments
from .errors import ConsoleError

MAX_FILES = 2048
MAX_TOTAL_BYTES = 32 * 1024 * 1024
_OID = re.compile(rb"[0-9a-f]{40}")


def _configuration(root, args, index=None):
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_AUTHOR_NAME": "MIY Workbench",
        "GIT_AUTHOR_EMAIL": "workbench@local.invalid",
        "GIT_COMMITTER_NAME": "MIY Workbench",
        "GIT_COMMITTER_EMAIL": "workbench@local.invalid",
    }
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    config = {
        "core.hooksPath": "/dev/null",
        "core.fsmonitor": "false",
        "commit.gpgsign": "false",
        "gc.auto": "0",
        "core.attributesFile": "/dev/null",
        "core.excludesFile": "/dev/null",
        "core.splitIndex": "false",
        "index.sparse": "false",
        "protocol.allow": "never",
    }
    argv = [
        "git",
        "--no-pager",
        *[value for pair in config.items() for value in ("-c", "=".join(pair))],
        "-C",
        str(root),
        *args,
    ]
    return argv, env


def _git(root, *args, data=None, index=None, allowed_codes=(0,)):
    argv, env = _configuration(root, args, index)
    # A regular temporary stdin avoids blocking a parent writing a full pipe.
    with tempfile.TemporaryFile() as source:
        if data is not None:
            source.write(data)
            source.seek(0)
        with subprocess.Popen(
            argv, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
        ) as process:
            output = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if not selector.select(timeout=0.1):
                            continue
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > git.MAX_BYTES:
                            raise ConsoleError("output_too_large")
                    else:
                        raise ConsoleError("git_timeout")
                if process.wait(timeout=1) not in allowed_codes:
                    raise ConsoleError("app_checkpoint_conflict", 409)
                return bytes(output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def _ack(process, expected):
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 15
        while bytes(output) != expected and time.monotonic() < deadline:
            if not selector.select(timeout=0.1):
                continue
            chunk = os.read(process.stdout.fileno(), 1024)
            output.extend(chunk)
            if not chunk or not expected.startswith(output):
                raise ConsoleError("app_checkpoint_conflict", 409)
    if bytes(output) != expected:
        raise ConsoleError("git_timeout")


def _update_head(root, branch, commit, head, head_file):
    # Public Git 2.43 transaction API owns the branch and implicit HEAD locks.
    # Verify the symbolic target while prepared, before allowing its CAS commit.
    argv, env = _configuration(root, ("update-ref", "-m", "MIY application checkpoint", "--stdin"))
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        bufsize=0,
    ) as process:
        try:
            process.stdin.write(
                b"start\nupdate " + branch.encode() + b" " + commit + b" " + head + b"\nprepare\n"
            )
            _ack(process, b"start: ok\nprepare: ok\n")
            if (
                not (root / ".git/HEAD.lock").is_file()
                or git.read_worktree_file(root / ".git", "HEAD", missing_ok=False) != head_file
            ):
                raise ConsoleError("app_checkpoint_conflict", 409)
            process.stdin.write(b"commit\n")
            _ack(process, b"commit: ok\n")
            process.stdin.close()
            if process.wait(timeout=2):
                raise ConsoleError("app_checkpoint_conflict", 409)
        finally:
            if not process.stdin.closed:
                # EOF aborts a prepared but uncommitted transaction in Git.
                process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _metadata(root):
    metadata = root / ".git"
    count = 0
    for directory, dirs, files in os.walk(metadata, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(directory) / name
            info = path.lstat()
            count += 1
            if (
                count > 50000
                or stat.S_ISLNK(info.st_mode)
                or (
                    not stat.S_ISDIR(info.st_mode)
                    and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                )
            ):
                raise ConsoleError("app_checkpoint_metadata_denied", 403)
    if (metadata / "objects/info/alternates").exists():
        raise ConsoleError("app_checkpoint_metadata_denied", 403)
    keys = (
        _git(root, "config", "--local", "--no-includes", "--name-only", "--list")
        .decode()
        .lower()
        .splitlines()
    )
    if any(
        key.startswith(("include.", "includeif."))
        or key in {"core.worktree", "extensions.worktreeconfig"}
        for key in keys
    ):
        raise ConsoleError("app_checkpoint_metadata_denied", 403)
    return metadata


@contextmanager
def _lock(path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise ConsoleError("app_checkpoint_busy", 409) from None
    inode = os.fstat(fd).st_ino
    try:
        yield fd
    finally:
        os.close(fd)
        try:
            if path.lstat().st_ino == inode:
                path.unlink()
        except FileNotFoundError:
            pass


def _paths(raw):
    try:
        return [item.decode("utf-8") for item in raw.split(b"\0") if item]
    except UnicodeError:
        raise ConsoleError("app_checkpoint_path_denied", 403) from None


def _tree(root, head):
    result = {}
    for item in _git(root, "ls-tree", "-r", "-z", head).split(b"\0"):
        if not item:
            continue
        header, path = item.split(b"\t", 1)
        mode, kind, oid = header.split()
        if mode not in {b"100644", b"100755"} or kind != b"blob" or not _OID.fullmatch(oid):
            raise ConsoleError("app_checkpoint_path_denied", 403)
        name = _paths(path + b"\0")[0]
        git.safe_path(root, name)
        result[name] = (mode, oid)
    return result


def _unstaged(root, baseline):
    index = {}
    for item in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not item:
            continue
        header, path = item.split(b"\t", 1)
        mode, oid, stage = header.split()
        if stage != b"0":
            raise ConsoleError("app_checkpoint_staged", 409)
        index[_paths(path + b"\0")[0]] = (mode, oid)
    if index != baseline:
        raise ConsoleError("app_checkpoint_staged", 409)


def _visible_files(root):
    result, seen = set(), 0
    # Git ls-files silently omits FIFOs and sockets. Walk without following
    # links, prune Git-ignored directories, then explicitly reject special files.
    for directory, dirs, files, fd in os.fwalk(root, follow_symlinks=False):
        relative = Path(directory).relative_to(root)
        if relative == Path("."):
            dirs[:] = [name for name in dirs if name != ".git"]
        names = [*dirs, *files]
        seen += len(names)
        if seen > MAX_FILES * 2:
            raise ConsoleError("app_checkpoint_too_large", 422)
        paths = [(relative / name).as_posix() for name in names]
        ignored = set(
            _paths(
                _git(
                    root,
                    "check-ignore",
                    "--stdin",
                    "-z",
                    data=b"\0".join(path.encode() for path in paths) + (b"\0" if paths else b""),
                    allowed_codes=(0, 1),
                )
            )
        )
        dirs[:] = [name for name in dirs if (relative / name).as_posix() not in ignored]
        for name, path in zip(names, paths, strict=True):
            if path in ignored:
                continue
            git.safe_path(root, path)
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                result.add(path)
            elif not stat.S_ISDIR(info.st_mode):
                raise ConsoleError("path_denied", 403)
    return result


def _snapshot(root, baseline):
    paths = set(baseline) | _visible_files(root)
    if len(paths) > MAX_FILES:
        raise ConsoleError("app_checkpoint_too_large", 422)
    result, total = {}, 0
    for relative in sorted(paths):
        try:
            data = git.read_worktree_file(root, relative, missing_ok=False)
        except ConsoleError as exc:
            if exc.code == "reference_not_found" and relative in baseline:
                continue
            raise
        info = (root / relative).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConsoleError("path_denied", 403)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ConsoleError("app_checkpoint_too_large", 422)
        result[relative] = (b"100755" if info.st_mode & 0o111 else b"100644", data)
    return result


def checkpoint(settings, task):
    source = (task.context or {}).get("source_binding")
    if not source:
        raise ConsoleError("app_checkpoint_source_required", 403)
    app_sources.require_task_source(settings, task)
    if remote_environments.for_task(settings, task) is None:
        raise ConsoleError("app_executor_unavailable", 503)
    root = app_sources.task_workspace(settings, task)
    if (
        root == settings.workspace
        or root.is_relative_to(settings.workspace)
        or settings.workspace.is_relative_to(root)
    ):
        raise ConsoleError("app_checkpoint_source_required", 403)
    metadata = _metadata(root)
    # The prepared Git transaction fences HEAD and its branch before cutover.
    # Detached heads are deliberately unsupported by this initial profile.
    with ExitStack() as stack:
        index_fd = stack.enter_context(_lock(metadata / "index.lock"))
        head_file = git.read_worktree_file(metadata, "HEAD", missing_ok=False)
        if not head_file.startswith(b"ref: refs/heads/") or b"\n" in head_file.rstrip(b"\n"):
            raise ConsoleError("app_checkpoint_named_branch_required", 422)
        branch = head_file.removeprefix(b"ref: ").strip().decode("utf-8")
        _git(root, "check-ref-format", branch)
        head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
        if not _OID.fullmatch(head):
            raise ConsoleError("app_checkpoint_source_required", 403)
        baseline = _tree(root, head.decode())
        _unstaged(root, baseline)
        original = _snapshot(root, baseline)
        with tempfile.TemporaryDirectory(prefix="miy-checkpoint-", dir=metadata) as temporary:
            index = Path(temporary) / "index"
            _git(root, "read-tree", "--empty", index=index)
            entries = bytearray()
            inputs = []
            for number, (_, data) in enumerate(original.values()):
                blob = Path(temporary) / f"blob-{number}"
                blob.write_bytes(data)
                inputs.append(blob.relative_to(root).as_posix().encode())
            hashes = _git(
                root,
                "hash-object",
                "-w",
                "--no-filters",
                "--stdin-paths",
                data=b"\n".join(inputs) + (b"\n" if inputs else b""),
            ).splitlines()
            if len(hashes) != len(original):
                raise ConsoleError("app_checkpoint_conflict", 409)
            for (relative, (mode, _)), oid in zip(original.items(), hashes, strict=True):
                if not _OID.fullmatch(oid):
                    raise ConsoleError("app_checkpoint_conflict", 409)
                if (
                    baseline.get(relative) != (mode, oid)
                    and not (root / relative).is_relative_to(Path(task.root))
                    and relative != "app.manifest.json"
                ):
                    raise ConsoleError("app_checkpoint_path_denied", 403)
                entries.extend(mode + b" " + oid + b"\t" + relative.encode() + b"\0")
            for deleted in set(baseline) - set(original):
                if not (root / deleted).is_relative_to(Path(task.root)):
                    raise ConsoleError("app_checkpoint_path_denied", 403)
            _git(root, "update-index", "-z", "--index-info", data=bytes(entries), index=index)
            tree = _git(root, "write-tree", index=index).strip()
            if original != _snapshot(root, baseline):
                raise ConsoleError("app_checkpoint_changed", 409)
            if (
                git.read_worktree_file(metadata, "HEAD", missing_ok=False) != head_file
                or _git(root, "rev-parse", "HEAD").strip() != head
            ):
                raise ConsoleError("app_checkpoint_conflict", 409)
            if tree == _git(root, "rev-parse", "HEAD^{tree}").strip():
                return {"source_revision": head.decode(), "created": False}
            content = git.read_worktree_file(Path(temporary), "index", missing_ok=False)
            with os.fdopen(os.dup(index_fd), "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            commit = _git(
                root,
                "commit-tree",
                tree.decode(),
                "-p",
                head.decode(),
                data=b"MIY application checkpoint\n",
            ).strip()
            if not _OID.fullmatch(commit):
                raise ConsoleError("app_checkpoint_conflict", 409)
            _update_head(root, branch, commit, head, head_file)
            # As in Git commit, ref and index are individually atomic. A process
            # loss between them leaves visible staged differences, never a replay.
            os.replace(metadata / "index.lock", metadata / "index")
            return {"source_revision": commit.decode(), "created": True}
