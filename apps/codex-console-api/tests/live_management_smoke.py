"""Opt-in real subscription validation of concurrent roots and native subagents.

Uses only disposable test DB/repository fixtures; never part of pytest/CI.
"""

import contextlib
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from conftest import PASSWORD, database_url, repository
from fastapi.testclient import TestClient

from codex_console.app import create_app
from codex_console.auth import CSRF_COOKIE, password_hash
from codex_console.config import Settings
from codex_console.models import Owner, database


def main():
    fixture = database_url.__wrapped__()
    target = next(fixture)
    try:
        with tempfile.TemporaryDirectory(prefix="codex-console-management-smoke-") as directory:
            root = repository.__wrapped__(Path(directory))
            settings = Settings(
                database_url=target,
                origin="http://localhost",
                workspace=root,
                web_dist=root / "absent",
                _env_file=None,
            )
            engine, factory = database(target)
            with factory.begin() as db:
                db.add(Owner(password_hash=password_hash(PASSWORD)))
            engine.dispose()
            with TestClient(create_app(settings), base_url=settings.origin) as client:
                client.headers["origin"] = settings.origin
                assert client.post("/api/session", json={"password": PASSWORD}).status_code == 200
                client.headers["x-csrf-token"] = client.cookies[CSRF_COOKIE]
                tasks = [
                    client.post("/api/tasks", json={"title": "Disposable management smoke"}).json()
                    for _ in range(2)
                ]
                try:
                    for task, prompt in zip(
                        tasks,
                        [
                            "Use spawn_agent to create two read-only subagents in parallel. "
                            "One should inspect hello.txt, the other should inspect git status. "
                            "Wait for both to finish and report a short combined result. "
                            "Actually delegate. Do not edit files or plan.",
                            "Read hello.txt; report one sentence. Do not edit files or plan.",
                        ],
                        strict=True,
                    ):
                        response = client.post(
                            f"/api/tasks/{task['id']}/messages",
                            json={
                                "text": prompt,
                                "stage": "plan",
                                "operation_id": str(uuid4()),
                            },
                        )
                        if response.status_code != 200:
                            raise RuntimeError(response.json().get("code", "submission_failed"))
                    print("live: concurrent root requests accepted", flush=True)
                    deadline = time.monotonic() + 240
                    while time.monotonic() < deadline:
                        states = [client.get(f"/api/tasks/{t['id']}").json() for t in tasks]
                        if any(t["requests"] for t in states):
                            raise RuntimeError("interactive_response_required")
                        if any(t["status"] in ("failed", "uncertain") for t in states):
                            raise RuntimeError("native_execution_failed")
                        children = [a for a in states[0]["agents"] if a["parent_thread_id"]]
                        if (
                            all(t["status"] == "idle" for t in states)
                            and len(children) >= 2
                            and all(a["status"] in ("completed", "shutdown") for a in children)
                        ):
                            assert not subprocess.check_output(
                                ["git", "-C", str(root), "status", "--porcelain"]
                            )
                            print(
                                f"live: {len(children)} subagents; roots completed; no changes",
                                flush=True,
                            )
                            return
                        time.sleep(1)
                    raise RuntimeError("native_subagent_smoke_timeout")
                finally:
                    runtime = client.app.state.runtime
                    for task in tasks:
                        current = client.get(f"/api/tasks/{task['id']}").json()
                        client.post(f"/api/tasks/{task['id']}/interrupt", json={})
                        ids = [a["thread_id"] for a in current["agents"]]
                        if current["thread_id"] and current["thread_id"] not in ids:
                            ids.append(current["thread_id"])
                        for thread_id in reversed(ids):
                            if runtime.rpc and runtime.rpc.connected:
                                with contextlib.suppress(Exception):
                                    client.portal.call(
                                        runtime.rpc.call, "thread/archive", {"threadId": thread_id}
                                    )
    finally:
        with contextlib.suppress(StopIteration):
            next(fixture)


if __name__ == "__main__":
    main()
