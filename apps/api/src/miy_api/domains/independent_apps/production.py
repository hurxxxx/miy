"""Core-admin same-host promotion policy; development delegates cannot approve it."""

import hashlib
import json
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.independent_delivery_settings import validate_targets
from miy_api.core.settings import WORKSPACE_ROOT, get_settings
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import CompanyAppControl, UserSystemRole
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.models import AppInstallationRecord


def runtime_target(installation: AppInstallationRecord):
    settings = get_settings()
    try:
        targets = validate_targets(
            settings.independent_app_delivery_targets,
            platform_root=WORKSPACE_ROOT,
            platform_origins=settings.independent_app_platform_origins,
        )
    except ValueError:
        service.fail("local_delivery_only", 409)
    for target in targets:
        if (
            target.environment == installation.environment
            and target.app_id == installation.app_id
            and str(target.installation_id) == installation.id
            and target.app_origin == installation.origin
        ):
            return target
    return None


def delivery_target(installation: AppInstallationRecord):
    if get_settings().environment != "production" or installation.environment != "production":
        service.fail("local_delivery_only", 409)
    target = runtime_target(installation)
    if target is not None:
        return target
    service.fail("local_delivery_only", 409)


def binding_digest(target) -> str:
    """Fence runtime settings; source/build ownership stays in the build proof."""
    fields = {
        "app_id",
        "installation_id",
        "environment",
        "app_origin",
        "loopback_port",
        "state_root",
        "ingress_image",
        "platform_origin",
        "platform_api_origin",
    }
    return hashlib.sha256(
        json.dumps(
            target.model_dump(mode="json", include=fields), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def require_authority(
    db: Session, installation: AppInstallationRecord, context: AuthContext
) -> None:
    user, _ = service._source_user(db, context.session.id)
    company = db.get(CompanyAppControl, installation.app_id, populate_existing=True)
    current_admin = db.scalar(
        select(UserSystemRole.user_id).where(
            UserSystemRole.user_id == context.user.id,
            UserSystemRole.role == "platform_admin",
        )
    )
    settings = get_settings()
    if (
        user.id != context.user.id
        or current_admin is None
        or installation.environment != "production"
        or urlsplit(installation.origin).scheme != "https"
        or not settings.independent_app_platform_origins
        or installation.origin in settings.independent_app_platform_origins
        or company is None
        or not company.enabled
    ):
        service.fail("forbidden")
    delivery_target(installation)
