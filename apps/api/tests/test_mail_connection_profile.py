from __future__ import annotations

from miy_api.domains.mail.clients import MailConnectionSettings
from miy_api.domains.mail.connection_profile import (
    encrypt_connection_secrets,
    incoming_identity,
    settings_from_account,
    settings_from_account_update,
)
from miy_api.domains.mail.models import MailAccount
from miy_api.domains.mail.schemas import (
    MailAccountUpdateRequest,
)


def test_account_update_reuses_blank_passwords_and_detects_incoming_identity_change() -> None:
    current = _settings()
    secrets = encrypt_connection_secrets(current)
    account = _account(
        incoming_password_encrypted=secrets.incoming_password_encrypted,
        smtp_password_encrypted=secrets.smtp_password_encrypted,
    )

    restored = settings_from_account(account)
    assert restored.incoming_password == current.incoming_password
    assert restored.smtp_password == current.smtp_password
    updated = settings_from_account_update(
        account,
        MailAccountUpdateRequest(
            display_name=" Updated ",
            incoming_host=" imap2.example.test ",
            incoming_password="",
            smtp_password="",
        ),
    )

    assert updated.display_name == "Updated"
    assert updated.incoming_host == "imap2.example.test"
    assert updated.incoming_password == "incoming-secret"
    assert updated.smtp_password == "smtp-secret"
    assert incoming_identity(account) != incoming_identity(updated)


def _settings(**overrides: object) -> MailConnectionSettings:
    settings = MailConnectionSettings(
        protocol="imap",
        incoming_host="imap.example.test",
        incoming_port=993,
        incoming_security="ssl",
        incoming_username="user",
        incoming_password="incoming-secret",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="smtp-user",
        smtp_password="smtp-secret",
        email_address="user@example.test",
        display_name="User",
        provider_kind="imap",
    )
    return MailConnectionSettings(
        **{
            **settings.__dict__,
            **overrides,
        }
    )


def _account(**overrides: object) -> MailAccount:
    values = {
        "id": "account-1",
        "user_id": "user-1",
        "email_address": "user@example.test",
        "display_name": "User",
        "protocol": "imap",
        "provider_kind": "imap",
        "incoming_host": "imap.example.test",
        "incoming_port": 993,
        "incoming_security": "ssl",
        "incoming_username": "user",
        "incoming_password_encrypted": "incoming-encrypted",
        "smtp_host": "smtp.example.test",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "smtp-user",
        "smtp_password_encrypted": "smtp-encrypted",
    }
    values.update(overrides)
    return MailAccount(**values)
