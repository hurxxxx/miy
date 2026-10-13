"""Fixed Linux/Docker dependency preparation for owner-operated core worktrees.

No source-provided shell commands, production env copies or service startup.
The operator config selects private Linux storage and optional development DB
provisioning. Dependency installers use committed lockfiles, with pnpm scripts off.
"""

import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from . import git


def run(args, *, cwd, env):
    subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=1200,
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_write(path, text):
    if path.is_symlink():
        raise ValueError("Unsafe preparation path")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        info = os.fstat(output.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError("Unsafe private preparation file")
        os.ftruncate(output.fileno(), 0)
        os.fchmod(output.fileno(), 0o600)
        output.write(text)


def development_database(config, state, task_id):
    """Optional fixed administrator profile; never reuse the shared dev database."""
    if not config:
        return None
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url

    credential = state / "database.json"
    if credential.exists():
        item = json.loads(credential.read_text())
    else:
        name = "miy_wb_" + UUID(task_id).hex
        item = {"name": name, "password": secrets.token_urlsafe(32)}
        private_write(credential, json.dumps(item))
    admin = make_url(config["url"]).set(
        password=Path(config["password_file"]).read_text().strip(), drivername="postgresql"
    )
    with psycopg.connect(
        admin.render_as_string(hide_password=False), autocommit=True
    ) as connection:
        if not connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (item["name"],)
        ).fetchone():
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
                ).format(sql.Identifier(item["name"]), sql.Literal(item["password"]))
            )
        db = connection.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (item["name"],)
        ).fetchone()
        if db and db[0] != item["name"]:
            raise ValueError("Unexpected database owner")
        if not db:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(item["name"]), sql.Identifier(item["name"])
                )
            )
    with psycopg.connect(
        admin.set(database=item["name"]).render_as_string(hide_password=False), autocommit=True
    ) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    return admin.set(
        drivername="postgresql+psycopg",
        database=item["name"],
        username=item["name"],
        password=item["password"],
    ).render_as_string(hide_password=False)


def prepare(config, request):
    if sys.platform != "linux":
        raise ValueError("Prepare in the configured Linux/Docker runtime")
    task_id = str(UUID(request["task_id"]))
    source = Path(config["source"])
    root = Path(request["root"])
    worktrees = Path(config["worktree_root"])
    runtime_root = Path(config["runtime_root"])
    if (
        request["source"] != str(source)
        or root != worktrees / f"codex-{task_id}"
        or any(
            not p.is_absolute() or p.resolve() != p for p in (source, root, worktrees, runtime_root)
        )
        or runtime_root.is_relative_to(source)
        or runtime_root.is_relative_to(worktrees)
        or git.repository_root(root) != root
    ):
        raise ValueError("Unexpected task preparation target")
    if git.git(root, "rev-parse", "HEAD").decode().strip() != request["revision"]:
        raise ValueError("Source changed before environment preparation")
    state = runtime_root / task_id
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.resolve() != state:
        raise ValueError("Unsafe private runtime path")
    state.chmod(0o700)
    env = {
        **{k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        "UV_LINK_MODE": "copy",
        "UV_CACHE_DIR": str(runtime_root / "uv-cache"),
    }
    env_file = root / ".env"
    if env_file.is_symlink():
        raise ValueError("Unsafe task environment file")
    if not env_file.exists():
        private_write(state / "progress.json", json.dumps({"step": "environment"}))
        template = git.read_worktree_file(root, ".env.example", missing_ok=False).decode()
        # Unprepared shared services are deliberately not inherited from dev.
        # The task's database is separate; other runtime services need their own
        # explicit profile before an app/worker is started.
        database = development_database(config.get("postgres"), state, task_id)
        overrides = {
            "MIY_ENVIRONMENT": "development",
            "MIY_POSTGRES_DSN": database
            or f"postgresql+psycopg://unconfigured@127.0.0.1:1/miy_wb_{UUID(task_id).hex}",
            "MIY_WORKER_BROKER_URL": "redis://127.0.0.1:1/0",
            "MIY_WORKER_RESULT_BACKEND": "redis://127.0.0.1:1/0",
            "MIY_API_COLLAB_REDIS_URL": "redis://127.0.0.1:1/0",
            "MIY_API_REALTIME_REDIS_URL": "redis://127.0.0.1:1/0",
            "MIY_DEV_REDIS_URL": "redis://127.0.0.1:1/0",
            "MIY_DEV_REDIS_RESULT_BACKEND": "redis://127.0.0.1:1/0",
            "MIY_MINIO_ENDPOINT": "http://127.0.0.1:1",
            "MIY_OPENSEARCH_URL": "http://127.0.0.1:1",
            "MIY_RAG_QDRANT_URL": "http://127.0.0.1:1",
            "MIY_HERMES_ENABLED": "false",
        }
        lines = [line for line in template.splitlines() if line.split("=", 1)[0] not in overrides]
        private_write(
            env_file,
            "\n".join(lines)
            + "\n"
            + "\n".join(f"{key}={value}" for key, value in overrides.items())
            + "\n",
        )
    # Package bytes are stored on Linux, while workspace links stay task-local.
    store = state / "pnpm"
    private_write(state / "progress.json", json.dumps({"step": "javascript"}))
    seed = source / "node_modules/.pnpm"
    if (
        not store.exists()
        and seed.is_dir()
        and digest(root / "pnpm-lock.yaml") == digest(source / "pnpm-lock.yaml")
    ):
        shutil.copytree(seed, store, symlinks=True)
    run(
        [
            config["pnpm"],
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--virtual-store-dir",
            str(store),
        ],
        cwd=root,
        env=env,
    )
    for name in ("api", "worker", "codex-console-api"):
        private_write(state / "progress.json", json.dumps({"step": "python-" + name}))
        project = root / "apps" / name
        target = state / "venvs" / name
        lock = project / "uv.lock"
        python = config.get("pythons", {}).get(name, config["python"])
        seed_info = config.get("venv_seeds", {}).get(name)
        if not target.exists() and seed_info and digest(lock) == seed_info["lock_sha256"]:
            shutil.copytree(Path(seed_info["path"]), target, symlinks=True)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            run(
                [config["uv"], "venv", "--python", python, str(target)],
                cwd=project,
                env=env,
            )
        link = project / ".venv"
        if link.is_symlink():
            if link.readlink() != target:
                raise ValueError("Unexpected task virtualenv")
        elif link.exists():
            raise ValueError("An existing virtualenv cannot be replaced")
        else:
            link.symlink_to(target, target_is_directory=True)
        run([config["uv"], "sync", "--frozen", "--python", python], cwd=project, env=env)
    private_write(
        state / "ready.json",
        json.dumps(
            {
                "task_id": task_id,
                "revision": request["revision"],
                "dependencies": "ready",
                "services_started": False,
            }
        ),
    )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    info = args.config.lstat()
    if (
        not args.config.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or info.st_size > 32768
    ):
        raise SystemExit("Use a protected operator-owned preparation config")
    try:
        request = json.loads(sys.stdin.buffer.read(8193))
        prepare(json.loads(args.config.read_text()), request)
    except Exception:
        # Child/install/config failures must not publish DSNs or installer logs.
        raise SystemExit("Task environment preparation failed") from None


if __name__ == "__main__":
    main()
