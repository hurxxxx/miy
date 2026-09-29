"""Immutable, provenance-carrying AI report and analysis artifacts."""

from mty_api.domains.ai_artifacts.contracts import (
    AiArtifactCreate,
    AiArtifactIndexGenerationCreate,
    AiArtifactQueryCreate,
    AiArtifactSourceCreate,
)
from mty_api.domains.ai_artifacts.repository import AiArtifactRepository

__all__ = [
    "AiArtifactCreate",
    "AiArtifactIndexGenerationCreate",
    "AiArtifactQueryCreate",
    "AiArtifactRepository",
    "AiArtifactSourceCreate",
]
