from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Protocol

from celery import Celery
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.core.worker_queue_contract import MAIL_SYNC_QUEUE, MAIL_SYNC_TASK_NAME
from miy_api.core.worker_task_publisher import create_fail_fast_celery_publisher
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import new_id
from miy_api.domains.mail.models import MailAccount, MailMailbox, MailSyncJob
from miy_api.domains.mail.sync_policy import (
    MailSyncAccessRevoked,
    cancel_mail_sync_job,
    require_mail_sync_access,
)
from miy_api.domains.official_apps.source_guard import lock_source_writer

logger = logging.getLogger(__name__)
PENDING_MAIL_SYNC_PUBLISHES_KEY = "mail_sync_publish_after_commit"


class MailSyncClaimLost(Exception):
    """A prior processing attempt cannot adopt or finish a later claim."""


class MailSyncCommitUnknown(Exception):
    """Stop this invocation without guessing whether a phase COMMIT succeeded."""


@dataclass(frozen=True)
class MailSyncClaim:
    job_id: str
    account_id: str
    mailbox_id: str
    operation: str
    attempt: int
    lease_owner: str | None
    lease_expires_at: datetime

    @classmethod
    def capture(cls, job: MailSyncJob) -> MailSyncClaim:
        if job.status != "processing" or job.lease_expires_at is None:
            raise MailSyncClaimLost("mail_sync_claim_lost")
        return cls(
            job.id,
            job.account_id,
            job.mailbox_id,
            job.operation,
            job.attempts,
            job.lease_owner,
            job.lease_expires_at,
        )


