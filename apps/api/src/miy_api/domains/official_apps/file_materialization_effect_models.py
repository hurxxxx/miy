"""Core Files effects retain identities and unknowns, never Source bodies."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base


class FileMaterializationOperation(Base):
    __tablename__ = "core_file_materialization_operations"
    __table_args__ = (
        UniqueConstraint(
            "event_sequence",
            "keyword_generation_id",
            "vector_generation_id",
            name="uq_core_file_materialization_event_pair",
        ),
        CheckConstraint(
            "resource_type='file_manager_file' AND length(trim(resource_id))>0",
            name="ck_core_file_materialization_resource",
        ),
        CheckConstraint(
            "event_sequence>0 AND projection_version>0 AND source_revision>0 "
            "AND partition_metadata_version>0",
            name="ck_core_file_materialization_versions",
        ),
        CheckConstraint(
            "change_kind IN ('content','visibility','delete','repair') "
            "AND desired_state IN ('active','deleted')",
            name="ck_core_file_materialization_event",
        ),
        CheckConstraint(
            "keyword_generation_id<>vector_generation_id "
            "AND keyword_schema_version=3 AND vector_schema_version=1",
            name="ck_core_file_materialization_pair",
        ),
        CheckConstraint(
            "source_payload_digest ~ '^[a-f0-9]{64}$' "
            "AND header_digest ~ '^[a-f0-9]{64}$' "
            "AND armed_xact_id ~ '^[0-9]{1,20}$'",
            name="ck_core_file_materialization_digests",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(desired_state='active' AND source_extracted_at IS NOT NULL "
            "AND content_checksum ~ '^[a-f0-9]{64}$') "
            "OR (desired_state='deleted' AND source_extracted_at IS NULL)",
            name="ck_core_file_materialization_result",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "issuer_role_oid>0 AND length(issuer_role_name)>0",
            name="ck_core_file_materialization_issuer",
        ),
        CheckConstraint(
            "(state='armed' AND completed_at IS NULL) "
            "OR (state='complete' AND completed_at IS NOT NULL)",
            name="ck_core_file_materialization_state",
        ),
        Index(
            "uq_core_file_materialization_armed_keyword",
            "resource_id",
            "keyword_generation_id",
            unique=True,
            postgresql_where=text("state='armed'"),
            sqlite_where=text("state='armed'"),
        ),
        Index(
            "uq_core_file_materialization_armed_vector",
            "resource_id",
            "vector_generation_id",
            unique=True,
            postgresql_where=text("state='armed'"),
            sqlite_where=text("state='armed'"),
        ),
        Index("ix_core_file_materialization_keyword_state", "keyword_generation_id", "state"),
        Index("ix_core_file_materialization_vector_state", "vector_generation_id", "state"),
    )

    operation_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    event_sequence: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT"),
    )
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(255))
    projection_version: Mapped[int] = mapped_column(BigInteger)
    retrieval_partition_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("retrieval_partitions.id", ondelete="RESTRICT")
    )
    partition_metadata_version: Mapped[int] = mapped_column(Integer)
    change_kind: Mapped[str] = mapped_column(String(16))
    desired_state: Mapped[str] = mapped_column(String(16))
    content_checksum: Mapped[str | None] = mapped_column(String(128))
    visibility_checksum: Mapped[str | None] = mapped_column(String(128))
    source_event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("official_projection_outbox.event_id", ondelete="RESTRICT")
    )
    source_revision: Mapped[int] = mapped_column(BigInteger)
    source_payload_digest: Mapped[str] = mapped_column(String(64))
    source_extracted_at: Mapped[datetime | None] = mapped_column(DateTime)
    keyword_generation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("retrieval_projection_generations.id", ondelete="RESTRICT")
    )
    vector_generation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("retrieval_projection_generations.id", ondelete="RESTRICT")
    )
    generation_key: Mapped[str] = mapped_column(String(64))
    keyword_physical_name: Mapped[str] = mapped_column(String(255))
    vector_physical_name: Mapped[str] = mapped_column(String(255))
    keyword_schema_version: Mapped[int] = mapped_column(Integer)
    vector_schema_version: Mapped[int] = mapped_column(Integer)
    issuer_role_oid: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    issuer_role_name: Mapped[str] = mapped_column(String(63), server_default=FetchedValue())
    armed_xact_id: Mapped[str] = mapped_column(String(20), server_default=FetchedValue())
    header_digest: Mapped[str] = mapped_column(String(64), server_default=FetchedValue())
    state: Mapped[str] = mapped_column(String(16), server_default=text("'armed'"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
