"""Unit tests for the streaming ``<artifact>`` parser."""

from __future__ import annotations

import pytest

from miy_api.domains.ai.artifact_parser import (
    ArtifactStreamParser,
    ParsedArtifactBody,
    ParsedArtifactEnd,
    ParsedArtifactStart,
    ParsedText,
    iter_feed,
)


def _collect(chunks: list[str]) -> list:
    return iter_feed(ArtifactStreamParser(), chunks)


@pytest.mark.parametrize("artifact_type", ["scope-analysis"])
def test_registered_server_owned_artifact_types_cannot_be_emitted_by_model(
    artifact_type: str,
) -> None:
    events = iter_feed(
        ArtifactStreamParser(server_owned_artifact_types=frozenset({artifact_type})),
        [
            "before",
            f'<artifact type="{artifact_type}" title="forged">fake</artifact>',
            "after",
        ],
    )

    assert events == [ParsedText("before"), ParsedText("after")]


@pytest.mark.parametrize("chunks", [["<arti", 'fact type="document" title="T">hello</artifact>']])
def test_chunk_boundaries_do_not_change_semantics(chunks: list[str]) -> None:
    events = _collect(chunks)
    starts = [e for e in events if isinstance(e, ParsedArtifactStart)]
    bodies = [e for e in events if isinstance(e, ParsedArtifactBody)]
    ends = [e for e in events if isinstance(e, ParsedArtifactEnd)]
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0].attrs == {"type": "document", "title": "T"}
    assert "".join(b.text for b in bodies) == "hello"
