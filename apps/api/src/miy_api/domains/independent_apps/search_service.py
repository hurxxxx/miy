"""App-session search over current owned PostgreSQL records, never raw engine hits."""

from sqlalchemy import select

from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.data_store import DataStoreError
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
from miy_api.domains.independent_apps.verification import trusted_release


def search_context(db, actor, collection, mode):
    if not {"data:read", "search:read"}.issubset(actor.permissions):
        service.fail("forbidden")
    installation = db.get(AppInstallationRecord, actor.installation_id)
    release = (
        trusted_release(db, installation, installation.release_id)
        if installation and installation.release_id
        else None
    )
    if release is None:
        service.fail("forbidden")
    definition = AppDefinition.model_validate(release.definition_snapshot)
    declaration = definition.search.collections.get(collection) if definition.search else None
    if declaration is None or mode not in declaration.modes:
        service.fail("forbidden")
    binding = db.scalar(
        select(AppSearchBindingRecord)
        .where(
            AppSearchBindingRecord.installation_id == actor.installation_id,
            AppSearchBindingRecord.search_spec_sha256 == definition.search.content_hash(),
            AppSearchBindingRecord.state == "ready",
        )
        .order_by(AppSearchBindingRecord.generation.desc())
        .limit(1)
    )
    if not binding:
        service.fail("data_unavailable", 503)
    return installation, binding


def pending(source, actor, collection, binding):
    with source.data._transaction(actor) as conn:
        source.data._search_identity(conn)
        actual = conn.execute(
            "SELECT workspace_id::text,search_spec_sha256,active FROM miy_data.search_generations WHERE generation=%s",
            (binding.generation,),
        ).fetchone()
        if actual != (binding.workspace_id, binding.search_spec_sha256, True):
            raise DataStoreError("data_schema_identity_mismatch")
        return conn.execute(
            "SELECT EXISTS(SELECT 1 FROM miy_data.search_outbox WHERE generation=%s AND owner_id=%s AND collection=%s AND NOT completed)",
            (binding.generation, actor.user_id, collection),
        ).fetchone()[0]
