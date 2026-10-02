"""Owner-authored Codex documents at official locations, never an arbitrary file API."""

import fcntl
import hashlib
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from . import git
from .errors import ConsoleError

MAX_BYTES = 64 * 1024
MAX_FILES = 2000
Scope = Literal["project", "personal", "global"]
GUIDANCE = {"AGENTS.md", "AGENTS.override.md"}


class DocumentKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    path: str = Field(min_length=1, max_length=1000)


class DocumentWrite(DocumentKey):
    content: str = Field(max_length=MAX_BYTES)
    # Missing and empty files have distinct revisions. Creation cannot overwrite.
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DocumentOut(DocumentKey):
    kind: Literal["instructions", "skill", "metadata", "reference"]
    editable: bool
    exists: bool
    revision: str | None
    content: str


class DocumentEntry(DocumentKey):
    kind: Literal["instructions", "skill", "metadata", "reference"]
    editable: bool


class DocumentCatalog(BaseModel):
    entries: list[DocumentEntry]
    roots: dict[str, str]


def roots(settings):
    return {
        "project": settings.workspace,
        "personal": Path.home() / ".agents",
        "global": Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser(),
    }


def target(settings, scope, relative):
    root = roots(settings)[scope]
    if not root.is_absolute():
        raise ConsoleError("path_denied", 403)
    path = Path(relative)
    if str(path) != relative or "\\" in relative or any(ord(c) < 32 for c in relative):
        raise ConsoleError("path_denied", 403)
    candidate = git.safe_path(root, relative)
    settings.require_allowed_paths(root, candidate)
    parts = path.parts
    if parts[-1] in GUIDANCE and (scope == "project" or len(parts) == 1):
        return root, "instructions", True
    prefix = (".agents", "skills") if scope == "project" else ("skills",)
    # Repository scopes can have their own .agents/skills directory.
    offset = next((i for i in range(len(parts)) if parts[i : i + len(prefix)] == prefix), None)
    if offset is None or (scope != "project" and offset != 0):
        raise ConsoleError("path_denied", 403)
    rest = parts[offset + len(prefix) :]
    if len(rest) < 2 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", rest[0]):
        raise ConsoleError("path_denied", 403)
    tail = rest[1:]
    if tail == ("SKILL.md",):
        return root, "skill", True
    if tail == ("agents", "openai.yaml"):
        return root, "metadata", True
    if len(tail) >= 2 and tail[0] == "references" and tail[-1].endswith(".md"):
        return root, "reference", True
    raise ConsoleError("path_denied", 403)


@contextmanager
def parent(root, relative, *, create=False):
    """Pin all ancestors with no-follow descriptors, including the root's ancestors."""
    handles = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        handles.append(fd)
        components = (*root.parts[1:], *Path(relative).parts[:-1])
        for component in components:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            handles.append(fd)
        yield fd, Path(relative).name
    except OSError:
        raise ConsoleError("path_denied", 403) from None
    finally:
        for fd in reversed(handles):
            os.close(fd)


def read_at(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None, None
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConsoleError("path_denied", 403)
        if info.st_size > MAX_BYTES:
            raise ConsoleError("instruction_too_large", 413)
        data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ConsoleError("instruction_too_large", 413)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ConsoleError("instruction_not_text", 422) from None
        return data, info


def output(key, kind, editable, data):
    return DocumentOut(
        **key.model_dump(),
        kind=kind,
        editable=editable,
        exists=data is not None,
        revision=hashlib.sha256(data).hexdigest() if data is not None else None,
        content=data.decode("utf-8") if data is not None else "",
    )


def read(settings, key):
    root, kind, editable = target(settings, key.scope, key.path)
    if not (root / key.path).exists():
        return output(key, kind, editable, None)
    with parent(root, key.path) as (directory, name):
        data, _ = read_at(directory, name)
    return output(key, kind, editable, data)


def write(settings, body):
    root, kind, editable = target(settings, body.scope, body.path)
    data = body.content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ConsoleError("instruction_too_large", 413)
    if kind == "skill" and not re.match(r"\A---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)", body.content):
        raise ConsoleError("invalid_skill_document", 422)
    if kind == "skill":
        metadata = re.split(r"\r?\n---(?:\r?\n|$)", body.content, maxsplit=1)[0]
        if any(
            not re.search(rf"(?m)^{field}:[ \t]*[^ \t\r\n]", metadata)
            for field in ("name", "description")
        ):
            raise ConsoleError("invalid_skill_document", 422)
    with parent(root, body.path, create=True) as (directory, name):
        # Directory lock coordinates saves without persisting a second document store.
        fcntl.flock(directory, fcntl.LOCK_EX)
        old, info = read_at(directory, name)
        revision = hashlib.sha256(old).hexdigest() if old is not None else None
        if revision != body.revision:
            raise ConsoleError("instruction_conflict", 409)
        temporary = f".console-document-{uuid4().hex}"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                stat.S_IMODE(info.st_mode) if info else 0o600,
                dir_fd=directory,
            )
            with os.fdopen(fd, "wb") as destination:
                if info:
                    os.fchmod(destination.fileno(), stat.S_IMODE(info.st_mode))
                destination.write(data)
                destination.flush()
                os.fsync(destination.fileno())
            # Also detect edits by ordinary editors/Codex during this save.
            current, _ = read_at(directory, name)
            if current != old:
                raise ConsoleError("instruction_conflict", 409)
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return output(DocumentKey(scope=body.scope, path=body.path), kind, editable, data)


def catalog(settings):
    locations = roots(settings)
    candidates = [
        ("project", p.decode("utf-8", "replace"))
        for p in git.git(
            settings.workspace, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ).split(b"\0")
        if p
    ]
    candidates.extend((scope, name) for scope in ("project", "global") for name in GUIDANCE)
    for scope in ("personal", "global"):
        base = locations[scope] / "skills"
        if not base.is_dir() or base.is_symlink():
            continue
        visited = 0
        for directory, dirs, files in os.walk(base, followlinks=False):
            visited += len(dirs) + len(files)
            if visited > 10000:
                raise ConsoleError("output_too_large", 413)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                candidates.append(
                    (scope, str((Path(directory) / name).relative_to(locations[scope])))
                )
    entries = {}
    for scope, path in candidates:
        if Path(path).name not in GUIDANCE | {"SKILL.md", "openai.yaml"} and not (
            "/references/" in path and path.endswith(".md")
        ):
            continue
        try:
            root, kind, editable = target(settings, scope, path)
            if not (root / path).is_file():
                continue
        except ConsoleError:
            continue
        entries[(scope, path)] = DocumentEntry(scope=scope, path=path, kind=kind, editable=editable)
        if len(entries) > MAX_FILES:
            raise ConsoleError("output_too_large", 413)
    return DocumentCatalog(
        entries=[entries[k] for k in sorted(entries)],
        roots={scope: str(path) for scope, path in locations.items()},
    )


def install(app, secured):
    @app.get("/api/instructions", dependencies=secured, response_model=DocumentCatalog)
    def listing():
        return catalog(app.state.settings)

    @app.get("/api/instructions/document", dependencies=secured, response_model=DocumentOut)
    def document(scope: Scope, path: str = Query(min_length=1, max_length=1000)):
        return read(app.state.settings, DocumentKey(scope=scope, path=path))

    @app.put("/api/instructions/document", dependencies=secured, response_model=DocumentOut)
    def save(body: DocumentWrite):
        return write(app.state.settings, body)
