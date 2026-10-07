"""Durable cleanup of Files objects that could not be removed inline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from miy_worker.task_binding import task_app

from miy_worker.queue_contract import (
    DEFAULT_QUEUE,
    FILE_STORAGE_CLEANUP_REPUBLISH_TASK_NAME,
    FILE_STORAGE_CLEANUP_TASK_NAME,
)
from miy_worker.runtime import (
    db_session as _db_session,
)
from miy_worker.runtime import (
    ensure_api_src_on_path as _ensure_api_src_on_path,
)
from miy_worker.runtime import (
    minio_client as _minio_client,
)
from miy_worker.settings import get_settings

_ensure_api_src_on_path()

from miy_api.domains.files.models import FileManagerStorageCleanupJob  # noqa: E402
from miy_api.domains.official_apps.source_guard import lock_source_writer  # noqa: E402

celery_app = task_app(__name__)

logger = logging.getLogger(__name__)

CLAIM_LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 30
MAX_RETRY_BACKOFF_SECONDS = 3600
REPUBLISH_BATCH_SIZE = 100
_MISSING_OBJECT_ERROR_CODES = frozenset({"NoSuchKey", "NoSuchObject", "NoSuchVersion"})


@dataclass(frozen=True)
class _CleanupClaim:
    job_id: str
    storage_key: str
    attempt: int
    lease_expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _safe_error_code(error: Exception) -> str:
    return f"minio_delete:{type(error).__name__}"[:120]


def _is_missing_object_error(error: Exception) -> bool:
    return str(getattr(error, "code", "")) in _MISSING_OBJECT_ERROR_CODES


def _claim_cleanup_job(
    session: Session,
    *,
    job_id: str,
    now: datetime | None = None,
) -> tuple[str, _CleanupClaim | None]:
    claimed_at = now or _utcnow()
    # Take ownership before the job row, using this transaction's existing
    # trusted writer identity. Never discover/adopt a later generation.
    lock_source_writer(session, "file_manager_storage_cleanup_jobs")
    job = session.scalar(
        select(FileManagerStorageCleanupJob)
        .where(
            FileManagerStorageCleanupJob.id == job_id,
            FileManagerStorageCleanupJob.status == "pending",
            or_(
                FileManagerStorageCleanupJob.next_retry_at.is_(None),
                FileManagerStorageCleanupJob.next_retry_at <= claimed_at,
            ),
        )
        .with_for_update(skip_locked=True)
    )
    if job is None:
        session.rollback()
        current = session.get(FileManagerStorageCleanupJob, job_id)
        if current is None:
            return "missing", None
        if current.status != "pending":
            return current.status, None
        return "leased", None

    if job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
        job.last_error = "dead_letter:max_attempts_exhausted"
        job.next_retry_at = None
        session.add(job)
        session.commit()
        logger.error("Dead-lettered Files storage cleanup job %s before claim", job.id)
        return "dead_letter", None

    job.attempts += 1
    job.next_retry_at = claimed_at + CLAIM_LEASE
    session.add(job)
    claim = _CleanupClaim(
        job_id=job.id,
        storage_key=job.storage_key,
        attempt=job.attempts,
        lease_expires_at=job.next_retry_at,
    )
    session.commit()
    # The immutable snapshot precedes COMMIT: refreshing expired ORM fields
    # afterwards must not silently adopt another worker's claim.
    return "claimed", claim


def _matches_claim(job: FileManagerStorageCleanupJob | None, claim: _CleanupClaim) -> bool:
    return (
        job is not None
        and job.status == "pending"
        and job.attempts == claim.attempt
        and job.storage_key == claim.storage_key
        and job.next_retry_at == claim.lease_expires_at
    )


def _lock_cleanup_effect(session: Session, *, claim: _CleanupClaim) -> bool:
    # The claim is already durable. Reacquire on the SAME Session's new
    # transaction; an outer connection would risk pool exhaustion/deadlock.
    lock_source_writer(session, "file_manager_storage_cleanup_jobs")
    job = session.scalar(
        select(FileManagerStorageCleanupJob)
        .where(FileManagerStorageCleanupJob.id == claim.job_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if not _matches_claim(job, claim) or claim.lease_expires_at <= _utcnow():
        session.rollback()
        return False
    # Hold source SHARE + row lock through delete and final COMMIT/rollback.
    # Expiry during this admitted effect does not discard its locked outcome.
    return True


def _complete_cleanup_job(session: Session, *, claim: _CleanupClaim) -> bool:
    job = session.scalar(
        select(FileManagerStorageCleanupJob)
        .where(FileManagerStorageCleanupJob.id == claim.job_id)
        .with_for_update()
    )
    if not _matches_claim(job, claim):
        session.rollback()
        return False
    job.status = "succeeded"
    job.last_error = None
    job.next_retry_at = None
    session.add(job)
    session.commit()
    return True


def _fail_cleanup_job(
    session: Session,
    *,
    claim: _CleanupClaim,
    error: Exception,
    now: datetime | None = None,
) -> str:
    failed_at = now or _utcnow()
    job = session.scalar(
        select(FileManagerStorageCleanupJob)
        .where(FileManagerStorageCleanupJob.id == claim.job_id)
        .with_for_update()
    )
    if not _matches_claim(job, claim):
        session.rollback()
        return "lost_lease"

    error_code = _safe_error_code(error)
    if job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
        job.last_error = f"dead_letter:{error_code}"
        job.next_retry_at = None
        result = "dead_letter"
    else:
        retry_exponent = max(job.attempts - 2, 0)
        countdown = min(
            RETRY_BACKOFF_SECONDS * (2**retry_exponent),
            MAX_RETRY_BACKOFF_SECONDS,
        )
        job.status = "pending"
        job.last_error = error_code
        job.next_retry_at = failed_at + timedelta(seconds=countdown)
        result = "retry_scheduled"

    session.add(job)
    session.commit()
    return result


@celery_app.task(
    name=FILE_STORAGE_CLEANUP_TASK_NAME,
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
)
def cleanup_file_storage_object(job_id: str) -> str:
    """Claim and idempotently delete one deferred Files object."""

    session = _db_session()
    try:
        claim_status, claim = _claim_cleanup_job(session, job_id=job_id)
        if claim is None:
            return claim_status
        if not _lock_cleanup_effect(session, claim=claim):
            return "lost_lease"

        try:
            settings = get_settings()
            _minio_client().remove_object(settings.minio_bucket, claim.storage_key)
        except Exception as error:
            if _is_missing_object_error(error):
                completed = _complete_cleanup_job(session, claim=claim)
                return "succeeded" if completed else "lost_lease"
            result = _fail_cleanup_job(session, claim=claim, error=error)
            logger.warning(
                "Files storage cleanup job %s attempt %s failed; outcome=%s error_type=%s",
                claim.job_id,
                claim.attempt,
                result,
                type(error).__name__,
            )
            return result

        # COMMIT errors escape without a second effect or failure transaction.
        # An accepted-but-unacknowledged result must not be changed into retry.
        completed = _complete_cleanup_job(session, claim=claim)
        return "succeeded" if completed else "lost_lease"
    finally:
        session.close()


def _due_cleanup_job_ids(
    session: Session,
    *,
    limit: int,
    now: datetime | None = None,
) -> list[str]:
    due_at = now or _utcnow()
    return list(
        session.scalars(
            select(FileManagerStorageCleanupJob.id)
            .where(
                FileManagerStorageCleanupJob.status == "pending",
                or_(
                    FileManagerStorageCleanupJob.next_retry_at.is_(None),
                    FileManagerStorageCleanupJob.next_retry_at <= due_at,
                ),
            )
            .order_by(
                FileManagerStorageCleanupJob.created_at.asc(),
                FileManagerStorageCleanupJob.id.asc(),
            )
            .limit(max(1, min(int(limit), 500)))
        )
    )


def _publish_cleanup_job(job_id: str) -> None:
    celery_app.signature(
        FILE_STORAGE_CLEANUP_TASK_NAME,
        args=[job_id],
        immutable=True,
    ).apply_async(queue=DEFAULT_QUEUE, retry=False)


@celery_app.task(
    name=FILE_STORAGE_CLEANUP_REPUBLISH_TASK_NAME,
    task_time_limit=60,
    task_soft_time_limit=45,
)
def republish_file_storage_cleanup_jobs(limit: int = REPUBLISH_BATCH_SIZE) -> int:
    """Republish new, retryable, and stale-leased cleanup jobs."""

    session = _db_session()
    try:
        job_ids = _due_cleanup_job_ids(session, limit=limit)
    finally:
        session.close()

    for job_id in job_ids:
        _publish_cleanup_job(job_id)
    if job_ids:
        logger.info("Republished %s Files storage cleanup job(s)", len(job_ids))
    return len(job_ids)


__all__ = [
    "cleanup_file_storage_object",
    "republish_file_storage_cleanup_jobs",
]
