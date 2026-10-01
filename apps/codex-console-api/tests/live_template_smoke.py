"""Opt-in native template isolation/restart test, using only disposable fixtures.

Requires subscription login and MTY_CODEX_CONSOLE_TEMPLATE_BINARY pointing to a
verified compatible CLI installation; no live console service is touched.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from codex_console.auth import password_hash
from codex_console.cli import migrate
from codex_console.config import Settings
from codex_console.models import Owner, database
from codex_console.rpc import CodexRPC

ROOT = Path(__file__).resolve().parents[3]
PIN = Path(os.environ["MTY_CODEX_CONSOLE_TEMPLATE_BINARY"]).resolve(strict=True)


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def health(number):
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{number}/healthz", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Fixture service failed to start")


def main():
    with tempfile.TemporaryDirectory(prefix="codex-console-independent-") as temp:
        base = Path(temp).resolve()
        repo = base / "dev"
        repo.mkdir()
        for args in [
            ("init", "-b", "dev"),
            ("config", "user.name", "Console verification"),
            ("config", "user.email", "console@test.invalid"),
        ]:
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        (repo / "README.md").write_text(
            "A disposable console verification repository. No application files or secrets.\n"
        )
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "fixture"], check=True, capture_output=True
        )
        bad = base / "incompatible-codex"
        bad.write_text('#!/bin/sh\nprintf "codex-cli 0.0.0\\n"\n')
        bad.chmod(0o700)
        session, management, templates = [port() for _ in range(3)]
        origin = f"http://127.0.0.1:{management}"
        cfg = Settings(
            database_url="sqlite+pysqlite:///" + str(base / "console.sqlite3"),
            origin=origin,
            workspace=repo,
            worktree_root=base / "worktrees",
            binary=str(bad),
            template_binary=PIN,
            port=session,
            management_port=management,
            template_port=templates,
            attachment_cache=base / "attachments",
            web_dist=ROOT / "apps/codex-console-web/dist",
            _env_file=None,
        )
        migrate(cfg.database_url)
        engine, factory = database(cfg.database_url)
        password = uuid.uuid4().hex
        with factory.begin() as db:
            db.add(Owner(password_hash=password_hash(password)))
        engine.dispose()
        env = {k: v for k, v in os.environ.items() if not k.startswith("MTY_CODEX_CONSOLE_")}
        for key, field in Settings.model_fields.items():
            value = getattr(cfg, key)
            if value is not None:
                env[field.validation_alias] = (
                    json.dumps(value, default=str)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
        processes = {}
        log = (base / "runtime.log").open("w")

        def start(role, number):
            processes[role] = subprocess.Popen(
                [sys.executable, "-m", "codex_console.cli", role],
                cwd=base,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            health(number)

        def stop(role):
            process = processes.pop(role)
            process.terminate()
            process.wait(timeout=20)

        task = None
        try:
            start("serve", session)
            start("templates", templates)
            start("manage", management)
            with httpx.Client(base_url=origin, timeout=125, headers={"origin": origin}) as client:
                assert client.post("/api/session", json={"password": password}).status_code == 200
                client.headers["x-csrf-token"] = client.cookies["codex_console_csrf"]
                account = client.get("/api/codex/account").json()
                assert account["error_code"] == "codex_version_mismatch", account.get("error_code")
                row = client.post(
                    "/api/templates",
                    json={
                        "name": "Independent compatibility verification",
                        "stage": "plan",
                        "prompt": (
                            "Read README.md. Explain in four concise paragraphs how this "
                            "disposable repository can verify that a console UI restart is "
                            "independent of an ongoing agent task. Do not edit files or "
                            "call external services."
                        ),
                        "references": ["README.md"],
                    },
                ).json()
                launched = client.post(
                    f"/api/templates/{row['id']}/run",
                    json={"launch_id": str(uuid.uuid4()), "version": row["version"], "values": {}},
                )
                assert launched.status_code == 200, (
                    launched.status_code,
                    launched.json().get("code"),
                )
                task = launched.json()
                assert task["status"] in ("running", "waiting"), task.get("error_code")
                thread = task["thread_id"]
                runner_pid = processes["templates"].pid
                print(
                    "Native pinned template started while normal CLI was incompatible", flush=True
                )
                stop("serve")
                stop("manage")
                start("serve", session)
                start("manage", management)
                assert processes["templates"].pid == runner_pid
                assert client.get("/api/session").json()["authenticated"]
                current = client.get(f"/api/tasks/{task['id']}").json()
                assert current["thread_id"] == thread and current["status"] != "uncertain", (
                    current.get("error_code")
                )
                print(
                    "Management and session restarted; template process, "
                    "session cookie and task identity retained",
                    flush=True,
                )
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    current = client.get(f"/api/tasks/{task['id']}").json()
                    if current["status"] not in ("starting", "running", "waiting"):
                        break
                    time.sleep(0.5)
                assert current["status"] == "idle", current.get("error_code")
                assert any(i.get("type") == "agentMessage" for i in current["items"])
                assert (
                    subprocess.run(
                        ["git", "-C", str(repo), "status", "--porcelain"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout
                    == ""
                )
                print(
                    "Native task completed after restart; result persisted "
                    "and fixture repository unchanged",
                    flush=True,
                )
        finally:
            for role in list(processes):
                stop(role)
            log.close()
            if task and task.get("thread_id"):

                async def archive():
                    async def ignore(*args, **kwargs):
                        pass

                    rpc = CodexRPC(str(PIN), repo, ignore, ignore)
                    try:
                        await rpc.start()
                        await rpc.call("thread/archive", {"threadId": task["thread_id"]})
                    finally:
                        await rpc.close()

                asyncio.run(archive())


if __name__ == "__main__":
    main()
