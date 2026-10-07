"""Completed registration receipts share the resource transaction; there is no work queue."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class AppBootstrapOperation(Base):
    __tablename__ = "independent_app_bootstrap_operations"

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    app_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_definitions.app_id"),
        unique=True,
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"),
        unique=True,
    )
    payload_digest: Mapped[str] = mapped_column(String(71))
    definition_digest: Mapped[str] = mapped_column(String(71))
    source_revision: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
