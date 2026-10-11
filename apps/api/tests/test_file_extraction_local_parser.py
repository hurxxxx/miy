"""Pure local compute and legacy OCR default compatibility; no Source I/O."""

from hashlib import sha256
from uuid import uuid4

import pytest

from miy_api.domains.files.extraction_contracts import (
    FileExtractionBoundInput,
    FileExtractionNeedsOcr,
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


def test_actual_image_needs_ocr_without_provider_inspection():
    item = bound(b"\x89PNG\r\n\x1a\n" + b"synthetic bounded image", "local.png", "image/png")
    result = compute_local_file_extraction(item)
    assert result.outcome == "ocr_required" and result.artifact is None


def test_empty_local_source_is_unsupported():
    result = compute_local_file_extraction(bound(b"", "local.txt", "text/plain"))
    assert result.outcome == "unsupported" and result.artifact is None


def test_ocr_seam_preserves_legacy_default():
    from miy_api.domains.files.rag_projection import extract_file_artifact

    item = bound(b"\x89PNG\r\n\x1a\n" + b"synthetic image", "local.png", "image/png")
    calls = []

    class Runtime:
        @property
        def ocr_provider_name(self):
            calls.append("provider")
            return "synthetic"

        def extract_text(self, **kwargs):
            calls.append("ocr")
            return "Synthetic legacy OCR text."

    with pytest.raises(FileExtractionNeedsOcr):
        extract_file_artifact(
            file=item.parser_input, content=item.content, rag_service=Runtime(), allow_ocr=False
        )
    assert calls == []
    assert extract_file_artifact(
        file=item.parser_input, content=item.content, rag_service=Runtime()
    ).text
    assert calls == ["provider", "ocr"]
