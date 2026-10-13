#!/usr/bin/env python3
"""Install user-owned macOS Workbench jobs; never start or stop existing work."""

import argparse
import os
import plistlib
import stat
import sys
from pathlib import Path

ROLES = {"session": "serve", "management": "manage", "templates": "templates"}


def private_file(path):
    info = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ValueError("Use a private regular file owned by the service user")


def jobs(release, environment, logs, search_path, home):
    api = release / "apps/codex-console-api"
    python = api / ".venv/bin/python"
    return {
        role: {
            "Label": f"com.miy.workbench.{role}",
            "ProgramArguments": [
                str(python),
                "-m",
                "codex_console.cli",
                command,
                "--env-file",
                str(environment),
            ],
            "WorkingDirectory": str(api),
            "EnvironmentVariables": {"HOME": str(home), "PATH": search_path},
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "ExitTimeOut": 30,
            "Umask": 0o077,
            "StandardOutPath": str(logs / f"{role}.log"),
            "StandardErrorPath": str(logs / f"{role}.log"),
        }
        for role, command in ROLES.items()
    }


def install(release, environment, agents, logs, search_path, *, replace=False):
    if (
        not release.is_absolute()
        or not (release / "apps/codex-console-api/.venv/bin/python").is_file()
    ):
        raise ValueError("Build a host release with its own Python environment first")
    private_file(environment)
    if not agents.is_absolute() or not logs.is_absolute():
        raise ValueError("Select absolute service and log directories")
    definitions = jobs(release, environment, logs, search_path, Path.home())
    # Check every destination before writing any job. Existing foreign jobs are never replaced.
    for definition in definitions.values():
        target = agents / (definition["Label"] + ".plist")
        if target.exists() or target.is_symlink():
            private_file(target)
            if not replace:
                raise ValueError(
                    "Jobs already exist; stop idle services before using --replace"
                )
    agents.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (
        logs.is_symlink()
        or logs.stat().st_uid != os.getuid()
        or logs.stat().st_mode & 0o077
    ):
        raise ValueError("Use a private log directory owned by the service user")
    for role, definition in definitions.items():
        log = logs / f"{role}.log"
        if log.exists() or log.is_symlink():
            private_file(log)
        else:
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        target = agents / (definition["Label"] + ".plist")
        temporary = target.with_suffix(".plist.next")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                plistlib.dump(definition, output)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return list(definitions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument(
        "--agents", type=Path, default=Path.home() / "Library/LaunchAgents"
    )
    parser.add_argument("--path", default=os.environ.get("PATH", os.defpath))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error(
            "Use this installer on macOS; Linux uses the systemd service files"
        )
    install(
        args.release,
        args.env_file,
        args.agents,
        args.logs,
        args.path,
        replace=args.replace,
    )
    print(
        "Three private LaunchAgent jobs installed; no services were started or stopped."
    )


if __name__ == "__main__":
    main()
