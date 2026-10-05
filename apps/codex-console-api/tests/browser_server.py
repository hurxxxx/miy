"""Browser-test entrypoint. No fake runtime or password is installed in the application."""

import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn
from conftest import PASSWORD, FakeRPC

from codex_console import instructions
from codex_console.app import create_app
from codex_console.auth import password_hash
from codex_console.cli import migrate
from codex_console.config import Settings
from codex_console.models import Owner, database


class BrowserRPC(FakeRPC):
    completion_gate = None

    def __init__(self, *args):
        super().__init__(*args)
        self.jobs = set()

    async def call(self, method, params):
        result = await super().call(method, params)
        if method == "skills/list":
            result = {
                "data": [
                    {
                        "cwd": cwd,
                        "skills": [
                            {
                                "name": re.search(r"(?m)^name: (.+)$", path.read_text())[1],
                                "description": "Browser fixture skill",
                                "path": str(path),
                                "enabled": True,
                            }
                            for path in (Path(cwd) / ".agents/skills").glob("*/SKILL.md")
                        ],
                        "errors": [],
                    }
                    for cwd in params["cwds"]
                ]
            }
        if method == "turn/start":
            job = asyncio.create_task(
                self.finish(params, result["turn"]["id"], type(self).completion_gate)
            )
            self.jobs.add(job)
            job.add_done_callback(self.jobs.discard)
        return result

    async def finish(self, params, turn_id, completion_gate=None):
        await asyncio.sleep(0.15)
        envelope = {"threadId": params["threadId"], "turnId": turn_id}
        user = {
            "id": str(uuid4()),
            "clientId": params["clientUserMessageId"],
            "type": "userMessage",
            "content": params["input"],
        }
        await self.on_message({"method": "item/completed", "params": {**envelope, "item": user}})
        await self.on_message(
            {
                "method": "turn/plan/updated",
                "params": {
                    **envelope,
                    "explanation": None,
                    "plan": [
                        {"step": "Inspect files", "status": "completed"},
                        {"step": "Check result", "status": "inProgress"},
                    ],
                },
            }
        )
        if completion_gate is not None:
            await completion_gate.wait()
        if params["collaborationMode"]["mode"] == "plan":
            wants_plan = "make a plan" in params["input"][0].get("text", "")
            item = (
                {
                    "id": str(uuid4()),
                    "type": "plan",
                    "text": "# Greeting\nAdd a greeting and run a focused check.",
                }
                if wants_plan
                else {
                    "id": str(uuid4()),
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": "This is a general answer; saved plan is unchanged.",
                }
            )
        else:
            (Path(params["cwd"]) / "greeting.txt").write_text("Hello from the Codex console.\n")
            command = {
                "id": str(uuid4()),
                "type": "commandExecution",
                "command": "python -m unittest",
                "status": "completed",
                "exitCode": 0,
                "aggregatedOutput": "1 test passed",
            }
            await self.on_message(
                {"method": "item/completed", "params": {**envelope, "item": command}}
            )
            item = {
                "id": str(uuid4()),
                "type": "agentMessage",
                "phase": "final_answer",
                "text": "Implemented the greeting. Focused check passed. Review greeting.txt.",
            }
        await self.on_message({"method": "item/completed", "params": {**envelope, "item": item}})
        await self.on_message(
            {
                "method": "turn/completed",
                "params": {**envelope, "turn": {"id": turn_id, "status": "completed"}},
            }
        )

    async def close(self):
        for job in list(self.jobs):
            job.cancel()
        await asyncio.gather(*self.jobs, return_exceptions=True)
        await super().close()


def main():
    port = int(os.environ.get("MIY_CODEX_CONSOLE_PORT", "19365"))
    with tempfile.TemporaryDirectory(prefix="codex-console-browser-") as directory:
        target = "sqlite+pysqlite:///" + str(Path(directory).resolve() / "console.sqlite3")
        migrate(target)
        engine, factory = database(target)
        with factory.begin() as db:
            db.add(Owner(password_hash=password_hash(PASSWORD)))
        engine.dispose()
        # macOS temporary paths can contain the /var -> /private/var symlink.
        # Use the canonical fixture directory for the protected attachment cache.
        directory = Path(directory).resolve()
        root = directory / "dev"
        root.mkdir()
        for args in (
            ("init", "-b", "dev"),
            ("config", "user.name", "Console Test"),
            ("config", "user.email", "console@test.invalid"),
        ):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        (root / "README.md").write_text("Browser regression fixture\n")
        contract = root / "packages/contracts/app-contracts.json"
        contract.parent.mkdir(parents=True)
        contract.write_bytes(
            (
                Path(__file__).resolve().parents[3] / "packages/contracts/app-contracts.json"
            ).read_bytes()
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "update-ref", "refs/remotes/origin/dev", "HEAD"],
            check=True,
            capture_output=True,
        )
        settings = Settings(
            database_url=target,
            origin=f"http://127.0.0.1:{port}",
            base_path=os.environ.get("MIY_CODEX_CONSOLE_BASE_PATH", ""),
            workspace=root,
            attachment_cache=directory / "attachments",
            web_dist=Path(__file__).resolve().parents[2] / "codex-console-web/dist",
            _env_file=None,
        )
        instructions.roots = lambda cfg: {
            "project": cfg.workspace,
            "personal": directory / "personal",
            "global": directory / "codex-home",
        }
        app = create_app(settings, rpc_factory=BrowserRPC)
        # Only this disposable browser fixture has completion controls. Product
        # code and the real app-server transport never install these endpoints.
        gate_id = None

        @app.post(f"{settings.base_path}/__test__/hold-completion")
        async def hold_completion():
            nonlocal gate_id
            assert BrowserRPC.completion_gate is None
            gate_id = str(uuid4())
            BrowserRPC.completion_gate = asyncio.Event()
            return {"id": gate_id}

        @app.post(f"{settings.base_path}/__test__/release-completion")
        async def release_completion(body: dict):
            nonlocal gate_id
            assert body.get("id") == gate_id and BrowserRPC.completion_gate is not None
            BrowserRPC.completion_gate.set()
            BrowserRPC.completion_gate = None
            gate_id = None
            return {"ok": True}

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
