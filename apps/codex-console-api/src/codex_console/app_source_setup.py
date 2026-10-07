"""Explicit preparation of one fixed starter, never an app command/provisioning runner."""

import configparser
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import zlib
from contextlib import ExitStack, contextmanager
from datetime import UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import app_sources, app_starters
from .errors import ConsoleError
from .models import AppSourceBinding, AppSourceSetup, WorkbenchProject, now
from .storage import database_path, private_file
from .workbench_schemas import SourceBindingInput, SourceSetupOut

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_TREE_BYTES = 16 * 1024 * 1024


def root_id(path):
    return hashlib.sha256(str(path).encode()).hexdigest()


@contextmanager
def directory(path):
    """Anchor every path component; a symlinked ancestor never becomes a write root."""
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ConsoleError("app_setup_root_denied", 403)
    with ExitStack() as stack:
        descriptor = os.open("/", DIRECTORY_FLAGS)
        stack.callback(os.close, descriptor)
        for part in path.parts[1:]:
            descriptor = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            stack.callback(os.close, descriptor)
        yield descriptor


def allowed_root(settings, key):
    root = next((path for path in settings.app_creation_roots if root_id(path) == key), None)
    if root is None or not any(root.is_relative_to(path) for path in settings.app_source_roots):
        raise ConsoleError("app_setup_root_denied", 403)
    protected = [
        settings.workspace,
        settings.worktree_root,
        *settings.protected_workspaces,
        database_path(settings.database_url),
        settings.attachment_cache.expanduser(),
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser(),
        Path.home() / ".agents",
        Path.home() / ".ssh",
        Path.home() / ".config",
    ]
    if any(
        root.is_relative_to(path.resolve()) or path.resolve().is_relative_to(root)
        for path in protected
    ):
        raise ConsoleError("app_setup_root_denied", 403)
    try:
        with directory(root) as descriptor:
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                raise ConsoleError("app_setup_root_denied", 403)
    except OSError:
        raise ConsoleError("app_setup_root_denied", 403) from None
    return root


def options(settings):
    resources = app_starters.bundle()
    roots = []
    for path in settings.app_creation_roots:
        # Invalid or unavailable configured roots are not offered as writable choices.
        try:
            allowed_root(settings, root_id(path))
        except ConsoleError:
            continue
        roots.append({"id": root_id(path), "label": str(path)})
    return {
        "roots": roots,
        "templates": [
            {
                "id": key,
                "name": item["name"],
                "runtime_profile": item["runtime_profile"],
                "bundle_digest": resources["bundle_digest"],
                "sdk_version": resources["sdk_version"],
            }
            for key, item in resources["templates"].items()
        ],
    }


def output(row):
    return SourceSetupOut(**{name: getattr(row, name) for name in SourceSetupOut.model_fields})


def read(factory, project_id):
    with factory() as db:
        if db.get(WorkbenchProject, project_id) is None:
            raise ConsoleError("app_not_found", 404)
        row = db.scalar(select(AppSourceSetup).where(AppSourceSetup.project_id == project_id))
        return {"setup": output(row) if row else None}


@contextmanager
def ownership(settings, project_id):
    # This private lock is outside the app checkout and spans short DB transactions.
    path = database_path(settings.database_url)
    descriptor = private_file(path.with_name(path.name + f".source-setup-{project_id}.lock"))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConsoleError("app_setup_busy", 409) from None
        yield
    finally:
        os.close(descriptor)


def stat_at(parent, name):
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def identity(info):
    return str(info.st_dev), str(info.st_ino)


def current_root(path, descriptor):
    with directory(path) as current:
        if identity(os.fstat(current)) != identity(os.fstat(descriptor)):
            raise ConsoleError("app_setup_conflict", 409)


