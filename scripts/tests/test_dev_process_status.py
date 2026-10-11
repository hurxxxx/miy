from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dev_worker_processes", ROOT / "scripts/dev-worker-processes.py"
)
workers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workers)

ENTRY = "miy_worker.celery_app:celery_app"
INTERPRETER = "/owned/python3.12"
UID = 1000


def process(
    pid,
    ppid=1,
    *,
    uid=UID,
    cwd=None,
    exe=INTERPRETER,
    entry=ENTRY,
    role="worker",
    hostname="",
):
    argv = ("python3", "-m", "celery", "-A", entry, role)
    if hostname:
        argv += ("--hostname=" + hostname,)
    return workers.Process(pid, ppid, uid, cwd or str(ROOT / "apps/worker"), exe, argv)


def inventory(*entries):
    return {item.pid: item for item in (workers.Process(1, 0, 0), *entries)}


def test_native_main_excludes_identical_argv_prefork_descendants_and_wrappers():
    wrapper = process(10, exe="/owned/uv")
    shell = process(11, 10, exe="/bin/dash")
    main = process(12, 11)
    # No process title hint: real prefork children preserve the original argv.
    child = process(13, 12)
    descendant = process(14, 13)
    beat = process(20, role="beat")
    assert workers.native_mains(
        inventory(wrapper, shell, main, child, descendant, beat), ROOT, UID, INTERPRETER
    ) == [
        (12, ENTRY, "worker", ""),
        (20, ENTRY, "beat", ""),
    ]


def test_production_sibling_and_other_uid_are_not_owned():
    entries = inventory(
        process(101, cwd="/opt/miy/apps/worker"),
        process(102, cwd=str(ROOT) + "-sibling/apps/worker"),
        process(103, uid=10001),
        process(104, cwd=str(ROOT / "apps/worker/child")),
        process(105),
    )
    assert workers.native_mains(entries, ROOT, UID, INTERPRETER) == [
        (105, ENTRY, "worker", "")
    ]


def test_independent_first_party_and_explicit_transient_mains_keep_bindings():
    platform = "miy_worker.first_party_platform:celery_app"
    official = "miy_official_worker.runtime:celery_app"
    entries = inventory(
        process(10, entry=platform, hostname="miy-dev-platform@%h"),
        process(20, entry=official, hostname="miy-dev-official@%h"),
        process(30, hostname="miy-dev-legacy-handoff@owned"),
    )
    assert workers.native_mains(entries, ROOT, UID, INTERPRETER) == [
        (10, platform, "worker", "miy-dev-platform@%h"),
        (20, official, "worker", "miy-dev-official@%h"),
        (30, ENTRY, "worker", "miy-dev-legacy-handoff@owned"),
    ]


@pytest.mark.parametrize(
    "entries",
    [
        inventory(process(10, entry="unknown:celery_app")),
        inventory(process(10, exe="/other/python3.12")),
        inventory(process(10, ppid=999)),
        inventory(process(10, ppid=11), process(11, ppid=10)),
        inventory(
            process(10),
            process(11, ppid=10, entry="miy_official_worker.runtime:celery_app"),
        ),
        inventory(process(10, hostname="invalid hostname")),
    ],
)
def test_unknown_native_identity_or_ancestry_holds(entries):
    with pytest.raises(workers.InventoryUnavailable):
        workers.native_mains(entries, ROOT, UID, INTERPRETER)


def test_real_script_entry_is_valid_but_rewritten_unknown_title_holds():
    script = (
        str(ROOT / "apps/worker/.venv/bin/python3"),
        str(ROOT / "apps/worker/.venv/bin/celery"),
        "-A",
        ENTRY,
        "worker",
    )
    assert workers.command(script, ROOT) == (ENTRY, "worker", "")
    with pytest.raises(workers.InventoryUnavailable):
        workers.command(("[celeryd: owned:MainProcess]",), ROOT)
    with pytest.raises(workers.InventoryUnavailable):
        workers.command(("python3", "/external/celery", "-A", ENTRY, "worker"), ROOT)


