"""Company-level app management projections. No business records or account identities."""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from miy_api.core.app_contracts_generated import APP_CONTRACTS
from miy_api.domains.ai.registry import get_ai_capability_registry
from miy_api.domains.auth.models import AuditLog, CompanyAppControl
from miy_api.domains.independent_apps.service import management_projection
from miy_api.domains.usage.models import UsageEvent
from miy_api.domains.usage.service import USAGE_EVENT_APP_OPEN
from miy_api.version import RUNTIME_REVISION


def app_catalog(db: Session) -> list[dict]:
    enabled = dict(db.execute(select(CompanyAppControl.app_id, CompanyAppControl.enabled)).all())
    ai_apps = {
        app_id
        for workload in get_ai_capability_registry().llm_workloads.values()
        for app_id in workload.app_ids
    }
    return [
        {
            "app_id": app["app_id"],
            "title": app["title"],
            "title_translations": app.get("title_translations", {}),
            "icon_key": app.get("icon_key", "layout-grid"),
            "enabled": enabled.get(app["app_id"], False),
            "release_unit": app.get("management", {}).get("release_unit"),
            "installed_revision": (
                RUNTIME_REVISION
                if app.get("management", {}).get("release_unit") == "miy-app"
                and RUNTIME_REVISION != "unmanaged"
                else None
            ),
            "runtime_ai": app["app_id"] in ai_apps,
        }
        for app in APP_CONTRACTS
    ] + management_projection(db)


def app_usage(db: Session, app_id: str, month: date | None) -> dict:
    start = (month or datetime.now(UTC).date()).replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    since = datetime.combine(start, datetime.min.time())
    until = datetime.combine(end, datetime.min.time())
    opens = (
        db.scalar(
            select(func.sum(UsageEvent.count)).where(
                UsageEvent.app_id == app_id,
                UsageEvent.event_type == USAGE_EVENT_APP_OPEN,
                UsageEvent.occurred_at >= since,
                UsageEvent.occurred_at < until,
            )
        )
        or 0
    )
    # Select only aggregate inputs. Never load/export prompts, content or actor identities.
    rows = db.execute(
        select(
            AuditLog.payload["status"].as_string(),
            AuditLog.payload["usage"]["total_tokens"].as_integer(),
        )
        .where(
            AuditLog.action == "llm_call",
            AuditLog.payload["app_id"].as_string() == app_id,
            AuditLog.created_at >= since,
            AuditLog.created_at < until,
        )
        .limit(100001)
    ).all()
    complete = len(rows) <= 100000
    rows = rows[:100000]
    reported = [tokens for _, tokens in rows if type(tokens) is int and tokens >= 0]
    return {
        "app_id": app_id,
        "month": start.strftime("%Y-%m"),
        "app_opens": opens,
        "llm_calls": len(rows),
        "llm_errors": sum(status not in ("ok", "cancelled") for status, _ in rows),
        "total_tokens": sum(reported) if reported or not rows else None,
        "unreported_calls": len(rows) - len(reported),
        "complete": complete,
        "amount_minor": None,
        "currency": None,
        "cost_basis": "not_reported",
    }
