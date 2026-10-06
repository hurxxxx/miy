from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .storage import UTCDateTime, database  # noqa: F401 -- public persistence entry point


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "console_owner"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    password_hash: Mapped[str] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WebSession(Base):
    __tablename__ = "console_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class Task(Base):
    __tablename__ = "console_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    executor: Mapped[str] = mapped_column(String(24), default="session", server_default="session")
    template_snapshot: Mapped[dict | None] = mapped_column(JSON)
    launch_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    context: Mapped[dict | None] = mapped_column(JSON)
    pinned: Mapped[bool] = mapped_column(default=False)
    thread_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    stage: Mapped[str] = mapped_column(String(24), default="plan")
    status: Mapped[str] = mapped_column(String(24), default="idle")
    root: Mapped[str] = mapped_column(Text)
    last_execution_root: Mapped[str | None] = mapped_column(Text)
    previous_execution_root: Mapped[str | None] = mapped_column(Text)
    previous_permissions: Mapped[str | None] = mapped_column(String(24))
    worktree_owned: Mapped[bool] = mapped_column(default=False)
    # Retained for database compatibility; Git snapshots no longer gate native execution.
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    effort: Mapped[str | None] = mapped_column(String(40))
    permissions: Mapped[str] = mapped_column(String(24), default="read-only")
    progress: Mapped[dict | None] = mapped_column(JSON)
    runtime_generation: Mapped[str | None] = mapped_column(String(36))
    turn_id: Mapped[str | None] = mapped_column(String(160))
    current_operation_id: Mapped[str | None] = mapped_column(String(36))
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Revision(Base):
    __tablename__ = "console_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "kind", "version"),
        UniqueConstraint("task_id", "kind", "source_turn_id", name="uq_console_revision_kind_turn"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    source_turn_id: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class WorkbenchProject(Base):
    __tablename__ = "console_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    reuse_decision: Mapped[str] = mapped_column(String(24))
    reuse_notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Maintenance(Base):
    __tablename__ = "console_maintenance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(120), default="")
    due_on: Mapped[str | None] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(24), default="open")
    target_revision: Mapped[str | None] = mapped_column(String(40))
    verification: Mapped[dict | None] = mapped_column(JSON)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("console_tasks.id"))
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class AppBudget(Base):
    __tablename__ = "console_app_budgets"
    app_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    development_tokens: Mapped[int | None] = mapped_column(Integer)
    runtime_tokens: Mapped[int | None] = mapped_column(Integer)
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    version: Mapped[int] = mapped_column(default=1)


class DevelopmentUsage(Base):
    __tablename__ = "console_development_usage"
    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id"), index=True)
    total_tokens: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class DevelopmentUsageMonth(Base):
    __tablename__ = "console_development_usage_months"
    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id"), index=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)


class WorkbenchObservation(Base):
    __tablename__ = "console_workbench_observations"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Item(Base):
    __tablename__ = "console_items"
    __table_args__ = (UniqueConstraint("task_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(String(200))
    turn_id: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON)


class PendingRequest(Base):
    __tablename__ = "console_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id", ondelete="CASCADE"))
    thread_id: Mapped[str | None] = mapped_column(String(160))
    turn_id: Mapped[str] = mapped_column(String(160))
    rpc_id: Mapped[str] = mapped_column(Text)
    generation: Mapped[str] = mapped_column(String(36))
    method: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    answer: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Operation(Base):
    __tablename__ = "console_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    digest: Mapped[str] = mapped_column(String(64))
    display_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Attachment(Base):
    __tablename__ = "console_attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("console_tasks.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MessageAttachment(Base):
    __tablename__ = "console_message_attachments"
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("console_operations.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("console_attachments.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class WorkspaceLease(Base):
    __tablename__ = "console_workspace_lease"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("console_tasks.id"))
    __table_args__ = (CheckConstraint("id = 1"),)


class ResourceLease(Base):
    __tablename__ = "console_resource_leases"
    task_id: Mapped[str] = mapped_column(
        ForeignKey("console_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    resource: Mapped[str] = mapped_column(Text, primary_key=True)
    exclusive: Mapped[bool] = mapped_column(default=True)


class Agent(Base):
    """Replaceable native thread projection, not an agent execution engine."""

    __tablename__ = "console_agents"
    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("console_tasks.id", ondelete="CASCADE"), index=True
    )
    parent_thread_id: Mapped[str | None] = mapped_column(String(160))
    session_id: Mapped[str | None] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(200), default="Codex")
    role: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="notLoaded")
    flags: Mapped[list] = mapped_column(JSON, default=list)
    turn_id: Mapped[str | None] = mapped_column(String(160))
    activity: Mapped[str | None] = mapped_column(String(500))
    progress: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class ServiceObservation(Base):
    __tablename__ = "console_service_observations"
    service_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(40))
    version: Mapped[str | None] = mapped_column(String(160))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class TaskTemplate(Base):
    __tablename__ = "console_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version: Mapped[int] = mapped_column(default=1)
    definition: Mapped[dict] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class HostObservation(Base):
    __tablename__ = "console_host_observations"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    payload: Mapped[dict] = mapped_column(JSON)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Event(Base):
    __tablename__ = "console_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("console_tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (
        Index("ix_console_events_task_id_id", "task_id", "id"),
        {"sqlite_autoincrement": True},
    )
