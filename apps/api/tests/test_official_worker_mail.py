"""Real source/claim transactions; all provider responses are synthetic."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from company_admission_fixture import seed_company_app_access
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_mail_personal_scope import SyncClient, _account
from test_official_writer_fence import writer as writer

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


@pytest.mark.parametrize("phase", ["fetch"])
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


@pytest.mark.parametrize("at_commit,accepted", [(1, False), (2, True), (4, False), (5, True)])
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
        message = db.scalar(select(MailMessage))
        assert message.account_id == c.account_id
        assert message.body.text_body == "Disposable mail fixture"