def tree(descriptor):
    result = {}
    total = 0
    count = 0

    def visit(parent, prefix):
        nonlocal total, count
        if len(Path(prefix).parts) > 20:
            raise ConsoleError("app_setup_conflict", 409)
        names = []
        with os.scandir(parent) as children:
            for child in children:
                names.append(child.name)
                if count + len(names) > 4096:
                    raise ConsoleError("app_setup_conflict", 409)
        for name in sorted(names):
            count += 1
            if count > 4096:
                raise ConsoleError("app_setup_conflict", 409)
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            relative = prefix + name
            if info.st_uid != os.getuid():
                raise ConsoleError("app_setup_conflict", 409)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
                try:
                    visit(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(child, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (
                        identity(opened) != identity(info)
                        or opened.st_nlink != 1
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_uid != os.getuid()
                    ):
                        raise ConsoleError("app_setup_conflict", 409)
                    content = stream.read(MAX_TREE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                    if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ):
                        raise ConsoleError("app_setup_conflict", 409)
                    if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(
                        after
                    ):
                        raise ConsoleError("app_setup_conflict", 409)
                total += len(content)
                if total > MAX_TREE_BYTES or len(result) >= 4096:
                    raise ConsoleError("app_setup_conflict", 409)
                result[relative] = content
            else:
                raise ConsoleError("app_setup_conflict", 409)

    visit(descriptor, "")
    return result


def copy_files(descriptor, entries):
    present = {
        name: value for name, value in tree(descriptor).items() if not name.startswith(".git/")
    }
    if any(name not in entries or entries[name] != value for name, value in present.items()):
        raise ConsoleError("app_setup_conflict", 409)
    for name, content in entries.items():
        if name in present:
            continue
        with ExitStack() as stack:
            parent = descriptor
            for part in Path(name).parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                parent = os.open(part, DIRECTORY_FLAGS, dir_fd=parent)
                stack.callback(os.close, parent)
            fd = os.open(
                Path(name).name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    os.fsync(descriptor)


def git(descriptor, row, *arguments, data=None):
    # Only fixed Git argv reaches this helper. No user shell/config/environment is inherited.
    timestamp = row.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC).isoformat()
    environment = {
        "PATH": os.defpath,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_AUTHOR_NAME": "MIY app workspace",
        "GIT_COMMITTER_NAME": "MIY app workspace",
        "GIT_AUTHOR_EMAIL": "app-workspace@localhost.invalid",
        "GIT_COMMITTER_EMAIL": "app-workspace@localhost.invalid",
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    try:
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "diff.external=",
                "-C",
                f"/proc/self/fd/{descriptor}",
                *arguments,
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            pass_fds=(descriptor,),
            timeout=15,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        raise ConsoleError("app_setup_git_failed", 503) from None
    if len(result.stdout) > 65536:
        raise ConsoleError("app_setup_git_failed", 503)
    return result.stdout.strip()


def metadata_safe(descriptor, row):
    entries = tree(descriptor)
    metadata = {name[5:]: value for name, value in entries.items() if name.startswith(".git/")}
    allowed = re.compile(
        r"(?:HEAD|config|index|refs/heads/main|logs/HEAD|logs/refs/heads/main|objects/[0-9a-f]{2}/[0-9a-f]{38})"
    )
    if any(not allowed.fullmatch(name) for name in metadata):
        raise ConsoleError("app_setup_conflict", 409)
    if metadata.get("HEAD") != b"ref: refs/heads/main\n":
        raise ConsoleError("app_setup_conflict", 409)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(metadata.get("config", b"").decode())
        if parser.defaults() or set(parser.sections()) - {"core", 'remote "origin"'}:
            raise ValueError("Unexpected Git configuration")
        expected = {
            "core": {
                "repositoryformatversion": "0",
                "filemode": "true",
                "bare": "false",
                "logallrefupdates": "true",
            },
            'remote "origin"': {
                "url": row.repository,
                "fetch": "+refs/heads/*:refs/remotes/origin/*",
            },
        }
        if "core" not in parser or dict(parser["core"]) != expected["core"]:
            raise ValueError("Incomplete Git initialization")
        for section in parser.sections():
            if any(expected[section].get(key) != value for key, value in parser[section].items()):
                raise ValueError("Unexpected Git configuration")
    except (ValueError, UnicodeError, configparser.Error):
        raise ConsoleError("app_setup_conflict", 409) from None


def initialize_git(descriptor, row):
    if stat_at(descriptor, ".git") is None:
        git(descriptor, row, "init", "--template=", "--initial-branch=main", "--object-format=sha1")
    metadata_safe(descriptor, row)
    git(descriptor, row, "config", "--local", "remote.origin.url", row.repository)
    git(
        descriptor,
        row,
        "config",
        "--local",
        "remote.origin.fetch",
        "+refs/heads/*:refs/remotes/origin/*",
    )
    git(descriptor, row, "add", "--all")
    tree_id = git(descriptor, row, "write-tree")
    commit = git(
        descriptor,
        row,
        "commit-tree",
        tree_id.decode(),
        data=b"Initialize isolated application workspace\n",
    )
    if not re.fullmatch(rb"[0-9a-f]{40}", commit):
        raise ConsoleError("app_setup_git_failed", 503)
    previous = tree(descriptor).get(".git/refs/heads/main")
    if previous is not None and previous.strip() != commit:
        raise ConsoleError("app_setup_conflict", 409)
    if previous is None:
        git(descriptor, row, "update-ref", "refs/heads/main", commit.decode(), "0" * 40)
    metadata_safe(descriptor, row)
    os.fsync(descriptor)
    return commit.decode()


def verify_git(descriptor, row, entries):
    """The recorded commit must contain these starter bytes, including after a lost response."""
    metadata_safe(descriptor, row)
    present = tree(descriptor)
    if {name: value for name, value in present.items() if not name.startswith(".git/")} != entries:
        raise ConsoleError("app_setup_conflict", 409)
    if present.get(".git/refs/heads/main", b"").strip() != row.source_revision.encode():
        raise ConsoleError("app_setup_conflict", 409)
    expanded = 0
    for name, compressed in present.items():
        if not name.startswith(".git/objects/"):
            continue
        try:
            decoder = zlib.decompressobj()
            content = decoder.decompress(compressed, MAX_TREE_BYTES + 1)
            expanded += len(content)
            if (
                expanded > MAX_TREE_BYTES
                or not decoder.eof
                or decoder.unused_data
                or decoder.unconsumed_tail
                or hashlib.sha1(content).hexdigest() != name[13:].replace("/", "")
            ):
                raise ValueError("Invalid starter object")
        except (ValueError, zlib.error):
            raise ConsoleError("app_setup_conflict", 409) from None
    try:
        git(descriptor, row, "fsck", "--strict", "--no-reflogs")
        listing = git(descriptor, row, "ls-tree", "-rz", "--full-tree", "HEAD")
        actual = {}
        for item in listing.split(b"\0"):
            if not item:
                continue
            metadata, name = item.split(b"\t", 1)
            actual[name.decode()] = metadata.decode()
        expected = {
            name: "100644 blob "
            + hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            for name, content in entries.items()
        }
        if actual != expected:
            raise ValueError("Starter tree differs")
        git(descriptor, row, "diff", "--cached", "--quiet", "--no-ext-diff", "HEAD", "--")
    except (ConsoleError, ValueError, UnicodeError):
        raise ConsoleError("app_setup_conflict", 409) from None


def publish(parent, source, destination):
    # POSIX rename may replace an existing empty directory. Require Linux no-replace semantics.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ConsoleError("app_setup_publish_unsupported", 503)
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, source.encode(), parent, destination.encode(), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise ConsoleError("app_setup_conflict", 409)
        raise ConsoleError("app_setup_publish_failed", 503)
    os.fsync(parent)


def checkpoint(factory, operation_id, **values):
    with factory.begin() as db:
        row = db.get(AppSourceSetup, operation_id)
        for name, value in values.items():
            setattr(row, name, value)
        row.updated_at = now()


def materialize(settings, factory, row, entries):
    root = allowed_root(settings, row.root_id)
    if str(root) != row.root_path:
        raise ConsoleError("app_setup_conflict", 409)
    with directory(root) as parent:
        stage = ".miy-source-" + row.operation_id
        final = row.app_id
        target = stat_at(parent, final)
        if target is not None:
            if identity(target) != (row.stage_device, row.stage_inode) or not row.source_revision:
                raise ConsoleError("app_setup_conflict", 409)
            chosen = final
        else:
            chosen = stage
            info = stat_at(parent, stage)
            if info is None:
                if row.stage_inode:
                    raise ConsoleError("app_setup_conflict", 409)
                os.mkdir(stage, mode=0o700, dir_fd=parent)
                info = os.stat(stage, dir_fd=parent, follow_symlinks=False)
                row.stage_device, row.stage_inode = identity(info)
                checkpoint(
                    factory,
                    row.operation_id,
                    stage_device=row.stage_device,
                    stage_inode=row.stage_inode,
                )
            elif identity(info) != (row.stage_device, row.stage_inode):
                raise ConsoleError("app_setup_conflict", 409)
        descriptor = os.open(chosen, DIRECTORY_FLAGS, dir_fd=parent)
        try:
            if identity(os.fstat(descriptor)) != (row.stage_device, row.stage_inode):
                raise ConsoleError("app_setup_conflict", 409)
            current_root(root, parent)
            if chosen == final:
                verify_git(descriptor, row, entries)
            else:
                copy_files(descriptor, entries)
                row.source_revision = initialize_git(descriptor, row)
                verify_git(descriptor, row, entries)
                row.source_root = str(root / final)
                checkpoint(
                    factory,
                    row.operation_id,
                    source_root=row.source_root,
                    source_revision=row.source_revision,
                )
                current_root(root, parent)
                publish(parent, stage, final)
            current_root(root, parent)
            if identity(os.stat(final, dir_fd=parent, follow_symlinks=False)) != identity(
                os.fstat(descriptor)
            ):
                raise ConsoleError("app_setup_conflict", 409)
        finally:
            os.close(descriptor)
    return root / final


def prepare(settings, factory, project_id, body):
    with ownership(settings, project_id):
        root = allowed_root(settings, body.root_id)
        with factory() as db:
            project = db.get(WorkbenchProject, project_id)
            if project is None or project.reuse_decision != "new":
                raise ConsoleError("app_setup_invalid", 422)
            previous = db.scalar(
                select(AppSourceSetup).where(AppSourceSetup.project_id == project_id)
            )
            intent = {
                "project_id": project.id,
                "app_id": project.app_id,
                "title": project.title,
                **body.model_dump(mode="json"),
            }
            input_digest = (
                "sha256:" + hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
            )
            if previous:
                if (
                    previous.operation_id != str(body.operation_id)
                    or previous.input_digest != input_digest
                ):
                    raise ConsoleError("app_setup_conflict", 409)
                if previous.state in ("ready", "conflict"):
                    return output(previous)
            entries = app_starters.render(
                body.template_id,
                app_id=project.app_id,
                title=project.title,
                repository=body.repository,
                expected_digest=body.expected_bundle_digest,
            )
            if not previous and db.get(AppSourceBinding, project.app_id):
                raise ConsoleError("app_setup_conflict", 409)
            row = previous or AppSourceSetup(
                operation_id=str(body.operation_id),
                project_id=project.id,
                app_id=project.app_id,
                title=project.title,
                root_id=body.root_id,
                root_path=str(root),
                template_id=body.template_id,
                repository=body.repository,
                bundle_digest=body.expected_bundle_digest,
                input_digest=input_digest,
                state="preparing",
                created_at=now(),
                updated_at=now(),
            )
            if previous:
                db.expunge(row)
        try:
            with factory.begin() as db:
                if not previous:
                    if db.get(AppSourceSetup, row.operation_id):
                        raise ConsoleError("app_setup_conflict", 409)
                    db.add(row)
                else:
                    stored = db.get(AppSourceSetup, row.operation_id)
                    stored.state, stored.failure_code, stored.updated_at = "preparing", None, now()
        except IntegrityError:
            # The operation ID is global; another project's independent lock may have won it.
            raise ConsoleError("app_setup_conflict", 409) from None
        try:
            destination = materialize(settings, factory, row, entries)
            manifest, digest = app_sources.read_manifest(settings, destination, row.app_id)
            from .workbench import bind_source_record

            with factory.begin() as db:
                binding = bind_source_record(
                    settings,
                    db,
                    row.app_id,
                    SourceBindingInput(repository_root=str(destination), version=0),
                    manifest=manifest,
                    digest=digest,
                )
                stored = db.get(AppSourceSetup, row.operation_id)
                stored.state, stored.failure_code, stored.updated_at = "ready", None, now()
                stored.source_root, stored.source_revision = str(destination), row.source_revision
                stored.source_version = binding.version
        except ConsoleError as error:
            checkpoint(
                factory,
                row.operation_id,
                state="conflict" if error.status in (403, 409) else "failed",
                failure_code=error.code,
            )
        except OSError:
            checkpoint(
                factory, row.operation_id, state="failed", failure_code="app_setup_io_failed"
            )
        return read(factory, project_id)["setup"]
