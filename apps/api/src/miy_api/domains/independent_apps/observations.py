"""Read-only company integration metadata; never grants, identities, or credentials."""

from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .delivery_models import AppDeploymentRequest
from .models import AppDefinitionRecord, AppInstallationRecord, AppReleaseRecord


def installation_observations(db: Session, app_id: str) -> list[dict] | None:
    if db.get(AppDefinitionRecord, app_id) is None:
        return None
    rows = db.execute(
        select(AppInstallationRecord, AppReleaseRecord)
        .outerjoin(AppReleaseRecord, AppReleaseRecord.id == AppInstallationRecord.release_id)
        .where(AppInstallationRecord.app_id == app_id)
        .order_by(AppInstallationRecord.id)
    ).all()
    latest = {}
    if rows:
        ranked = (
            select(
                AppDeploymentRequest.id,
                func.row_number()
                .over(
                    partition_by=AppDeploymentRequest.installation_id,
                    order_by=(
                        AppDeploymentRequest.created_at.desc(),
                        AppDeploymentRequest.id.desc(),
                    ),
                )
                .label("position"),
            )
            .where(AppDeploymentRequest.installation_id.in_([row[0].id for row in rows]))
            .subquery()
        )
        for request in db.scalars(
            select(AppDeploymentRequest)
            .join(ranked, ranked.c.id == AppDeploymentRequest.id)
            .where(ranked.c.position == 1)
        ):
            latest[request.installation_id] = request
    return [
        {
            "id": item.id,
            "environment": item.environment,
            "origin": item.origin,
            "enabled": item.enabled,
            "state": item.state,
            "generation": item.generation,
            "release_id": item.release_id,
            "source_revision": release.source_revision if release else None,
            "artifact_digest": release.artifact if release else None,
            "deployment": {
                "request_id": latest[item.id].id,
                "action": latest[item.id].action,
                "state": latest[item.id].state,
                "failure_code": latest[item.id].failure_code,
                "updated_at": latest[item.id].updated_at.replace(tzinfo=UTC).isoformat(),
            }
            if item.id in latest
            else None,
        }
        for item, release in rows
    ]
