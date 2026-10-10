import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_deployment_drain_accepts_the_installed_native_empty_queue_error():
    # Execute the shared transport regression in the locked Worker environment;
    # the shell harness's system Python may not have Kombu installed.
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "native_drain_regression", root / "scripts/tests/test_prod_app_first_party.py"
    )
    assert spec is not None and spec.loader is not None
    regression = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regression)
    regression.DrainContractTests().test_installed_virtual_passive_empty_queue_uses_native_404_form()


@pytest.mark.parametrize(
    "profile,entry",
    [
        ("platform", "miy_worker.first_party_platform"),
        ("official", "miy_official_worker.runtime"),
        ("legacy", "miy_worker.first_party_beat"),
    ],
)
def test_first_party_entries_import_without_api_collaboration_dependencies(profile, entry):
    # Use the current Worker interpreter, never an API venv. API/owner sources
    # add matching application code without installing API-only dependencies,
    # matching the worker image's --no-deps wheel boundary. A fresh process also
    # keeps native task registration and owner selection independent per entry.
    root = Path(__file__).resolve().parents[3]
    script = """
import importlib, json, pathlib, sys
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        if pathlib.Path(args[0]).name.startswith(".env"):
            raise AssertionError("environment file read")
    if event.startswith("socket.connect") or event == "socket.bind":
        raise AssertionError("network access")
    if event == "import" and args[0].split(".")[0] in {"y_py", "ypy_websocket"}:
        raise AssertionError("API-only collaboration dependency imported")
sys.addaudithook(audit)
from dataclasses import asdict
from miy_worker import settings
fixture = settings.Settings.model_construct(
    postgres_dsn="sqlite:///:memory:", broker_url="memory://",
    result_backend="cache+memory://", env_profile="test", otel_enabled=False,
)
settings.get_settings = lambda: fixture
from miy_api.core import settings as api_settings
api_fixture = api_settings.Settings.model_construct()
api_settings.get_settings = lambda: api_fixture
from miy_worker import first_party_app
from miy_api.domains.official_apps.writer import LEGACY_WRITER_IDENTITY
assert asdict(LEGACY_WRITER_IDENTITY) == {
    "scope": "official.suite", "owner": "legacy", "generation": 1, "artifact": None,
}
preflights = []
first_party_app.require_first_party_database = lambda **kw: preflights.append(kw["composition"])
first_party_app.assert_llm_routing_control_plane_ready = lambda **kw: None
profile, entry = sys.argv[1:]
app = importlib.import_module(entry).celery_app
from miy_api.core.worker_queue_contract import worker_profile_task_names, worker_profile_queues
assert {name for name in app.tasks if not name.startswith("celery.")} == set(worker_profile_task_names(profile))
queue_profiles = ("platform", "official") if profile == "legacy" else (profile,)
assert set(app.amqp.queues) == {queue for owner in queue_profiles for queue in worker_profile_queues(owner)}
assert preflights == ["platform" if profile == "platform" else "official"]
assert len(app.conf.beat_schedule) == (9 if profile == "legacy" else 0)
assert "miy_api.domains.docs.collab" not in sys.modules
assert not {"y_py", "ypy_websocket"}.intersection(sys.modules)
app.close()
print(json.dumps({"profile": profile, "tasks": len(app.tasks)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, profile, entry],
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("MIY_")},
            "PYTHONPATH": os.pathsep.join(
                str(root / path)
                for path in ("apps/worker/src", "apps/api/src", "apps/official-suite/worker/src")
            ),
        },
        cwd=root,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["profile"] == profile


def test_owned_worker_refuses_foreign_partial_excluded_queues_and_embedded_beat_before_construction(
    monkeypatch,
):
    from miy_worker.first_party_app import FirstPartyConsumerApp, FirstPartyBeatApp

    consumer = FirstPartyConsumerApp("owned", broker="memory://", set_as_current=False)
    consumer._first_party_owned_queues = frozenset(
        {"miy.official.celery", "miy.official.recording"}
    )
    for options in (
        {"queues": "miy.platform.celery"},
        {"queues": "miy.official.celery"},
        {"exclude_queues": "miy.official.recording"},
        {"beat": True},
    ):
        with pytest.raises(RuntimeError, match="first_party_"):
            consumer.Worker(**options)
    with pytest.raises(RuntimeError, match="single_owner"):
        consumer.Beat()
    beat = FirstPartyBeatApp("scheduler", broker="memory://", set_as_current=False)
    with pytest.raises(RuntimeError, match="cannot_consume"):
        beat.Worker()
