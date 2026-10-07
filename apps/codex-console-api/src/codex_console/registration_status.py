"""Compare observed registration metadata; never grant or execute app operations."""

import asyncio
import re

from . import app_sources, workbench_sources
from .errors import ConsoleError
from .workbench_schemas import SourceRegistrationStatusOut


async def read(settings, factory, project_id):
    before = await asyncio.to_thread(
        app_sources.registration_snapshot, settings, factory, project_id
    )
    origin = settings.miy_api_origin
    platform = await workbench_sources.runtime_catalog(settings, factory, fresh=True)
    try:
        after = await asyncio.to_thread(
            app_sources.registration_snapshot, settings, factory, project_id
        )
    except ConsoleError:
        # It was valid before the remote read. A removal/rebind/edit during that
        # read must not return a comparison for a different or now-invalid source.
        raise ConsoleError("app_source_changed", 409) from None
    if before != after or origin != settings.miy_api_origin:
        raise ConsoleError("app_source_changed", 409)
    draft = after[0]
    result = SourceRegistrationStatusOut(
        project_id=project_id,
        app_id=draft.app_id,
        binding_version=draft.binding_version,
        state="unknown",
        source_revision=draft.source_revision,
        definition_digest=draft.definition_digest,
        platform_state=platform.state,
        platform_checked_at=platform.checked_at,
        registered_source_revision=None,
        registered_definition_digest=None,
        definition_matches=None,
        revision_matches=None,
    )
    if (
        platform.state != "ready"
        or platform.registration_status_version != 1
        or platform.stale
        or platform.checked_at is None
        or not re.fullmatch(r"[0-9a-f]{64}", platform.catalog_revision or "")
    ):
        return result
    registered = next((item for item in platform.items if item.app_id == draft.app_id), None)
    if registered is None:
        result.state = "unregistered"
        return result
    result.registered_source_revision = registered.registered_source_revision
    digest = registered.definition_digest
    if digest and re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        result.registered_definition_digest = digest
    if not registered.source_repository or registered.source_directory is None:
        return result
    try:
        source = draft.definition["source"]
        same_repository = app_sources.repository_identity(registered.source_repository) == (
            app_sources.repository_identity(source["repository"])
        )
    except ValueError:
        return result
    if not same_repository or registered.source_directory != source["directory"]:
        result.state = "collision"
        return result
    if not result.registered_source_revision or not result.registered_definition_digest:
        return result
    result.definition_matches = result.registered_definition_digest == draft.definition_digest
    result.revision_matches = result.registered_source_revision == draft.source_revision
    result.state = (
        "matching" if result.definition_matches and result.revision_matches else "different"
    )
    return result
