from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.mail.clients import MailboxInfo, MailConnectionSettings
from miy_api.domains.mail.models import MailAccount, MailMailbox, MailSyncState


def _session() -> Session:
    from company_admission_fixture import company_authority_tables, seed_company_app_access

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            *company_authority_tables(),
            MailAccount.__table__,
            MailMailbox.__table__,
            MailSyncState.__table__,
        ],
    )
    session = Session(engine)
    seed_company_app_access(session, app_ids=["mail"])
    return session


def _settings(protocol: str = "imap") -> MailConnectionSettings:
    return MailConnectionSettings(
        protocol=protocol,
        incoming_host="mail.example.test",
        incoming_port=993,
        incoming_security="ssl",
        incoming_username="user",
        incoming_password="password",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="user",
        smtp_password="password",
        email_address="user@example.test",
        display_name="User",
        provider_kind=protocol,
    )


def _account() -> MailAccount:
    return MailAccount(
        id="account-1",
        user_id="user-1",
        email_address="user@example.test",
        display_name="User",
        protocol="imap",
        provider_kind="imap",
        incoming_host="mail.example.test",
        incoming_port=993,
        incoming_security="ssl",
        incoming_username="user",
        incoming_password_encrypted="encrypted",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="user",
        smtp_password_encrypted="encrypted",
    )


def _seed_account(session: Session) -> MailAccount:
    account = _account()
    session.add_all(
        [
            User(
                id="user-1",
                login_id="user-1",
                email="user-1@miy.local",
                full_name="User One",
                password_hash="hash",
                status="active",
            ),
            account,
        ]
    )
    session.commit()
    return account


class MultiMailboxClient:
    def list_mailboxes(self, settings: MailConnectionSettings) -> list[MailboxInfo]:
        assert settings.incoming_password == "password"
        return [
            MailboxInfo(provider_mailbox_id="Projects", display_name="Projects"),
            MailboxInfo(provider_mailbox_id="INBOX", display_name="Inbox", role="inbox"),
            MailboxInfo(
                provider_mailbox_id="[Gmail]/Sent Mail",
                display_name="Sent",
                role="sent",
                sync_enabled=False,
            ),
        ]