def test_snapshot_only_reads_matching_owner_workdir_metadata(tmp_path):
    root = tmp_path / "checkout"
    worker = root / "apps/worker"
    worker.mkdir(parents=True)
    executable = tmp_path / "python3.12"
    executable.touch()
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, ppid, uid in ((1, 0, 0), (10, 1, UID), (11, 10, UID)):
        folder = proc / str(pid)
        folder.mkdir()
        (folder / "status").write_text(
            f"State:\tS\nPPid:\t{ppid}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        )
        if uid == UID:
            (folder / "cwd").symlink_to(worker)
            (folder / "exe").symlink_to(executable)
            (folder / "cmdline").write_bytes(
                b"\0".join(
                    value.encode()
                    for value in ("python3", "-m", "celery", "-A", ENTRY, "worker")
                )
            )
    general = proc / "12"
    general.mkdir()
    (general / "status").write_text(f"State:\tS\nPPid:\t1\nUid:\t{UID}\n")
    (general / "cmdline").write_bytes(b"systemd\0--user\0")
    assert workers.native_mains(
        workers.snapshot(root, UID, proc), root, UID, str(executable)
    ) == [(10, ENTRY, "worker", "")]
    (proc / "10/exe").unlink()
    with pytest.raises(workers.InventoryUnavailable):
        workers.snapshot(root, UID, proc)


def test_helper_failure_propagates_without_worker_signal_or_fake_pgrep(tmp_path):
    fake_python = tmp_path / "python3"
    fake_python.write_text("#!/bin/sh\nexit 1\n")
    fake_python.chmod(0o755)
    source = (ROOT / "dev.sh").read_text()
    selector = source[
        source.index("find_worker_processes() {") : source.index("process_is_owned() {")
    ]
    stop = source[
        source.index("stop_project_processes() {") : source.index(
            "if (( status_only ))"
        )
    ]
    body = f'ROOT_DIR="{ROOT}"\n{selector}\n{stop}\nkill_if_running() {{ printf "SIGNAL\\n"; }}\nstop_project_processes worker\n'
    result = subprocess.run(
        ["bash", "-c", body],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "SIGNAL" not in result.stdout


def test_selected_shutdown_waits_for_worker_before_publishers_or_beat(tmp_path):
    source = (ROOT / "dev.sh").read_text()
    selection = source[
        source.index("project_selected() {") : source.index("find_worker_processes() {")
    ]
    stop = source[
        source.index("stop_selected_projects() {") : source.index(
            'if [[ -n "${VIRTUAL_ENV:-}" ]]'
        )
    ]
    counter = tmp_path / "observations"
    counter.write_text("0")
    body = f"""projects=(web api official-suite worker)
{selection}
{stop}
stop_project_processes() {{ printf 'STOP %s %s\\n' "$1" "${{2:-}}"; }}
sleep() {{ printf 'WAIT\\n'; }}
find_worker_processes() {{
  count="$(cat '{counter}')"
  printf '%s' "$((count + 1))" > '{counter}'
  if [[ "$count" == 0 ]]; then printf '12 {ENTRY} worker\\n'; fi
}}
stop_selected_projects
"""
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "STOP worker worker",
        "WAIT",
        "STOP web ",
        "STOP api ",
        "STOP official-suite ",
        "STOP worker beat",
    ]


def test_selected_shutdown_metadata_failure_keeps_publishers_and_beat_alive():
    source = (ROOT / "dev.sh").read_text()
    selection = source[
        source.index("project_selected() {") : source.index("find_worker_processes() {")
    ]
    stop = source[
        source.index("stop_selected_projects() {") : source.index(
            'if [[ -n "${VIRTUAL_ENV:-}" ]]'
        )
    ]
    body = f"""projects=(web api official-suite worker)
{selection}
{stop}
stop_project_processes() {{ printf 'STOP %s %s\\n' "$1" "${{2:-}}"; }}
find_worker_processes() {{ return 1; }}
stop_selected_projects
"""
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["STOP worker worker"]


def test_native_setsid_isolates_session_and_preserves_runner_exit_status(tmp_path):
    pnpm = tmp_path / "pnpm"
    pnpm.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "print(os.getsid(0), os.getpgrp(), flush=True)\n"
        "raise SystemExit(27)\n"
    )
    pnpm.chmod(0o755)
    source = (ROOT / "dev.sh").read_text()
    launch = source[source.index("setsid --wait pnpm exec nx run-many") :]
    body = f"""project_csv=web
parallelism=1
output_style=stream
nx_configuration=()
{launch}
"""
    result = subprocess.run(
        ["bash", "-c", body],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 27
    session, group = map(int, result.stdout.split())
    assert session == group
    assert session != os.getsid(0)
    assert group != os.getpgrp()


def test_missing_setsid_holds_before_starting_runner():
    source = (ROOT / "dev.sh").read_text()
    guard = source[
        source.index("if ! command -v setsid") : source.index("# Namespace changes use")
    ]
    result = subprocess.run(
        ["bash", "-c", "command() { return 1; }\n" + guard + 'printf "STARTED\\n"'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "startup HOLD" in result.stderr
    assert "STARTED" not in result.stdout


def test_launcher_term_trap_runs_while_runner_waits_and_preserves_warm_order(
    tmp_path,
):
    source = (ROOT / "dev.sh").read_text()
    selection = source[
        source.index("project_selected() {") : source.index("find_worker_processes() {")
    ]
    stop = source[
        source.index("stop_selected_projects() {") : source.index(
            'if [[ -n "${VIRTUAL_ENV:-}" ]]'
        )
    ]
    tail = source[source.index("cleanup() {") :]
    warm, finished, ready, done = (
        tmp_path / name for name in ("warm", "finished", "ready", "done")
    )
    pnpm = tmp_path / "pnpm"
    pnpm.write_text(
        f"#!{sys.executable}\n"
        "import time\nfrom pathlib import Path\n"
        f"Path({str(ready)!r}).touch()\n"
        f"while not Path({str(done)!r}).exists(): time.sleep(0.01)\n"
    )
    pnpm.chmod(0o755)
    body = f"""set -Eeuo pipefail
projects=(api worker)
project_csv=api,worker
parallelism=2
output_style=stream
nx_configuration=()
{selection}
{stop}
stop_project_processes() {{
  if [[ "$1:${{2:-}}" == worker:worker ]]; then touch '{warm}'; fi
  if [[ "$1:${{2:-}}" == worker:beat ]]; then touch '{done}'; fi
  if [[ "$1" == api ]]; then test -e '{finished}'; fi
}}
find_worker_processes() {{
  if [[ ! -e '{finished}' ]]; then printf '12 {ENTRY} worker\\n'; fi
}}
{tail}
"""
    child = subprocess.Popen(
        ["bash", "-c", body],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for observation in (ready, warm):
            if observation == warm:
                # Only this synthetic launcher is signaled; no MIY service or
                # native task is started, observed or signaled by the test.
                child.send_signal(signal.SIGTERM)
            deadline = time.monotonic() + 5
            while not observation.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert observation.exists()
        assert child.poll() is None
        assert not done.exists()
        finished.touch()
        _, errors = child.communicate(timeout=5)
        assert child.returncode == 130, errors
        assert done.exists()
    finally:
        finished.touch()
        done.touch()
        child.wait(timeout=5)