def commit_sync_phase(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        # Neither a raised driver error nor rollback proves COMMIT was rejected.
        # No failure write or provider retry may follow in this invocation.
        try:
            db.rollback()
        except Exception:
            pass
        raise MailSyncCommitUnknown("mail_sync_commit_unknown") from None


def lock_sync_claim(db: Session, claim: MailSyncClaim, *, admit: bool = True) -> MailSyncJob:
    """Retain source + exact processing row locks in this Session's transaction."""
    with db.no_autoflush:
        lock_source_writer(db, "mail_sync_jobs")
        job = db.scalar(
            select(MailSyncJob)
            .where(MailSyncJob.id == claim.job_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if (
            job is None
            or job.status != "processing"
            or (
                job.account_id,
                job.mailbox_id,
                job.operation,
                job.attempts,
                job.lease_owner,
                job.lease_expires_at,
            )
            != (
                claim.account_id,
                claim.mailbox_id,
                claim.operation,
                claim.attempt,
                claim.lease_owner,
                claim.lease_expires_at,
            )
            or (admit and claim.lease_expires_at <= utcnow_naive())
        ):
            raise MailSyncClaimLost("mail_sync_claim_lost")
        return job


class MailSyncRetryScheduled(Exception):
    def __init__(self, countdown: int) -> None:
        super().__init__(f"mail sync retry scheduled in {countdown}s")
        self.countdown = countdown


class MailSyncJobPublisher(Protocol):
    def __call__(self, *, job_id: str) -> None: ...


@lru_cache(maxsize=1)
def get_celery_client() -> Celery:
    settings = get_settings()
    return create_fail_fast_celery_publisher(
        "miy_api_mail",
        broker=settings.worker_broker_url,
        ignore_result=True,
    )


def publish_sync_job(*, job_id: str) -> None:
    get_celery_client().signature(
        MAIL_SYNC_TASK_NAME,
        args=[job_id],
        immutable=True,
    ).apply_async(
        queue=MAIL_SYNC_QUEUE,
        retry=False,
    )


def seconds_until(target: datetime, *, now: datetime) -> int:
    return max(1, int((target - now).total_seconds()))


def mark_sync_job_failed(db: Session, *, job: MailSyncJob, error_text: str) -> int | None:
    settings = get_settings()
    now = utcnow_naive()
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = error_text
    if job.attempts >= settings.mail_sync_max_attempts:
        job.status = "failed"
        job.next_retry_at = None
        countdown = None
    else:
        countdown = min(settings.mail_sync_retry_backoff_seconds * max(job.attempts, 1), 3600)
        job.status = "pending"
        job.next_retry_at = now + timedelta(seconds=countdown)
    job.updated_at = now
    db.add(job)
    commit_sync_phase(db)
    return countdown


def publish_due_mail_sync_jobs(
    db: Session,
    *,
    limit: int = 50,
    publisher: MailSyncJobPublisher = publish_sync_job,
) -> int:
    now = utcnow_naive()
    due_job_ids = claim_due_mail_sync_jobs(db, now=now, limit=limit)
    published_count = 0
    for due_job_id in due_job_ids:
        try:
            publisher(job_id=due_job_id)
        except Exception:
            logger.warning("Failed to publish due mail sync job", exc_info=True)
            clear_mail_sync_publish_claim(db, job_id=due_job_id, published_at=now)
            continue
        published_count += 1
    return published_count


def claim_due_mail_sync_jobs(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> list[str]:
    settings = get_settings()
    visible_before = now - timedelta(seconds=settings.mail_sync_dispatch_visibility_seconds)
    jobs = list(
        db.scalars(
            select(MailSyncJob)
            .where(
                or_(
                    and_(
                        MailSyncJob.status == "pending",
                        or_(
                            MailSyncJob.next_retry_at.is_(None),
                            MailSyncJob.next_retry_at <= now,
                        ),
                        or_(
                            MailSyncJob.last_published_at.is_(None),
                            MailSyncJob.last_published_at <= visible_before,
                        ),
                    ),
                    and_(
                        MailSyncJob.status == "processing",
                        MailSyncJob.lease_expires_at.is_not(None),
                        MailSyncJob.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(MailSyncJob.created_at.asc(), MailSyncJob.id.asc())
            .limit(limit)
            .with_for_update()
        )
    )
    if not jobs:
        return []
    due_job_ids: list[str] = []
    for job in jobs:
        try:
            require_mail_sync_access(db, account_id=job.account_id)
        except MailSyncAccessRevoked as exc:
            cancel_mail_sync_job(db, job=job, error=str(exc))
            continue
        job.status = "pending"
        job.last_published_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = now
        db.add(job)
        due_job_ids.append(job.id)
    db.commit()
    return due_job_ids


def clear_mail_sync_publish_claim(
    db: Session,
    *,
    job_id: str,
    published_at: datetime,
) -> None:
    job = db.get(MailSyncJob, job_id)
    if job is None or job.status != "pending" or job.last_published_at != published_at:
        return
    job.last_published_at = None
    job.updated_at = utcnow_naive()
    db.add(job)
    db.commit()


def enqueue_sync_job(
    db: Session,
    *,
    account: MailAccount,
    mailbox: MailMailbox,
    operation: str,
    publish: bool = True,
    schedule_publish_after_commit: Callable[[Session, str], None] | None = None,
) -> MailSyncJob:
    now = utcnow_naive()
    schedule_publish = schedule_publish_after_commit or schedule_mail_sync_publish_after_commit
    settings = get_settings()
    visible_before = now - timedelta(seconds=settings.mail_sync_dispatch_visibility_seconds)
    existing = db.scalar(
        select(MailSyncJob)
        .where(
            MailSyncJob.account_id == account.id,
            MailSyncJob.mailbox_id == mailbox.id,
            MailSyncJob.operation == operation,
            MailSyncJob.status.in_(("pending", "processing")),
        )
        .order_by(MailSyncJob.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is not None:
        should_publish = False
        if existing.status == "processing":
            lease_expired = (
                existing.lease_expires_at is not None and existing.lease_expires_at <= now
            )
            if lease_expired:
                existing.status = "pending"
                existing.lease_owner = None
                existing.lease_expires_at = None
                should_publish = publish
        else:
            existing.next_retry_at = None
            should_publish = publish and (
                existing.last_published_at is None or existing.last_published_at <= visible_before
            )
        existing.last_error = None
        existing.updated_at = now
        if should_publish:
            existing.last_published_at = now
        db.add(existing)
        if should_publish:
            schedule_publish(db, existing.id)
        return existing

    job = MailSyncJob(
        id=new_id(),
        account_id=account.id,
        mailbox_id=mailbox.id,
        operation=operation,
        status="pending",
        attempts=0,
    )
    if publish:
        job.last_published_at = now
    db.add(job)
    if publish:
        schedule_publish(db, job.id)
    return job


def schedule_mail_sync_publish_after_commit(db: Session, job_id: str) -> None:
    pending = db.info.setdefault(PENDING_MAIL_SYNC_PUBLISHES_KEY, set())
    if not isinstance(pending, set):
        pending = set()
        db.info[PENDING_MAIL_SYNC_PUBLISHES_KEY] = pending
    pending.add(job_id)


def pop_pending_mail_sync_job_publications(session: Session) -> set[str]:
    pending = session.info.pop(PENDING_MAIL_SYNC_PUBLISHES_KEY, None)
    if not pending:
        return set()
    return set(pending)


def clear_pending_mail_sync_job_publications(session: Session) -> None:
    session.info.pop(PENDING_MAIL_SYNC_PUBLISHES_KEY, None)
