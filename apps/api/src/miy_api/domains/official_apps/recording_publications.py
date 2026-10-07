"""Core-only fixed Recording publication preparation and explicit reconciliation.

An injected bounded publisher is an explicit prepared composition, not a switch
that activates the official worker. This module never creates broker credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication
from miy_api.domains.recording.pipeline_commands import (
    commit_command,
    render_command_args,
    require_transaction,
)
from miy_api.domains.recording.pipeline_contracts import (
    MANAGED_HEADER,
    MANAGED_QUEUE,
    RecordingCommandError,
)
from miy_api.domains.recording.pipeline_models import RecordingStageCommand


@dataclass(frozen=True)
class PublicationMessage:
    task: str
    args: tuple
    task_id: str
    command_id: str
    publication_id: str
    payload_digest: str
    attempt_id: str
    predecessor_task_id: str | None
    retry_ordinal: int

    def publish(self, celery) -> None:
        """Supported Celery API, fixed isolated route, without Canvas successors."""
        celery.signature(self.task, args=list(self.args), kwargs={}, immutable=True).apply_async(
            task_id=self.task_id,
            queue=MANAGED_QUEUE,
            serializer="json",
            retry=False,
            headers={
                MANAGED_HEADER: {
                    "version": 1,
                    "command_id": self.command_id,
                    "publication_id": self.publication_id,
                    "payload_digest": self.payload_digest,
                }
            },
            root_id=self.attempt_id,
            parent_id=self.predecessor_task_id,
            retries=self.retry_ordinal,
        )


def _admit(db: Session, command, publication) -> None:
    require_transaction(db)
    db.execute(
        text("SELECT public.miy_recording_publication_admit(:command, :publication, :digest)"),
        {
            "command": command.command_id,
            "publication": publication.publication_id,
            "digest": command.payload_digest,
        },
    )


def prepare_publication(db: Session, command_id: str) -> str:
    """Create only a Core binding. DB stamp validates actual issuer authority."""
    require_transaction(db)
    command = db.get(RecordingStageCommand, command_id, populate_existing=True)
    if command is None:
        raise RecordingCommandError("recording_command_missing")
    existing = db.scalar(
        select(CoreRecordingPublication).where(CoreRecordingPublication.command_id == command_id)
    )
    if existing is not None:
        _admit(db, command, existing)
        return existing.publication_id
    # Competing prepare-only polls may observe the same unbound command. Let
    # the fixed unique identity converge without aborting this transaction or
    # overwriting a binding/token that another prepared issuer committed.
    db.execute(
        insert(CoreRecordingPublication)
        .values(
            publication_id=str(uuid4()),
            command_id=command_id,
            task_id=command.task_id,
            payload_digest=command.payload_digest,
            queue=MANAGED_QUEUE,
            profile="official",
            state="pending",
        )
        .on_conflict_do_nothing(index_elements=[CoreRecordingPublication.command_id])
    )
    publication = db.scalar(
        select(CoreRecordingPublication).where(CoreRecordingPublication.command_id == command_id)
    )
    if publication is None:
        raise RecordingCommandError("recording_publication_missing")
    _admit(db, command, publication)
    result = publication.publication_id
    commit_command(db)
    return result


def _binding(db: Session, publication_id: str):
    require_transaction(db)
    publication = db.get(CoreRecordingPublication, publication_id, populate_existing=True)
    if publication is None:
        raise RecordingCommandError("recording_publication_missing")
    command = db.get(RecordingStageCommand, publication.command_id, populate_existing=True)
    if command is None:
        raise RecordingCommandError("recording_command_missing")
    _admit(db, command, publication)
    db.refresh(publication)
    db.refresh(command)
    return command, publication


def send_publication(
    db: Session,
    publication_id: str,
    *,
    publish: Callable[[PublicationMessage], None],
    republish: bool = False,
) -> str:
    """Durable claim then same-Session admitted send. No automatic resend."""
    command, publication = _binding(db, publication_id)
    allowed = {"unknown"} if republish else {"pending"}
    if publication.state not in allowed:
        raise RecordingCommandError("recording_publication_not_sendable")
    if command.state != "pending" or command.due_at > utcnow_naive():
        raise RecordingCommandError("recording_command_not_sendable")
    render_command_args(db, command)
    token = str(uuid4())
    publication.state = "publishing"
    publication.publication_token = token
    publication.attempted_at = utcnow_naive()
    publication.observed_at = None
    commit_command(db)
    # If another explicit observer got this row during the COMMIT/relock gap,
    # only this unchanged claim can send. A duplicate remote message is further
    # guarded by the source's durable execution token across progress commits.
    command, publication = _binding(db, publication_id)
    if publication.state != "publishing" or publication.publication_token != token:
        raise RecordingCommandError("recording_publication_claim_changed")
    if command.state != "pending":
        publication.state = "consumed"
        publication.observed_at = utcnow_naive()
        commit_command(db)
        return "consumed"
    args = render_command_args(db, command)
    parent = (
        db.get(RecordingStageCommand, command.predecessor_id) if command.predecessor_id else None
    )
    message = PublicationMessage(
        "recording." + command.stage,
        tuple(args),
        command.task_id,
        command.command_id,
        publication.publication_id,
        command.payload_digest,
        command.attempt_id,
        parent.task_id if parent is not None else None,
        command.retry_ordinal,
    )
    try:
        publish(message)
    except Exception:
        publication.state = "unknown"
    else:
        publication.state = "acknowledged"
    publication.observed_at = utcnow_naive()
    outcome = publication.state
    commit_command(db)
    return outcome


def reconcile_publication(db: Session, publication_id: str) -> str:
    """Exact-ID observation only: empty/queued state never proves non-delivery."""
    command, publication = _binding(db, publication_id)
    if publication.state == "consumed":
        return "consumed"
    if command.state != "pending":
        publication.state = "consumed"
        publication.observed_at = utcnow_naive()
    elif publication.state == "publishing":
        publication.state = "unknown"
        publication.observed_at = utcnow_naive()
    outcome = publication.state
    commit_command(db)
    return outcome


def poll_once(db: Session, *, limit: int = 20) -> list[str]:
    """Bounded prepare-only consumption. Never discovers or starts a broker."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise RecordingCommandError("recording_publication_limit_invalid")
    require_transaction(db)
    ids = db.scalars(
        select(RecordingStageCommand.command_id)
        .where(
            RecordingStageCommand.state == "pending",
            RecordingStageCommand.due_at <= utcnow_naive(),
            ~select(CoreRecordingPublication.command_id)
            .where(CoreRecordingPublication.command_id == RecordingStageCommand.command_id)
            .exists(),
        )
        .order_by(RecordingStageCommand.due_at, RecordingStageCommand.command_id)
        .limit(limit)
    ).all()
    return [prepare_publication(db, command_id) for command_id in ids]
