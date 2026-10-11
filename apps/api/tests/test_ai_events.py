"""Envelope contract tests for the current streaming wire format."""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from miy_api.domains.ai.events import (
    AgentEventEnvelope,
)

_ADAPTER: TypeAdapter = TypeAdapter(AgentEventEnvelope)
_SCHEMA_FIXTURE = Path(__file__).parent / "fixtures" / "envelope_schema.json"
