"""Pure local compute and legacy OCR default compatibility; no Source I/O."""

from hashlib import sha256
from uuid import uuid4

import pytest

from miy_api.domains.files.extraction_contracts import (
    FileExtractionBoundInput,
    FileExtractionParserInput,
    FileExtractionReceipt,
)
from miy_api.domains.files.extraction_runner import compute_local_file_extraction


def bound(content, filename, content_type):
    identifier = str(uuid4())
    return FileExtractionBoundInput(
        FileExtractionReceipt(
            request_id=uuid4(),
            result_id=uuid4(),
            event_id=uuid4(),
            request_digest="a" * 64,
            state="input_bound",
            input_sha256=sha256(content).hexdigest(),
            input_byte_count=len(content),
            provisional=False,
        ),
        FileExtractionParserInput(identifier, filename, content_type),
        content,
    )


@pytest.mark.parametrize(
    "content,filename,content_type",
    [
        (b"Synthetic local text.", "local.txt", "text/plain"),
        (
            b"<html><body><p>"
            + b"Synthetic meaningful visible text. " * 10
            + b"</p></body></html>",
            "local.html",
            "text/html",
        ),
    ],
)
def test_actual_local_parsers_produce_valid_source_artifacts(content, filename, content_type):
    item = bound(content, filename, content_type)
    result = compute_local_file_extraction(item)
    assert result.outcome == "ready" and result.input_sha256 == sha256(content).hexdigest()
    assert result.artifact.content_checksum == result.input_sha256
    assert result.artifact.text and result.artifact.blocks
    assert result.artifact.metadata["ocr_attempted"] is False
