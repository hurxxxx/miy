"""Execution metadata must not damage persisted Task history inspection."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from codex_console import remote_environments, store, toolchain_profiles
from codex_console.cli import migrate
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.models import Item, Task, database
from codex_console.schemas import TaskDetail


@pytest.fixture
def fresh_console(tmp_path):
    # Use the same fresh SQLite migration/database entrypoints as database_url;
    # no auth, native client, app lifespan, or existing database is involved.
    url = "sqlite+pysqlite:///" + str(tmp_path.resolve() / "console.sqlite3")
    migrate(url)
    engine, factory = database(url)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("core", ["ask", "yolo"]),
        ("native_v1", ["ask", "yolo"]),
        ("sdk", ["ask"]),
        ("removed", []),
        ("retargeted", []),
        ("profile_changed", []),
        ("missing_repository_root", []),
        ("nonmapping_binding", []),
        ("template_definition_null", []),
        ("template_definition_list", []),
        ("template_definition_boolean", []),
    ],
)
def test_actual_task_detail_preserves_stored_history_and_source_for_all_permission_bindings(
    fresh_console, tmp_path, case, expected
):
    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "app.py"
    source_bytes = b"# synthetic immutable application source\n"
    source_file.write_bytes(source_bytes)
    selected = AppExecutionEnvironment(
        key="synthetic-app-v1",
        source_root=source,
        exec_server_url="ws://127.0.0.1:19391",
        auth_bearer_token="synthetic-executor-token-" + "x" * 32,
        toolchain_profile=(
            toolchain_profiles.SDK_PROFILE if case == "sdk" else toolchain_profiles.NATIVE_PROFILE
        ),
    )
    settings = SimpleNamespace(
        app_execution_environments=[selected],
        attachment_max_bytes=1024,
        attachment_task_max_bytes=4096,
    )
    context = {
        "source_binding": {
            "repository_root": str(source),
            **remote_environments.binding_snapshot(settings, source),
        }
    }
    if case == "core":
        context = None
        settings.app_execution_environments = []
    elif case == "removed":
        settings.app_execution_environments = []
    elif case == "retargeted":
        settings.app_execution_environments = [
            selected.model_copy(update={"exec_server_url": "ws://127.0.0.1:19392"})
        ]
    elif case == "profile_changed":
        settings.app_execution_environments = [
            selected.model_copy(update={"toolchain_profile": toolchain_profiles.SDK_PROFILE})
        ]
    elif case == "missing_repository_root":
        context["source_binding"].pop("repository_root")
    elif case == "nonmapping_binding":
        context = {"source_binding": ["synthetic-stored-binding"]}
    template_snapshot = (
        {
            "definition": {
                "template_definition_null": None,
                "template_definition_list": [],
                "template_definition_boolean": True,
            }[case]
        }
        if case.startswith("template_definition_")
        else None
    )
    payloads = [
        {"id": "original-item", "type": "agentMessage", "text": "Synthetic prior result"},
        {
            "id": "original-command",
            "type": "commandExecution",
            "command": "synthetic-prior-command",
            "status": "completed",
            "exitCode": 0,
        },
    ]
    with fresh_console.begin() as db:
        db.add(
            Task(
                id="original-task",
                title="Synthetic stored task",
                root=str(source),
                context=context,
                template_snapshot=template_snapshot,
                thread_id="original-thread",
                stage="implement",
                status="idle",
                permissions="ask",
            )
        )
        db.flush()
        db.add_all(
            Item(
                task_id="original-task",
                item_id=payload["id"],
                turn_id="original-turn",
                payload=payload,
            )
            for payload in payloads
        )

    def stored_rows():
        with fresh_console() as db:
            return {
                "task": [dict(row) for row in db.execute(select(Task.__table__)).mappings()],
                "items": [
                    dict(row)
                    for row in db.execute(select(Item.__table__).order_by(Item.id)).mappings()
                ],
            }

    before = stored_rows()
    detail = store.detail(fresh_console, "original-task", settings)
    typed = TaskDetail.model_validate(detail)
    assert typed.implementation_permissions == expected
    assert detail["thread_id"] == "original-thread" and detail["context"] == context
    assert detail["template_snapshot"] == template_snapshot
    assert detail["items"] == [{**payload, "turn_id": "original-turn"} for payload in payloads]
    assert stored_rows() == before
    assert source_file.read_bytes() == source_bytes
    if case in {"removed", "retargeted", "profile_changed"}:
        with fresh_console() as db, pytest.raises(ConsoleError):
            remote_environments.for_task(settings, db.get(Task, "original-task"))


def test_metadata_refuses_nonmapping_context_without_changing_execution_gate():
    settings = SimpleNamespace(app_execution_environments=[])
    task = SimpleNamespace(context=["synthetic-stored-context"])
    assert remote_environments.implementation_permissions(settings, task) == []
    with pytest.raises(AttributeError):
        remote_environments.for_task(settings, task)
