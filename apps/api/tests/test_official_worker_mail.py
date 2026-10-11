"""Real source/claim transactions; all provider responses are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from company_admission_fixture import seed_company_app_access
from miy_api.domains.auth.models import User, utcnow_naive
from miy_api.domains.mail import service
from miy_api.domains.mail.clients import MailConnectionSettings
from miy_api.domains.mail.models import (
    MailAccount,
    MailMailbox,
    MailMessage,
    MailSyncJob,
    MailSyncState,
)
from miy_api.domains.mail.sync_batch import MailSyncResult
from test_mail_personal_scope import SyncClient, _account
from test_official_writer_fence import change, wait_for_blockers, writer as writer


@pytest.fixture
def mail(writer, monkeypatch):
    factory, admin, _ = writer
    engine = create_engine(factory.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=1)
    worker_factory = sessionmaker(bind=engine)
    account_id, mailbox_id, job_id = (str(uuid4()) for _ in range(3))
    with factory.begin() as db:
        seed_company_app_access(db, ["mail"])
        db.add(_account(account_id, admin["user"]["id"], label="Synthetic worker"))
        db.flush()
        db.add(
            MailMailbox(
                id=mailbox_id,
                account_id=account_id,
                provider_mailbox_id="INBOX",
                display_name="Inbox",
                role="inbox",
            )
        )
        db.flush()
        db.add(
            MailSyncJob(
                id=job_id,
                account_id=account_id,
                mailbox_id=mailbox_id,
                operation="initial",
                status="pending",
            )
        )
    settings = MailConnectionSettings(
        protocol="imap",
        incoming_host="imap.example.test",
        incoming_port=993,
        incoming_security="ssl",
        incoming_username="synthetic",
        incoming_password="synthetic",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="synthetic",
        smtp_password="synthetic",
        email_address="owner@example.test",
    )
    monkeypatch.setattr(service, "settings_from_account", lambda _row: settings)
    monkeypatch.setattr(service, "enforce_connection_profile", lambda *_args, **_kwargs: None)
    try:
        yield SimpleNamespace(
            factory=factory,
            worker_factory=worker_factory,
            admin=admin,
            account_id=account_id,
            job_id=job_id,
            client=SyncClient(),
        )
    finally:
        engine.dispose()


def test_stale_completed_attempt_cannot_overwrite_new_claim(mail, monkeypatch):
    c = mail
    replacement_deadline = utcnow_naive() + timedelta(hours=1)

    def completed(*_args, **_kwargs):
        # Separate claimant after the old attempt released its phase transaction.
        with c.factory.begin() as db:
            row = db.get(MailSyncJob, c.job_id)
            assert row.status == "processing" and row.attempts == 1
            row.attempts = 2
            row.lease_owner = "replacement"
            row.lease_expires_at = replacement_deadline
        return MailSyncResult(new_count=0, updated_count=0, deleted_count=0)

    monkeypatch.setattr(service, "sync_account", completed)
    with c.worker_factory() as db:
        assert (
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
            == "lost_lease"
        )
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert (row.status, row.attempts, row.lease_owner, row.lease_expires_at) == (
            "processing",
            2,
            "replacement",
            replacement_deadline,
        )


@pytest.mark.parametrize("after_commit", [0, 1, 2, 3, 4])
def test_drain_rejects_next_phase_without_provider_failure_retry(mail, monkeypatch, after_commit):
    c = mail
    with c.worker_factory() as db:
        commit = db.commit
        count = 0

        def committed():
            nonlocal count
            commit()
            count += 1
            if count == after_commit:
                with c.factory.begin() as controller:
                    change(controller, c.admin)

        monkeypatch.setattr(db, "commit", committed)
        if after_commit == 0:
            with c.factory.begin() as controller:
                change(controller, c.admin)
        with pytest.raises(DBAPIError) as error:
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
        assert error.value.orig.sqlstate == "55000"
        assert count == after_commit
    assert (c.client.list_calls, c.client.sync_calls) == (
        int(after_commit >= 3),
        int(after_commit >= 4),
    )
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert row.status == ("pending" if after_commit == 0 else "processing")
        assert row.next_retry_at is None and row.last_error is None


@pytest.mark.parametrize("phase", ["discovery", "fetch"])
def test_inflight_phase_holds_source_lock_with_one_worker_connection(mail, phase):
    c = mail
    entered, finish, draining = Event(), Event(), Event()
    pids = {}
    worker_db = c.worker_factory()

    def remote():
        pids["worker"] = worker_db.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert finish.wait(20)

    if phase == "discovery":
        c.client.on_list = remote
    else:
        c.client.on_sync = remote

    def run():
        try:
            return service.process_mail_sync_job(
                worker_db, c.job_id, client=c.client, lease_owner="original"
            )
        finally:
            worker_db.close()

    def drain():
        with c.factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            draining.set()
            return change(db, c.admin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(run)
        try:
            assert entered.wait(8)
            controller = pool.submit(drain)
            assert draining.wait(8)
            wait_for_blockers(c.factory, pids["controller"], {pids["worker"]})
            assert not controller.done()
            finish.set()
            assert controller.result(timeout=8)["state"] == "draining"
            with pytest.raises(DBAPIError) as error:
                work.result(timeout=8)
            assert error.value.orig.sqlstate == "55000"
        finally:
            finish.set()
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert row.status == "processing" and row.attempts == 1 and row.last_error is None
        # The already admitted phase committed before drain won. No later I/O.
        assert len(list(db.scalars(select(MailMessage)))) == int(phase == "fetch")
    assert c.client.sync_calls == int(phase == "fetch")


@pytest.mark.parametrize("changed", ["attempt", "owner", "deadline", "expired", "status"])
def test_replacement_or_expired_claim_cannot_start_provider(mail, monkeypatch, changed):
    c = mail
    sync = service.sync_account

    def replacement(db, **kwargs):
        with c.factory.begin() as other:
            row = other.get(MailSyncJob, c.job_id)
            if changed == "attempt":
                row.attempts += 1
            elif changed == "owner":
                row.lease_owner = "replacement"
            elif changed == "deadline":
                row.lease_expires_at += timedelta(seconds=30)
            elif changed == "status":
                row.status = "pending"
            else:
                now = row.lease_expires_at + timedelta(seconds=1)
                from miy_api.domains.mail import sync_jobs

                monkeypatch.setattr(sync_jobs, "utcnow_naive", lambda: now)
        return sync(db, **kwargs)

    monkeypatch.setattr(service, "sync_account", replacement)
    with c.worker_factory() as db:
        assert (
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
            == "lost_lease"
        )
    assert (c.client.list_calls, c.client.sync_calls) == (0, 0)


@pytest.mark.parametrize("phase", ["discovery", "fetch"])
def test_concurrent_acl_revocation_cancels_only_current_claim_and_discards_response(mail, phase):
    c = mail

    def revoke():
        with c.factory.begin() as other:
            other.get(User, c.admin["user"]["id"]).login_blocked = True

    if phase == "discovery":
        c.client.on_list = revoke
    else:
        c.client.on_sync = revoke
    with c.worker_factory() as db:
        assert (
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
            == "cancelled"
        )
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert row.status == "cancelled" and row.attempts == 1 and row.next_retry_at is None
        assert list(db.scalars(select(MailMessage))) == []
        assert all(not state.cursor_json for state in db.scalars(select(MailSyncState)))
        # Restore only our synthetic admin so the writer fixture can finish.
        db.get(User, c.admin["user"]["id"]).login_blocked = False
        db.commit()


@pytest.mark.parametrize("at_commit", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("accepted", [False, True])
def test_commit_unknown_never_retries_provider_or_writes_failure(
    mail, monkeypatch, at_commit, accepted
):
    from miy_api.domains.mail.sync_jobs import MailSyncCommitUnknown

    c = mail
    with c.worker_factory() as db:
        commit = db.commit
        count = 0

        def uncertain():
            nonlocal count
            count += 1
            if count == at_commit:
                if accepted:
                    commit()
                raise OSError("Synthetic acknowledgement loss")
            commit()

        monkeypatch.setattr(db, "commit", uncertain)
        with pytest.raises(MailSyncCommitUnknown):
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
        assert count == at_commit
    assert (c.client.list_calls, c.client.sync_calls) == (int(at_commit >= 3), int(at_commit >= 4))
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        expected = "pending" if at_commit == 1 and not accepted else "processing"
        if at_commit == 5 and accepted:
            expected = "succeeded"
        assert row.status == expected and row.next_retry_at is None and row.last_error is None


def test_normal_sync_and_provider_retry_preserve_existing_contract(mail):
    c = mail

    def fail():
        raise RuntimeError("Synthetic provider failure")

    c.client.on_sync = fail
    with c.worker_factory() as db:
        with pytest.raises(service.MailSyncRetryScheduled):
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
    with c.factory.begin() as db:
        job = db.get(MailSyncJob, c.job_id)
        assert job.status == "pending" and job.attempts == 1 and job.next_retry_at is not None
        assert job.lease_owner is None and job.lease_expires_at is None
        job.next_retry_at = utcnow_naive() - timedelta(seconds=1)
    c.client.on_sync = lambda: None
    with c.worker_factory() as db:
        assert (
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="next")
            == "synced:1"
        )
    with c.factory() as db:
        job = db.get(MailSyncJob, c.job_id)
        assert job.status == "succeeded" and job.attempts == 2
        assert db.get(MailAccount, c.account_id).status == "ready"
        assert db.scalar(select(MailSyncState)).cursor_json == {"highest_seen_uid": 1}


@pytest.mark.parametrize("next_phase", [False, True])
def test_lease_expiry_finishes_locked_outcome_but_cannot_admit_next_call(
    mail, monkeypatch, next_phase
):
    from miy_api.domains.mail import sync_jobs
    from miy_api.domains.mail.clients import MailboxInfo

    c = mail
    if next_phase:
        original = c.client.list_mailboxes
        c.client.list_mailboxes = lambda settings: (
            original(settings)
            + [MailboxInfo(provider_mailbox_id="Archive", display_name="Archive", role="folder")]
        )

    def expires():
        with c.factory() as observer:
            row = observer.get(MailSyncJob, c.job_id)
            deadline = row.lease_expires_at
            # A competing claim cannot steal the row during admitted I/O.
            assert (
                observer.scalar(
                    select(MailSyncJob)
                    .where(MailSyncJob.id == c.job_id)
                    .with_for_update(skip_locked=True)
                )
                is None
            )
        monkeypatch.setattr(sync_jobs, "utcnow_naive", lambda: deadline + timedelta(seconds=1))

    c.client.on_sync = expires
    with c.worker_factory() as db:
        assert service.process_mail_sync_job(
            db, c.job_id, client=c.client, lease_owner="original"
        ) == ("lost_lease" if next_phase else "synced:1")
    assert c.client.sync_calls == 1
    with c.factory() as db:
        assert len(list(db.scalars(select(MailMessage)))) == (0 if next_phase else 1)
        assert db.get(MailSyncJob, c.job_id).status == ("processing" if next_phase else "succeeded")


@pytest.mark.parametrize("failure", ["provider", "revoked"])
def test_stale_failure_or_cancellation_cannot_overwrite_replacement(mail, monkeypatch, failure):
    from miy_api.domains.mail.sync_policy import MailSyncAccessRevoked

    c = mail

    def replace_and_fail(*_args, **_kwargs):
        with c.factory.begin() as other:
            row = other.get(MailSyncJob, c.job_id)
            row.attempts = 2
            row.lease_owner = "replacement"
        if failure == "revoked":
            raise MailSyncAccessRevoked("Synthetic revocation")
        raise RuntimeError("Synthetic provider failure")

    monkeypatch.setattr(service, "sync_account", replace_and_fail)
    with c.worker_factory() as db:
        assert (
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
            == "lost_lease"
        )
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert (row.status, row.attempts, row.lease_owner) == ("processing", 2, "replacement")
        assert row.last_error is None and row.next_retry_at is None


@pytest.mark.parametrize("at_commit", [4, 5])
@pytest.mark.parametrize("accepted", [False, True])
def test_unknown_provider_error_record_commit_cannot_schedule_retry(
    mail, monkeypatch, at_commit, accepted
):
    from miy_api.domains.mail.sync_jobs import MailSyncCommitUnknown

    c = mail

    def provider_failure():
        raise RuntimeError("Synthetic provider failure")

    c.client.on_sync = provider_failure
    with c.worker_factory() as db:
        commit = db.commit
        count = 0

        def uncertain():
            nonlocal count
            count += 1
            if count == at_commit:
                if accepted:
                    commit()
                raise OSError("Synthetic acknowledgement loss")
            commit()

        monkeypatch.setattr(db, "commit", uncertain)
        with pytest.raises(MailSyncCommitUnknown):
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
        assert count == at_commit
    assert c.client.sync_calls == 1
    with c.factory() as db:
        row = db.get(MailSyncJob, c.job_id)
        assert row.status == ("pending" if at_commit == 5 and accepted else "processing")
        assert row.attempts == 1


def test_rollback_failure_does_not_turn_commit_unknown_into_retry(mail, monkeypatch):
    from miy_api.domains.mail.sync_jobs import MailSyncCommitUnknown

    c = mail
    with c.worker_factory() as db:
        commit = db.commit
        count = 0

        def uncertain():
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("Synthetic lost connection")
            commit()

        def failed_rollback():
            raise OSError("Synthetic disconnected rollback")

        monkeypatch.setattr(db, "commit", uncertain)
        monkeypatch.setattr(db, "rollback", failed_rollback)
        with pytest.raises(MailSyncCommitUnknown, match="^mail_sync_commit_unknown$"):
            service.process_mail_sync_job(db, c.job_id, client=c.client, lease_owner="original")
        assert count == 3
    assert c.client.sync_calls == 0
