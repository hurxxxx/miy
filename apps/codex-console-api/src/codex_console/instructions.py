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
Scope = Literal["project", "personal", "global", "admin", "system", "plugins"]
Kind = Literal["instructions", "skill", "metadata", "reference", "bridge", "script"]
GUIDANCE = {"AGENTS.md", "AGENTS.override.md"}
READ_ONLY = {"admin", "system", "plugins"}


class DocumentKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    path: str = Field(min_length=1, max_length=1000)


class DocumentWrite(DocumentKey):
    content: str = Field(max_length=MAX_BYTES)
    # Missing and empty files have distinct revisions. Creation cannot overwrite.
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DocumentOut(DocumentKey):
    kind: Kind
    editable: bool
    exists: bool
    revision: str | None
    content: str


class DocumentEntry(DocumentKey):
    kind: Kind
    editable: bool


class DocumentCatalog(BaseModel):
    entries: list[DocumentEntry]
    roots: dict[str, str]


class DiscoveredSkill(BaseModel):
    path: str = Field(max_length=4000)
    name: str = Field(max_length=200)
    description: str = Field(max_length=8000)
    enabled: bool = Field(strict=True)


class GuidanceConfiguration(BaseModel):
    fallback_filenames: list[str] = Field(max_length=100)
    max_bytes: int = Field(ge=0, strict=True)


class SkillDiscovery(BaseModel):
    directory: str
    skills: list[DiscoveredSkill] = Field(max_length=MAX_FILES)
    error_count: int = Field(ge=0)
    guidance: GuidanceConfiguration | None = None


def roots(settings):
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return {
        "project": settings.workspace,
        "personal": Path.home() / ".agents",
        "global": home,
        "admin": Path("/etc/codex/skills"),
        "system": home / "skills" / ".system",
        "plugins": home / "plugins" / "cache",
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
    if scope == "project" and (
        parts[-1] == "CLAUDE.md" or relative == ".github/copilot-instructions.md"
    ):
        return root, "bridge", False
    if parts[-1] in GUIDANCE and (scope == "project" or len(parts) == 1):
        if scope in ("project", "global"):
            return root, "instructions", True
    prefix = (".agents", "skills") if scope == "project" else ("skills",)
    # Repository scopes can have their own .agents/skills directory.
    offset = next((i for i in range(len(parts)) if parts[i : i + len(prefix)] == prefix), None)
    if scope in ("admin", "system"):
        rest = parts
    elif offset is None or (scope in ("personal", "global") and offset != 0):
        raise ConsoleError("path_denied", 403)
    else:
        rest = parts[offset + len(prefix) :]
    if len(rest) < 2 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", rest[0]):
        raise ConsoleError("path_denied", 403)
    tail = rest[1:]
    if any(part.startswith(".") for part in tail):
        raise ConsoleError("path_denied", 403)
    editable = scope not in READ_ONLY
    if tail == ("SKILL.md",):
        return root, "skill", editable
    if tail == ("agents", "openai.yaml"):
        return root, "metadata", editable
    if tail[-1].endswith(".md"):
        return root, "reference", editable
    if tail[0] == "scripts" and path.suffix in {".py", ".sh", ".js", ".mjs", ".ts"}:
        return root, "script", False
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
        if not editable:
            raise ConsoleError("path_denied", 403)
        return output(key, kind, editable, None)
    with parent(root, key.path) as (directory, name):
        data, _ = read_at(directory, name)
    return output(key, kind, editable, data)


def write(settings, body):
    root, kind, editable = target(settings, body.scope, body.path)
    if not editable:
        raise ConsoleError("path_denied", 403)
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


def catalog(settings, scope_filter=None, query=""):
    locations = roots(settings)
    candidates = [
        ("project", p.decode("utf-8", "replace"))
        for p in git.git(
            settings.workspace, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ).split(b"\0")
        if p
    ]
    candidates.extend((scope, name) for scope in ("project", "global") for name in GUIDANCE)
    for scope in ("personal", "global", "admin", "system", "plugins"):
        if scope not in locations or (scope_filter and scope != scope_filter):
            continue
        base = locations[scope] / "skills" if scope in ("personal", "global") else locations[scope]
        if not base.is_dir() or base.is_symlink():
            continue
        visited = 0
        for directory, dirs, files in os.walk(base, followlinks=False):
            visited += len(dirs) + len(files)
            if visited > 10000:
                raise ConsoleError("output_too_large", 413)
            dirs[:] = [
                d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink()
            ]
            for name in files:
                candidates.append(
                    (scope, str((Path(directory) / name).relative_to(locations[scope])))
                )
    entries = {}
    searched_bytes = 0
    query = query.strip().casefold()
    for scope, path in candidates:
        if scope_filter and scope != scope_filter:
            continue
        if not (
            path.endswith(".md")
            or path.endswith("/agents/openai.yaml")
            or ("/scripts/" in path and Path(path).suffix in {".py", ".sh", ".js", ".mjs", ".ts"})
        ):
            continue
        try:
            root, kind, editable = target(settings, scope, path)
            if not (root / path).is_file():
                continue
            if query and query not in path.casefold():
                with parent(root, path) as (directory, name):
                    data, _ = read_at(directory, name)
                if data is None:
                    continue
                searched_bytes += len(data)
                if searched_bytes > 16 * 1024 * 1024:
                    raise ConsoleError("output_too_large", 413)
                if query not in data.decode("utf-8").casefold():
                    continue
        except ConsoleError:
            if searched_bytes > 16 * 1024 * 1024:
                raise
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
    def listing(scope: Scope | None = None, q: str = Query(default="", max_length=200)):
        return catalog(app.state.settings, scope, q)

    @app.get("/api/instructions/document", dependencies=secured, response_model=DocumentOut)
    def document(scope: Scope, path: str = Query(min_length=1, max_length=1000)):
        return read(app.state.settings, DocumentKey(scope=scope, path=path))

    @app.put("/api/instructions/document", dependencies=secured, response_model=DocumentOut)
    def save(body: DocumentWrite):
        return write(app.state.settings, body)
