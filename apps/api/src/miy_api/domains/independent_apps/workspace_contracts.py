from uuid import UUID

from pydantic import Field

from miy_api.domains.independent_apps.contracts import (
    AppDefinition,
    Contract,
    Digest,
    InstallationOut,
    Revision,
)


class WorkspacePrepare(Contract):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    definition: AppDefinition
    source_revision: Revision


class WorkspaceSync(Contract):
    definition: AppDefinition
    source_revision: Revision
    expected_version: int = Field(ge=1)


class WorkspaceOut(Contract):
    id: UUID
    app_id: str
    version: int
    state: str
    profile_id: str
    definition: AppDefinition | None
    definition_digest: Digest | None
    source_revision: Revision | None
    installation: InstallationOut
    portal_url: str
    permanent_portal_url: str
    integration_revision: Revision | None
    integration_deployment_id: UUID | None
    source_handoff_complete: bool


class WorkspaceTransition(Contract):
    expected_version: int = Field(ge=1)


class WorkspaceIntegrate(WorkspaceSync):
    expected_digest: Digest
    expected_source_revision: Revision


class WorkspaceComplete(Contract):
    deployment_id: UUID
