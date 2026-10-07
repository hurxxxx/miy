"""Read current File content identity without granting access or loading bytes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.domains.files.models import FileManagerFile

_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_INVALID_PARTITION = object()


@dataclass(frozen=True)
class CurrentFileContent:
    content_checksum: str
    retrieval_partition_id: UUID | None
    extracted_at: str


def file_extraction_result_marker(extracted_at: datetime | None) -> str | None:
    """Fixed Source extraction-result stamp; raw input SHA alone is insufficient."""
    if type(extracted_at) is not datetime:
        return None
    aware = (
        extracted_at.replace(tzinfo=UTC)
        if extracted_at.tzinfo is None
        else extracted_at.astimezone(UTC)
    )
    return aware.isoformat(timespec="microseconds")


def _valid_checksum(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _partition(value: object) -> UUID | None | object:
    if value is None or type(value) is UUID:
        return value
    if type(value) is str:
        try:
            return UUID(value)
        except ValueError:
            pass
    return _INVALID_PARTITION


def load_current_file_content(
    db: Session, *, file_ids: Iterable[str]
) -> Mapping[str, CurrentFileContent]:
    """Return immutable current ready witnesses from one column-only query.

    IDs come from the caller's already bounded candidate set. No ORM identity
    cache, autoflush, artifact/storage read or ACL decision participates here.
    """
    identifiers = tuple(dict.fromkeys(value for value in file_ids if type(value) is str and value))
    content: dict[str, CurrentFileContent] = {}
    if not identifiers:
        return MappingProxyType(content)
    with db.no_autoflush:
        rows = db.execute(
            select(
                FileManagerFile.id,
                FileManagerFile.deleted_at,
                FileManagerFile.extraction_status,
                FileManagerFile.extraction_content_checksum,
                FileManagerFile.retrieval_partition_id,
                FileManagerFile.extracted_at,
            ).where(FileManagerFile.id.in_(identifiers))
        )
        for identifier, deleted_at, status, checksum, partition_id, extracted_at in rows:
            if deleted_at is not None or status != "ready" or not _valid_checksum(checksum):
                continue
            partition = _partition(partition_id)
            marker = file_extraction_result_marker(extracted_at)
            if partition is _INVALID_PARTITION or marker is None:
                continue
            content[identifier] = CurrentFileContent(checksum, partition, marker)
    return MappingProxyType(content)


def file_candidate_matches_current_content(
    content: CurrentFileContent | None,
    *,
    candidate_checksum: object,
    candidate_partition_id: object,
    candidate_extracted_at: object,
) -> bool:
    """Narrow a candidate; legacy None partitions match only Source None."""
    if (
        content is None
        or not _valid_checksum(candidate_checksum)
        or type(candidate_extracted_at) is not str
        or candidate_extracted_at != content.extracted_at
    ):
        return False
    partition = _partition(candidate_partition_id)
    return (
        partition is not _INVALID_PARTITION
        and candidate_checksum == content.content_checksum
        and partition == content.retrieval_partition_id
    )
