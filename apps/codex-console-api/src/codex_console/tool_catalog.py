"""Discoverable metadata from the same schemas passed to native Codex threads."""

from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel

from . import delivery_tools, registration_tools, source_tools, task_git, task_timeline


class ToolOut(BaseModel):
    name: str
    description: str
    scope: Literal["host", "app_development", "app_delivery", "app_registration"]
    input_schema: dict[str, Any]


def catalog():
    entries = [
        ("host", task_git.specs()),
        ("host", task_timeline.specs()),
        (
            "app_development",
            source_tools.specs(
                SimpleNamespace(
                    context={
                        "purpose": "development",
                        "source_binding": True,
                    }
                )
            ),
        ),
        ("app_delivery", delivery_tools.specs(SimpleNamespace(context={"installation_id": True}))),
        (
            "app_registration",
            registration_tools.specs(SimpleNamespace(context={"purpose": "registration"})),
        ),
    ]
    return [
        dict(
            name=s["name"], description=s["description"], scope=scope, input_schema=s["inputSchema"]
        )
        for scope, specs in entries
        for s in specs
    ]


def install(app, secured):
    @app.get("/api/tool-catalog", dependencies=secured, response_model=list[ToolOut])
    def tools():
        return catalog()
