"""Pure bounded Files extraction artifact contract shared by Source and Core.

This module supplies data validation only: no database, settings, storage,
provider, app admission or execution authority is constructed or granted.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from miy_api.domains.document_processing.contracts import EvidenceBlock

MAX_FILES_RAG_EXTRACTED_CHARS = 240_000

EXTERNAL_SOURCE_SAFE_METADATA_KEYS = frozenset(
    {
        "origin_source_kind",
        "origin_source_kind_filter",
        "source_title",
        "author",
        "author_filter",
        "authored_at",
        "department",
        "department_filter",
        "document_type",
        "document_type_filter",
        "source_updated_at",
    }
)

MAX_FILE_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_FILE_ARTIFACT_BLOCKS = 4_096
MAX_FILE_ARTIFACT_ROWS = 4_096
MAX_FILE_ARTIFACT_CELLS = 16_384
MAX_FILE_ARTIFACT_METADATA_BYTES = 64 * 1024
MAX_FILE_ARTIFACT_METADATA_DEPTH = 8
MAX_FILE_ARTIFACT_METADATA_NODES = 4_096
MAX_FILE_ARTIFACT_METADATA_KEYS = 1_024
MAX_FILE_ARTIFACT_FIELD_CHARS = 4_096

_CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")

_RESERVED_PROJECTION_METADATA_KEYS = EXTERNAL_SOURCE_SAFE_METADATA_KEYS | frozenset(
    {
        "origin_ref",
        "content_modality",
        "filename",
        "content_type",
        "size_bytes",
        "visibility",
        "corpus_id",
        "folder_id",
        "content_checksum",
        "chunking",
    }
)


@dataclass(frozen=True)
class FileExtractionArtifact:
    content_checksum: str
    text: str
    blocks: list[EvidenceBlock]
    metadata: dict[str, Any]


class FileArtifactControlError(RuntimeError):
    code = "file_artifact_control"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(self.code)


class FileArtifactNotReady(FileArtifactControlError):
    code = "file_artifact_not_ready"


class FileArtifactInvalid(FileArtifactControlError):
    code = "file_artifact_invalid"


class FileArtifactChecksumMismatch(FileArtifactInvalid):
    code = "file_artifact_checksum_mismatch"


def is_file_artifact_checksum(value: object) -> bool:
    return isinstance(value, str) and _CHECKSUM.fullmatch(value) is not None


def _canonical_bytes(value: object, *, max_bytes: int = MAX_FILE_ARTIFACT_BYTES) -> bytes:
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        parts = []
        size = 0
        for chunk in encoder.iterencode(value):
            part = chunk.encode("utf-8")
            size += len(part)
            if size > max_bytes:
                raise FileArtifactInvalid("artifact_budget_exceeded")
            parts.append(part)
        return b"".join(parts)
    except (TypeError, ValueError, UnicodeError, OverflowError) as error:
        raise FileArtifactInvalid("artifact_serialization_invalid") from error


def _validate_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict):
        raise FileArtifactInvalid("metadata_invalid")
    if metadata.keys() & _RESERVED_PROJECTION_METADATA_KEYS:
        # The unchanged public builder spreads artifact metadata after Source
        # fields. A bounded artifact cannot override those authoritative values.
        raise FileArtifactInvalid("metadata_reserved_key")
    stack = [(metadata, 0)]
    nodes = keys = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_FILE_ARTIFACT_METADATA_NODES or depth > MAX_FILE_ARTIFACT_METADATA_DEPTH:
            raise FileArtifactInvalid("metadata_budget_exceeded")
        if isinstance(value, dict):
            keys += len(value)
            if keys > MAX_FILE_ARTIFACT_METADATA_KEYS:
                raise FileArtifactInvalid("metadata_budget_exceeded")
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise FileArtifactInvalid("metadata_key_invalid")
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            if len(value) > MAX_FILE_ARTIFACT_METADATA_NODES:
                raise FileArtifactInvalid("metadata_budget_exceeded")
            stack.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            if len(value) > MAX_FILE_ARTIFACT_FIELD_CHARS:
                raise FileArtifactInvalid("metadata_budget_exceeded")
        elif value is None or type(value) is bool:
            pass
        elif type(value) is int:
            if abs(value) > 2**63 - 1:
                raise FileArtifactInvalid("metadata_number_invalid")
        elif type(value) is float:
            if not math.isfinite(value):
                raise FileArtifactInvalid("metadata_number_invalid")
        else:
            raise FileArtifactInvalid("metadata_value_invalid")
    _canonical_bytes(metadata, max_bytes=MAX_FILE_ARTIFACT_METADATA_BYTES)
    return metadata


def validate_file_extraction_artifact(
    *,
    file_id: str,
    content_checksum: object,
    text: object,
    blocks: object,
    metadata: object,
) -> FileExtractionArtifact:
    """Validate complete raw canonical fields without Source or Core authority."""
    if not is_file_artifact_checksum(content_checksum):
        raise FileArtifactInvalid("artifact_checksum_invalid")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_FILES_RAG_EXTRACTED_CHARS:
        raise FileArtifactInvalid("artifact_text_invalid")
    raw_blocks = blocks
    if not isinstance(raw_blocks, list) or not 0 < len(raw_blocks) <= MAX_FILE_ARTIFACT_BLOCKS:
        raise FileArtifactInvalid("artifact_blocks_invalid")
    blocks = []
    block_ids = set()
    text_chars = row_chars = rows_count = cells_count = 0
    required = {
        "document_id",
        "block_id",
        "locator_kind",
        "locator_label",
        "section_path",
        "block_kind",
        "text",
    }
    for raw in raw_blocks:
        if (
            not isinstance(raw, dict)
            or not required <= raw.keys()
            or raw.keys() - required - {"rows"}
        ):
            raise FileArtifactInvalid("artifact_block_invalid")
        for field in required - {"text"}:
            value = raw[field]
            if not isinstance(value, str) or len(value) > MAX_FILE_ARTIFACT_FIELD_CHARS:
                raise FileArtifactInvalid("artifact_block_field_invalid")
        if raw["document_id"] != file_id or not raw["block_id"] or raw["block_id"] in block_ids:
            raise FileArtifactInvalid("artifact_block_identity_invalid")
        block_ids.add(raw["block_id"])
        if not isinstance(raw["text"], str) or not raw["text"].strip():
            raise FileArtifactInvalid("artifact_block_text_invalid")
        text_chars += len(raw["text"])
        if text_chars > MAX_FILES_RAG_EXTRACTED_CHARS:
            raise FileArtifactInvalid("artifact_evidence_budget_exceeded")
        rows = raw.get("rows", [])
        if not isinstance(rows, list):
            raise FileArtifactInvalid("artifact_rows_invalid")
        rows_count += len(rows)
        if rows_count > MAX_FILE_ARTIFACT_ROWS:
            raise FileArtifactInvalid("artifact_evidence_budget_exceeded")
        for row in rows:
            if not isinstance(row, list):
                raise FileArtifactInvalid("artifact_rows_invalid")
            cells_count += len(row)
            if cells_count > MAX_FILE_ARTIFACT_CELLS:
                raise FileArtifactInvalid("artifact_evidence_budget_exceeded")
            for cell in row:
                if not isinstance(cell, str):
                    raise FileArtifactInvalid("artifact_rows_invalid")
                row_chars += len(cell)
                if row_chars > MAX_FILES_RAG_EXTRACTED_CHARS:
                    raise FileArtifactInvalid("artifact_evidence_budget_exceeded")
        blocks.append(EvidenceBlock(**raw))
    metadata = _validate_metadata(metadata)
    serialized = {
        "content_checksum": content_checksum,
        "text": text,
        "blocks": raw_blocks,
        "metadata": metadata,
    }
    _canonical_bytes(serialized)
    return FileExtractionArtifact(content_checksum, text, blocks, dict(metadata))


__all__ = [
    "FileExtractionArtifact",
    "FileArtifactControlError",
    "FileArtifactNotReady",
    "FileArtifactInvalid",
    "FileArtifactChecksumMismatch",
    "EXTERNAL_SOURCE_SAFE_METADATA_KEYS",
    "MAX_FILES_RAG_EXTRACTED_CHARS",
    "MAX_FILE_ARTIFACT_BYTES",
    "MAX_FILE_ARTIFACT_BLOCKS",
    "MAX_FILE_ARTIFACT_ROWS",
    "MAX_FILE_ARTIFACT_CELLS",
    "MAX_FILE_ARTIFACT_METADATA_BYTES",
    "MAX_FILE_ARTIFACT_METADATA_DEPTH",
    "MAX_FILE_ARTIFACT_METADATA_NODES",
    "MAX_FILE_ARTIFACT_METADATA_KEYS",
    "MAX_FILE_ARTIFACT_FIELD_CHARS",
    "is_file_artifact_checksum",
    "validate_file_extraction_artifact",
]
