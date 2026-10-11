from __future__ import annotations

from miy_worker.tasks import mail
from miy_api.domains.mail.sync_policy import MailSyncAccessRevoked


def test_mail_tasks_use_actual_celery_execution_deadlines() -> None:
    for task in (mail.sync_mail_job, mail.sync_mail_account):
        assert task.time_limit == mail._MAIL_SYNC_TASK_TIME_LIMIT
        assert task.soft_time_limit == mail._MAIL_SYNC_SOFT_TIME_LIMIT
        assert task._get_exec_options()["time_limit"] == mail._MAIL_SYNC_TASK_TIME_LIMIT
        assert task._get_exec_options()["soft_time_limit"] == mail._MAIL_SYNC_SOFT_TIME_LIMIT


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_legacy_sync_task_rechecks_platform_gate(monkeypatch) -> None:
    session = _Session()
    monkeypatch.setattr(mail, "_session_factory", lambda: lambda: session)
    monkeypatch.setattr(mail, "mail_background_sync_enabled", lambda _db: False)
    monkeypatch.setattr(
        mail,
        "sync_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider sync must not run while Mail is disabled")
        ),
    )

    assert mail.sync_mail_account.run("account-1") == "cancelled:disabled"
    assert session.closed is True


def test_direct_sync_task_terminalizes_revoked_personal_access(monkeypatch) -> None:
    session = _Session()
    monkeypatch.setattr(mail, "_session_factory", lambda: lambda: session)
    monkeypatch.setattr(mail, "mail_background_sync_enabled", lambda _db: True)

    def revoked(*_args, **_kwargs):
        raise MailSyncAccessRevoked("Mail sync access was revoked.")

    monkeypatch.setattr(mail, "sync_account", revoked)

    assert mail.sync_mail_account.run("account-1") == "cancelled:access_revoked"
    assert session.closed is True
