"""Bounded Git access; no shell, external diff driver, arbitrary cwd or raw file endpoint."""

import os
import selectors
import stat
import subprocess
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from .errors import ConsoleError

MAX_BYTES = 2 * 1024 * 1024


def mounted_directory_options(root: Path) -> list[str]:
    """Trust only a root-owned mount point with this owner's real Git metadata.

    Nested Docker bind mounts can report UID 0 on the checkout directory while
    its .git belongs to the service owner. Never trust a wildcard, foreign
    metadata or a symlink; source adapters still enforce their own Git policy.
    """
    if os.getuid() == 0:
        return []
    for candidate in (root, *root.parents):
        metadata = candidate / ".git"
        try:
            info = metadata.lstat()
        except FileNotFoundError:
            continue
        if (
            candidate.stat().st_uid == 0
            and info.st_uid == os.getuid()
            and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
        ):
            return ["-c", f"safe.directory={candidate}"]
        break
    return []


def git(root: Path, *args: str, limit: int = MAX_BYTES, transport: bool = False) -> bytes:
    env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_ALLOW_PROTOCOL="",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
    )
    if transport:
        # Only the managed-workspace broker calls this for fixed origin commands.
        # SSH/HTTPS credentials stay in the operator's native credential owner.
        env["GIT_ALLOW_PROTOCOL"] = "ssh:https"
        for key in ("HOME", "SSH_AUTH_SOCK"):
            if key in os.environ:
                env[key] = os.environ[key]
        if env.get("HOME"):
            home = Path(env["HOME"])
            if not home.is_absolute():
                raise ConsoleError("workspace_repository_denied", 403)
            for config in (home / ".gitconfig", home / ".config/git/config"):
                try:
                    info = config.lstat()
                except FileNotFoundError:
                    continue
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or info.st_mode & 0o022
                    or info.st_size > 65536
                ):
                    raise ConsoleError("workspace_repository_denied", 403)
            # Native operator credentials are available only for broker transport.
            # Source reads/checkpoints still ignore global/system Git settings.
            env.pop("GIT_CONFIG_GLOBAL")
    process = subprocess.Popen(
        [
            "git",
            "--no-pager",
            *mounted_directory_options(Path(root)),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "-c",
            "log.showSignature=false",
            "-C",
            str(root),
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if not selector.select(timeout=0.2):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    raise ConsoleError("output_too_large")
            else:
                raise ConsoleError("git_timeout")
        if process.wait(timeout=1) != 0:
            raise ConsoleError("git_unavailable")
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ConsoleError("path_denied", 403)
    if any(
        part == ".git"
        or part == ".secure"
        or part == "secrets"
        or part.startswith(".auth_info")
        or (part.startswith(".env") and part != ".env.example")
        or part in ("auth.json", "id_rsa", "id_ed25519")
        for part in path.parts
    ):
        raise ConsoleError("path_denied", 403)
    candidate = root / path
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ConsoleError("path_denied", 403)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ConsoleError("path_denied", 403)
    return candidate


def read_worktree_file(root: Path, relative: str, *, missing_ok: bool = True) -> bytes:
    safe_path(root, relative)
    # Pin each directory and reject links at open time too: an agent may replace
    # a path between the status scan and the file read.
    try:
        with ExitStack() as stack:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open(root, flags)
            stack.callback(os.close, directory)
            parts = Path(relative).parts
            for part in parts[:-1]:
                directory = os.open(part, flags, dir_fd=directory)
                stack.callback(os.close, directory)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as source:
                metadata = os.fstat(source.fileno())
                if metadata.st_nlink != 1:
                    raise ConsoleError("path_denied", 403)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                    raise ConsoleError("output_too_large")
                data = source.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ConsoleError("output_too_large")
                return data
    except FileNotFoundError:
        if missing_ok:
            return b""  # A tracked deletion has an empty worktree side.
        raise ConsoleError("reference_not_found", 404) from None
    except OSError:
        raise ConsoleError("path_denied", 403) from None


def repository_root(root: Path) -> Path:
    return Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip())


def changes(root: Path) -> list[dict]:
    root = repository_root(root)
    records = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0")
    result, i = [], 0
    while i < len(records):
        record = records[i]
        i += 1
        if not record:
            continue
        status, path = record[:2].decode(), record[3:].decode("utf-8", "replace")
        old_path = None
        if "R" in status or "C" in status:
            old_path = records[i].decode("utf-8", "replace")
            i += 1
        try:
            safe_path(root, path)
            if old_path:
                safe_path(root, old_path)
        except ConsoleError:
            continue
        result.append({"path": path, "status": status, "old_path": old_path})
    return result


def status(root: Path) -> dict:
    """Read local Git state only; remote counts describe cached refs, never a fetch."""
    root = repository_root(root)
    raw = git(root, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
    result = dict(
        branch=None,
        head=None,
        upstream=None,
        ahead=None,
        behind=None,
        staged=0,
        unstaged=0,
        untracked=0,
        conflicts=0,
        changed=0,
    )
    records = iter(raw.split(b"\0"))
    for record in records:
        if not record:
            continue
        value = record.decode("utf-8", "replace")
        if value.startswith("# branch.head "):
            name = value.removeprefix("# branch.head ")
            result["branch"] = None if name == "(detached)" else name
        elif value.startswith("# branch.oid "):
            oid = value.removeprefix("# branch.oid ")
            result["head"] = None if oid == "(initial)" else oid
        elif value.startswith("# branch.upstream "):
            result["upstream"] = value.removeprefix("# branch.upstream ")
        elif value.startswith("# branch.ab "):
            ahead, behind = value.removeprefix("# branch.ab ").split()
            result["ahead"], result["behind"] = int(ahead), -int(behind)
        elif record[:1] in (b"1", b"2", b"u", b"?"):
            result["changed"] += 1
            if record[:1] == b"?":
                result["untracked"] += 1
            elif record[:1] == b"u":
                result["conflicts"] += 1
            else:
                xy = value.split(" ", 2)[1]
                result["staged"] += int(xy[0] != ".")
                result["unstaged"] += int(xy[1] != ".")
            if record[:1] == b"2":
                next(records, None)  # rename/copy source path
    return {
        **result,
        "root": str(root),
        "detached": result["branch"] is None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def prepare_workspace(
    workspace: Path,
    task_id: str,
    *,
    base_ref: str,
    worktree_root: Path,
    validate_target=None,
    branch_name: str | None = None,
) -> tuple[Path, bool]:
    """Create an explicitly requested isolated checkout; native turns need no Git preflight."""
    target = worktree_root / f"codex-{task_id}"
    if validate_target is not None:
        validate_target(target)
    if target.exists():
        raise ConsoleError("worktree_exists")
    base = git(workspace, "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}")
    relative = workspace.relative_to(repository_root(workspace))
    if relative != Path("."):
        # Explicit isolation preserves the selected subdirectory.
        if (
            git(
                workspace, "cat-file", "-t", f"{base.decode().strip()}:{relative.as_posix()}"
            ).strip()
            != b"tree"
        ):
            raise ConsoleError("workspace_unavailable")
    worktree_root.mkdir(parents=True, exist_ok=True)
    if branch_name is None:
        git(workspace, "worktree", "add", "--detach", str(target), base.decode().strip())
    else:
        git(workspace, "check-ref-format", "--branch", branch_name)
        git(workspace, "worktree", "add", "-b", branch_name, str(target), base.decode().strip())
    return target / relative, True


def diff(root: Path, relative: str) -> dict:
    root = repository_root(root)
    candidates = {item["path"]: item for item in changes(root)}
    if relative not in candidates:
        raise ConsoleError("file_not_changed", 404)
    item = candidates[relative]
    new = read_worktree_file(root, relative)
    old = b""
    if item["status"] != "??":
        try:
            old = git(root, "show", f"HEAD:{item['old_path'] or relative}")
        except ConsoleError:
            # An added tracked file has no HEAD object. Do not mask other errors.
            if "A" not in item["status"]:
                raise
    if b"\x00" in old or b"\x00" in new:
        return {"path": relative, "binary": True, "old": "", "new": ""}
    return {
        "path": relative,
        "binary": False,
        "old": old.decode("utf-8", "replace"),
        "new": new.decode("utf-8", "replace"),
    }
