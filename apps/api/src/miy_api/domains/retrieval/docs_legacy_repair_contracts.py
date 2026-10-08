"""Fixed Core maintenance contract, never a source business event."""

import hashlib
import json
from typing import Literal

LegacyDocsJobKind = Literal["scope", "rag", "search"]
MAX_TARGETS = 100
MAX_PAYLOAD_BYTES = 131072
RESOURCE_TYPE = "docs_native_doc"


class DocsLegacyRepairError(RuntimeError):
    """No provider work/business retry is permitted after this control result."""


def canonical(value: object) -> str:
    result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(result.encode()) > MAX_PAYLOAD_BYTES:
        raise DocsLegacyRepairError("docs_repair_input_budget")
    return result


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 255:
        raise DocsLegacyRepairError("docs_repair_identity_invalid")
    return value
