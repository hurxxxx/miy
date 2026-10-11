from __future__ import annotations

from datetime import datetime

import pytest
from dev_accounts import auth_headers, dev_login
from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.mail import clients as mail_clients
from miy_api.domains.mail import service as mail_service
from miy_api.domains.mail.clients import (
    FetchedAttachment,
    FetchedMessage,
    MailboxInfo,
    MailboxSyncBatch,
    MailConnectionSettings,
)
from miy_api.domains.mail.models import (
    MailAccount,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailMessageBody,
)


class FakeMailClient:
    sent: list[dict]

    def __init__(self) -> None:
        self.sent = []

    def test_incoming(self, settings: MailConnectionSettings) -> None:
        assert settings.incoming_password == "mail-password"

    def test_smtp(self, settings: MailConnectionSettings) -> None:
        assert settings.smtp_password == "mail-password"

    def fetch_recent(
        self,
        settings: MailConnectionSettings,
        *,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> list[FetchedMessage]:
        assert settings.incoming_password == "mail-password"
        assert folder == "INBOX"
        assert limit >= 1
        return [
            FetchedMessage(
                provider_uid="uid-001",
                provider_message_id="<message-001@example.test>",
                thread_key="<message-001@example.test>",
                subject="Quarterly report",
                from_text="sender@example.test",
                to_text="admin@example.test",
                cc_text="",
                text_body="Please review the quarterly report by Friday.",
                html_body="",
                snippet="Please review the quarterly report by Friday.",
                received_at=datetime(2026, 5, 12, 9, 0, 0),
                sent_at=datetime(2026, 5, 12, 9, 0, 0),
                is_read=False,
                attachments=(
                    FetchedAttachment(
                        filename="report.pdf",
                        content_type="application/pdf",
                        size_bytes=128,
                    ),
                ),
                remote_identity="imap:10:uid-001",
                remote_flags={"provider": "imap", "flags": []},
            )
        ]

    def sync_mailbox(
        self,
        settings: MailConnectionSettings,
        *,
        mailbox: str = "INBOX",
        cursor: dict | None = None,
        initial_limit: int = 50,
    ) -> MailboxSyncBatch:
        assert settings.incoming_password == "mail-password"
        assert mailbox == "INBOX"
        assert initial_limit >= 1
        return MailboxSyncBatch(
            messages=tuple(self.fetch_recent(settings, folder=mailbox, limit=initial_limit)),
            cursor={"uidvalidity": "10", "highest_seen_uid": 1, "uidnext": "2"},
        )

    def send_draft(
        self,
        settings: MailConnectionSettings,
        *,
        to_text: str,
        cc_text: str,
        bcc_text: str,
        subject: str,
        text_body: str,
        html_body: str = "",
    ) -> str | None:
        assert settings.smtp_password == "mail-password"
        self.sent.append(
            {
                "to_text": to_text,
                "subject": subject,
                "text_body": text_body,
            }
        )
        return "<sent-message@example.test>"


class SequenceMailClient(FakeMailClient):
    def __init__(self, batches: list[MailboxSyncBatch]) -> None:
        super().__init__()
        self.batches = batches

    def sync_mailbox(
        self,
        settings: MailConnectionSettings,
        *,
        mailbox: str = "INBOX",
        cursor: dict | None = None,
        initial_limit: int = 50,
    ) -> MailboxSyncBatch:
        del settings, mailbox, cursor, initial_limit
        assert self.batches
        return self.batches.pop(0)


class MultiMailboxMailClient(FakeMailClient):
    def __init__(self) -> None:
        super().__init__()
        self.synced_mailboxes: list[str] = []

    def list_mailboxes(self, settings: MailConnectionSettings) -> list[MailboxInfo]:
        assert settings.incoming_password == "mail-password"
        return [
            MailboxInfo(provider_mailbox_id="INBOX", display_name="INBOX", role="inbox"),
            MailboxInfo(
                provider_mailbox_id="Projects",
                display_name="Projects",
                role="folder",
            ),
            MailboxInfo(
                provider_mailbox_id="[Gmail]/Sent Mail",
                display_name="Sent Mail",
                role="sent",
                sync_enabled=False,
            ),
        ]

    def sync_mailbox(
        self,
        settings: MailConnectionSettings,
        *,
        mailbox: str = "INBOX",
        cursor: dict | None = None,
        initial_limit: int = 50,
    ) -> MailboxSyncBatch:
        del cursor
        assert settings.incoming_password == "mail-password"
        assert initial_limit >= 1
        self.synced_mailboxes.append(mailbox)
        subject = "Inbox report" if mailbox == "INBOX" else "Project report"
        uid = "uid-inbox" if mailbox == "INBOX" else "uid-projects"
        return MailboxSyncBatch(
            messages=(
                FetchedMessage(
                    provider_uid=uid,
                    provider_message_id=f"<{uid}@example.test>",
                    thread_key=f"<{uid}@example.test>",
                    subject=subject,
                    from_text="sender@example.test",
                    to_text="admin@example.test",
                    cc_text="",
                    text_body=subject,
                    html_body="",
                    snippet=subject,
                    received_at=datetime(2026, 5, 12, 9, 0, 0),
                    sent_at=datetime(2026, 5, 12, 9, 0, 0),
                    is_read=False,
                    attachments=(),
                    remote_identity=f"imap:{mailbox}:10:{uid}",
                    remote_flags={"provider": "imap", "folder": mailbox},
                ),
            ),
            cursor={"uidvalidity": "10", "highest_seen_uid": 1, "uidnext": "2"},
        )


def _payload() -> dict:
    return {
        "email_address": "admin@example.test",
        "display_name": "Admin Mail",
        "protocol": "imap",
        "incoming_host": "imap.example.test",
        "incoming_port": 993,
        "incoming_security": "ssl",
        "incoming_username": "admin@example.test",
        "incoming_password": "mail-password",
        "smtp_host": "smtp.example.test",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "admin@example.test",
        "smtp_password": "mail-password",
    }


def _settings(protocol: str = "imap") -> MailConnectionSettings:
    return MailConnectionSettings(
        protocol=protocol,
        incoming_host="imap.example.test",
        incoming_port=993,
        incoming_security="ssl",
        incoming_username="admin@example.test",
        incoming_password="mail-password",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="admin@example.test",
        smtp_password="mail-password",
        email_address="admin@example.test",
        provider_kind=protocol,
    )


@pytest.mark.slow
def test_stored_account_sync_revalidates_mail_egress_policy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMailClient()
    monkeypatch.setattr(mail_service, "_mail_client", lambda: fake)
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    response = client.post(
        "/api/v1/mail/accounts",
        headers=headers,
        json=_payload(),
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["id"]

    with get_session_factory()() as db:
        account = db.get(MailAccount, account_id)
        assert account is not None
        account.incoming_host = "127.0.0.1"
        db.add(account)
        db.commit()

        with pytest.raises(mail_clients.MailConnectionPolicyError):
            mail_service.sync_account(db, account_id=account.id, client=fake)
        db.refresh(account)
        assert account.last_error == "Mail host resolves to a blocked network."


@pytest.mark.slow
def test_send_draft_revalidates_stored_smtp_policy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMailClient()
    monkeypatch.setattr(mail_service, "_mail_client", lambda: fake)
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    response = client.post(
        "/api/v1/mail/accounts",
        headers=headers,
        json=_payload(),
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["id"]
    with get_session_factory()() as db:
        account = db.get(MailAccount, account_id)
        assert account is not None
        account.smtp_security = "none"
        draft = MailDraft(
            id="mail-policy-draft",
            account_id=account.id,
            to_text="receiver@example.test",
            cc_text="",
            bcc_text="",
            subject="Policy check",
            text_body="Hello",
            html_body="",
            ai_generated=False,
            status="draft",
        )
        db.add_all([account, draft])
        db.commit()

    send_response = client.post(
        "/api/v1/mail/drafts/mail-policy-draft/send",
        headers=headers,
    )

    assert send_response.status_code == 502, send_response.text
    assert fake.sent == []


def test_mail_sync_remote_delete_purges_body_and_attachments(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mail_service, "_mail_client", lambda: FakeMailClient())
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    response = client.post(
        "/api/v1/mail/accounts",
        headers=headers,
        json=_payload(),
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["id"]
    message = FakeMailClient().fetch_recent(_settings())[0]
    sequence = SequenceMailClient(
        [
            MailboxSyncBatch(
                messages=(message,),
                cursor={"uidvalidity": "10", "highest_seen_uid": 1, "known_uids": ["uid-001"]},
            ),
            MailboxSyncBatch(
                messages=(),
                cursor={"uidvalidity": "10", "highest_seen_uid": 1, "known_uids": []},
                deleted_remote_identities=("imap:10:uid-001",),
            ),
        ]
    )

    with get_session_factory()() as db:
        first = mail_service.sync_account(db, account_id=account_id, client=sequence)
        assert first.new_count == 1
        row = db.query(MailMessage).filter(MailMessage.account_id == account_id).one()
        message_id = row.id
        assert (
            db.query(MailMessageBody).filter(MailMessageBody.message_id == message_id).count() == 1
        )
        assert db.query(MailAttachment).filter(MailAttachment.message_id == message_id).count() == 1

        second = mail_service.sync_account(db, account_id=account_id, client=sequence)
        assert second.deleted_count == 1
        row = db.get(MailMessage, message_id)
        assert row is not None
        assert row.remote_deleted_at is not None
        assert row.has_attachments is False
        assert row.body_status == "remote_deleted"
        assert (
            db.query(MailMessageBody).filter(MailMessageBody.message_id == message_id).count() == 0
        )
        assert db.query(MailAttachment).filter(MailAttachment.message_id == message_id).count() == 0

    list_response = client.get(
        "/api/v1/mail/messages",
        headers=headers,
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["items"] == []


def test_mail_account_unique_constraint_race_returns_conflict_without_partial_audit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import func, select

    from miy_api.domains.auth.models import AuditLog

    monkeypatch.setattr(mail_service, "_mail_client", lambda: FakeMailClient())
    headers = auth_headers(dev_login(client)["token"])
    first = client.post("/api/v1/mail/accounts", headers=headers, json=_payload())
    assert first.status_code == 201, first.text
    with get_session_factory()() as db:
        before = db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "mail.account.create")
        )
    # A concurrent writer can commit after preflight; the real database constraint remains authoritative.
    monkeypatch.setattr(mail_service, "_ensure_email_available", lambda *_args, **_kwargs: None)
    raced = client.post("/api/v1/mail/accounts", headers=headers, json=_payload())
    assert raced.status_code == 409, raced.text
    assert raced.json()["code"] == "mail.account_duplicate"
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(MailAccount)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "mail.account.create")
            )
            == before
        )
