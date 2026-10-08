"""Own a test-only PostgreSQL process, without access to a shared cluster."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
from tempfile import TemporaryDirectory
import time

import psycopg
from psycopg.conninfo import make_conninfo


def postgres_major():
    result = subprocess.run(
        ["pg_dump", "--version"], capture_output=True, text=True, timeout=5, check=True
    )
    match = re.fullmatch(r"pg_dump \(PostgreSQL\) (\d+)\.[^\n]+\n?", result.stdout)
    if match is None:
        raise RuntimeError("PostgreSQL test client version is unavailable")
    return int(match[1])


def native_bin_dir(major):
    directory = Path(f"/usr/lib/postgresql/{major}/bin")
    names = ("initdb", "postgres")
    return directory if all((directory / name).is_file() for name in names) else None


@contextmanager
def native_cluster(directory, major):
    # CI runs as root; PostgreSQL itself always runs without root privileges.
    identity = {"user": 65534, "group": 65534, "extra_groups": []} if os.geteuid() == 0 else {}
    with TemporaryDirectory(prefix="miy-isolated-postgres-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        if identity:
            os.chown(root, identity["user"], identity["group"])
        env = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}
        password = os.urandom(24).hex()
        password_file = root / "bootstrap-password"
        password_file.write_text(password + "\n")
        password_file.chmod(0o600)
        if identity:
            os.chown(password_file, identity["user"], identity["group"])
        try:
            subprocess.run(
                [
                    str(directory / "initdb"),
                    "-D",
                    str(root / "data"),
                    "-U",
                    "postgres",
                    "--auth=scram-sha-256",
                    "--pwfile=" + str(password_file),
                    "--no-locale",
                    "--encoding=UTF8",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True,
                **identity,
            )
        finally:
            password_file.unlink()
        # The private Unix socket and loopback both require real SCRAM credentials.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen(
            [
                str(directory / "postgres"),
                "-D",
                str(root / "data"),
                "-k",
                str(root),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-c",
                "shared_buffers=16MB",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **identity,
        )
        dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname="postgres", user="postgres", password=password
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Owned PostgreSQL process exited during startup")
                try:
                    with psycopg.connect(
                        host="127.0.0.1",
                        port=port,
                        dbname="postgres",
                        user="postgres",
                        password=password,
                        connect_timeout=1,
                    ) as conn:
                        version = conn.execute("SHOW server_version_num").fetchone()[0]
                        assert int(version) // 10000 == major
                    break
                except psycopg.OperationalError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Owned PostgreSQL startup timed out")
            yield dsn
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
