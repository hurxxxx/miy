"""Two bounded, stateless signing purposes; neither is an authentication bearer."""

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError

from miy_api.core.settings import get_settings
from miy_api.core.i18n import localized_http_exception
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.file_contracts import FileSelectionContext, FileVersion

REQUEST_TTL = 60
READ_TTL = 120


class FileRequestClaims(FileSelectionContext):
    purpose: Literal["file-selection-request"] = "file-selection-request"
    session_key: FileVersion
    generation: int = Field(ge=1, strict=True)
    issued_at: int = Field(ge=0, strict=True)
    expires: int = Field(ge=0, strict=True)


class FileReadClaims(FileSelectionContext):
    purpose: Literal["selected-file-read"] = "selected-file-read"
    session_key: FileVersion
    generation: int = Field(ge=1, strict=True)
    issued_at: int = Field(ge=0, strict=True)
    expires: int = Field(ge=0, strict=True)
    file_id: UUID
    version: FileVersion
    grant_id: UUID
    max_bytes: Literal[10485760] = 10485760


def _key() -> bytes:
    key = get_settings().independent_app_file_selection_signing_key.get_secret_value()
    if not key:
        service.fail("file_picker_unavailable", 503)
    return key.encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def sign(claims: FileRequestClaims | FileReadClaims) -> str:
    prefix = "miyfsr1" if isinstance(claims, FileRequestClaims) else "miyfsb1"
    payload = _encode(
        json.dumps(
            claims.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    signature = hmac.new(_key(), (prefix + "\0" + payload).encode(), hashlib.sha256).digest()
    result = f"{prefix}.{payload}.{_encode(signature)}"
    if len(result) > 4096:
        service.fail("file_request_invalid", 422)
    return result


def verify(token: str, *, read: bool = False) -> FileRequestClaims | FileReadClaims:
    key = _key()
    try:
        if not 1 <= len(token) <= 4096 or not token.isascii():
            raise ValueError("format")
        prefix, encoded, signature = token.split(".")
        if prefix != ("miyfsb1" if read else "miyfsr1"):
            raise ValueError("purpose")
        expected = hmac.new(key, (prefix + "\0" + encoded).encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise ValueError("signature")
        payload = json.loads(_decode(encoded))
        cls = FileReadClaims if read else FileRequestClaims
        claims = cls.model_validate(payload)
        now = time.time()
        if not (
            claims.issued_at <= now < claims.expires
            and 0 < claims.expires - claims.issued_at <= (READ_TTL if read else REQUEST_TTL)
        ):
            raise ValueError("expiry")
        return claims
    except (ValueError, TypeError, ValidationError, binascii.Error, RecursionError):
        raise localized_http_exception(
            status_code=403, code="independent_apps.file_access_invalid"
        ) from None
