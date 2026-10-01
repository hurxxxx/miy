from types import SimpleNamespace

from codex_console import host


def test_host_memory_survives_missing_cgroup_and_disks_are_deduplicated(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8192 kB\nMemAvailable: 2048 kB\nSwapTotal: 2048 kB\nSwapFree: 1024 kB\n"
    )
    result = host.collect(
        SimpleNamespace(workspace=tmp_path), proc=proc, cgroups=tmp_path / "absent"
    )
    assert result["memory"] == {
        "total": 8192 * 1024,
        "used": 6144 * 1024,
        "available": 2048 * 1024,
        "swap_total": 2048 * 1024,
        "swap_used": 1024 * 1024,
    }
    assert len(result["disks"]) == 1
    assert result["disks"][0]["total"] > 0


def test_host_observes_tightest_parent_cgroup_and_reports_missing_memory(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/parent/child\n")
    (proc / "meminfo").write_text("MemTotal: 8192 kB\nMemAvailable: 2048 kB\n")
    groups = tmp_path / "groups"
    child = groups / "parent/child"
    child.mkdir(parents=True)
    for path, limit, used in [
        (groups, "max", 8192),
        (child.parent, "4096", 3072),
        (child, "8192", 2048),
    ]:
        (path / "memory.max").write_text(limit)
        (path / "memory.current").write_text(str(used))
    cfg = SimpleNamespace(workspace=tmp_path)
    result = host.collect(cfg, proc=proc, cgroups=groups)
    assert result["memory"]["cgroup_limit"] == 4096
    assert result["memory"]["cgroup_used"] == 3072
    (proc / "meminfo").unlink()
    assert "memory" not in host.collect(cfg, proc=proc, cgroups=groups)
