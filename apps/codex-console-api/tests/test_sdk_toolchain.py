"""Offline artifact/cache failure boundaries; no service, network, or application execution."""

import hashlib
import io
import json
import os
import runpy
import struct
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
VERIFY = runpy.run_path(str(ROOT / "scripts/verify-native-sdk-toolchain.py"))
Refused = VERIFY["ToolchainRefused"]


@pytest.fixture(autouse=True)
def writable_owned_temp_cleanup(tmp_path):
    yield
    # Keep pytest's own disposable directory removable after readonly-cache cases.
    for path in tmp_path.rglob("*"):
        if not path.is_symlink() and path.is_dir():
            path.chmod(0o700)
    tmp_path.chmod(0o700)


def elf(*, machine=62, soname=None, needed=(), requires=None, defines=()):
    """Small valid ELF, deliberately independent of any host/toolchain executable."""
    data = bytearray(16384)
    strings = bytearray(b"\0")

    def name(value):
        index = len(strings)
        strings.extend(value.encode() + b"\0")
        return index

    dynamic = [(5, 0x400)]
    dynamic += [(1, name(value)) for value in needed]
    if soname:
        dynamic.append((14, name(soname)))
    requires = requires or {}
    cursor = 0x800
    if requires:
        dynamic += [(0x6FFFFFFE, cursor), (0x6FFFFFFF, len(requires))]
        for number, (provider, versions) in enumerate(requires.items()):
            size = 16 + len(versions) * 16
            struct.pack_into(
                "<HHIII",
                data,
                cursor,
                1,
                len(versions),
                name(provider),
                16,
                size if number + 1 < len(requires) else 0,
            )
            for index, version in enumerate(versions):
                struct.pack_into(
                    "<IHHII",
                    data,
                    cursor + 16 + index * 16,
                    0,
                    0,
                    0,
                    name(version),
                    16 if index + 1 < len(versions) else 0,
                )
            cursor += size
    if defines:
        cursor = 0x1800
        dynamic += [(0x6FFFFFFC, cursor), (0x6FFFFFFD, len(defines))]
        for index, version in enumerate(defines):
            struct.pack_into(
                "<HHHHIII",
                data,
                cursor,
                1,
                0,
                index + 1,
                1,
                0,
                20,
                28 if index + 1 < len(defines) else 0,
            )
            struct.pack_into("<II", data, cursor + 20, name(version), 0)
            cursor += 28
    dynamic += [(10, len(strings)), (0, 0)]
    data[0x400 : 0x400 + len(strings)] = strings
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into(
        "<16sHHIQQQIHHHHHH", data, 0, ident, 3, machine, 1, 0, 64, 0, 0, 64, 56, 2, 0, 0, 0
    )
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, len(data), len(data), 4096)
    struct.pack_into(
        "<IIQQQQQQ", data, 120, 2, 6, 0x200, 0x200, 0, len(dynamic) * 16, len(dynamic) * 16, 8
    )
    for index, (tag, value) in enumerate(dynamic):
        struct.pack_into("<qQ", data, 0x200 + index * 16, tag, value)
    return bytes(data)


def artifact(tmp_path, *, extra=None):
    records = []
    payloads = {}
    for component in sorted(VERIFY["COMPONENTS"]):
        records.append({"path": component, "kind": "directory", "mode": 0o555})
        name = component + "/payload"
        value = elf() if component == "node" else component.encode()
        payloads[name] = value
        records.append(VERIFY["_file_record"](name, 0o444, value))
    records.sort(key=lambda row: row["path"])
    archive = tmp_path / "sdk.tar.xz"
    with tarfile.open(archive, "w:xz") as output:
        for row in records + (extra or []):
            info = tarfile.TarInfo(row["path"])
            if row["kind"] == "directory":
                info.type = tarfile.DIRTYPE
                info.mode = row["mode"]
                output.addfile(info)
            elif row["kind"] == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = row["target"]
                output.addfile(info)
            else:
                value = payloads.get(row["path"], b"unexpected")
                info.mode = row["mode"]
                info.size = len(value)
                output.addfile(info, io.BytesIO(value))
    raw = archive.read_bytes()
    pin = {
        "schema_version": 1,
        "toolchain_id": "miy-test-sdk-v1",
        "target": "x86_64-unknown-linux-gnu",
        "native_version": "0.160.1",
        "versions": {"node": "22.23.3", "python": "3.12.14", "pnpm": "10.34.5"},
        "bundle": {
            **VERIFY["summary"](records),
            "format": "tar.xz",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "components": {
            c: VERIFY["summary"]([r for r in records if r["path"].split("/")[0] == c])
            for c in VERIFY["COMPONENTS"]
        },
        "elf": [{"path": "node/payload", "metadata": VERIFY["elf_metadata"](elf())}],
    }
    return archive, pin, records


def test_archive_snapshot_survives_path_replacement(tmp_path):
    archive, pin, _ = artifact(tmp_path)
    records, _, snapshot = VERIFY["inspect_archive"](archive, pin)
    archive.unlink()
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"Never read or extract this replacement")
    archive.symlink_to(foreign)
    destination = tmp_path / "new-cache"
    VERIFY["extract_verified_archive"](snapshot, destination, records)
    actual, files = VERIFY["scan_tree"](destination)
    VERIFY["verify_inventory"](actual, pin)
    VERIFY["verify_elf"](files, pin)
    assert (destination / "node/payload").read_bytes() == elf()
    assert foreign.read_bytes() == b"Never read or extract this replacement"


def test_existing_stage_never_overwritten(tmp_path):
    archive, pin, _ = artifact(tmp_path)
    records, _, snapshot = VERIFY["inspect_archive"](archive, pin)
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "owned"
    sentinel.write_text("preserve")
    with pytest.raises(FileExistsError):
        VERIFY["extract_verified_archive"](snapshot, destination, records)
    assert sentinel.read_text() == "preserve"


@pytest.mark.parametrize(
    "path", ["/escape", "node/../../escape", "node/./payload", "other/payload"]
)
def test_unsafe_archive_member_refused_before_stage(tmp_path, path):
    archive, pin, _ = artifact(tmp_path, extra=[{"path": path, "kind": "file", "mode": 0o444}])
    with pytest.raises(Refused):
        VERIFY["inspect_archive"](archive, pin)
    assert not (tmp_path / "new-cache").exists()


@pytest.mark.parametrize("target", ["/outside", "../../outside", "missing", "self"])
def test_bad_symlink_refused(tmp_path, target):
    archive, pin, _ = artifact(
        tmp_path, extra=[{"path": "node/self", "kind": "symlink", "target": target}]
    )
    with pytest.raises(Refused):
        VERIFY["inspect_archive"](archive, pin)


def test_duplicate_archive_member_refused(tmp_path):
    archive, pin, _ = artifact(
        tmp_path, extra=[{"path": "node/payload", "kind": "file", "mode": 0o444}]
    )
    with pytest.raises(Refused, match="duplicate_member"):
        VERIFY["inspect_archive"](archive, pin)


def test_artifact_digest_tamper_refused(tmp_path):
    archive, pin, _ = artifact(tmp_path)
    value = bytearray(archive.read_bytes())
    value[-1] ^= 1
    archive.write_bytes(value)
    with pytest.raises(Refused, match="artifact_digest_mismatch"):
        VERIFY["inspect_archive"](archive, pin)


@pytest.mark.parametrize("change", ["extra", "tampered", "mutable", "hardlink", "fifo"])
def test_installed_tree_failure_boundaries(tmp_path, change):
    archive, pin, _ = artifact(tmp_path)
    records, _, snapshot = VERIFY["inspect_archive"](archive, pin)
    destination = tmp_path / "new-cache"
    VERIFY["extract_verified_archive"](snapshot, destination, records)
    directory = destination / "sdk"
    directory.chmod(0o755)
    leaf = directory / "payload"
    if change == "extra":
        (directory / "extra").write_text("extra")
    elif change == "tampered":
        leaf.chmod(0o644)
        leaf.write_text("tampered")
        leaf.chmod(0o444)
    elif change == "mutable":
        leaf.chmod(0o644)
    elif change == "hardlink":
        os.link(leaf, directory / "alias")
    else:
        os.mkfifo(directory / "fifo")
    directory.chmod(0o555)
    with pytest.raises(Refused):
        actual, _ = VERIFY["scan_tree"](destination)
        VERIFY["verify_inventory"](actual, pin)


def scan_file(tmp_path, value):
    root = tmp_path / "cache"
    directory = root / "node"
    directory.mkdir(parents=True)
    leaf = directory / "payload"
    leaf.write_bytes(value)
    leaf.chmod(0o444)
    directory.chmod(0o555)
    root.chmod(0o555)
    return root, leaf


@pytest.mark.parametrize("size", [0, 9, 16])
def test_cache_scan_reads_observed_size_and_hashes_all_bytes(tmp_path, monkeypatch, size):
    value = b"x" * size
    root, _ = scan_file(tmp_path, value)
    monkeypatch.setitem(VERIFY["scan_tree"].__globals__, "MAX_FILE_BYTES", 16)
    requests = []
    original_fdopen = os.fdopen

    @contextmanager
    def observe(fd, mode):
        with original_fdopen(fd, mode) as stream:

            def read(requested):
                requests.append(requested)
                return stream.read(requested)

            yield SimpleNamespace(fileno=stream.fileno, read=read)

    monkeypatch.setattr(os, "fdopen", observe)
    records, files = VERIFY["scan_tree"](root)
    assert requests == [size + 1]
    assert records == [
        {"path": "node", "kind": "directory", "mode": 0o555},
        {
            "path": "node/payload",
            "kind": "file",
            "mode": 0o444,
            "bytes": size,
            "sha256": hashlib.sha256(value).hexdigest(),
        },
    ]
    assert files == {}


@pytest.mark.parametrize("change", [-1, 1], ids=["shrunk", "grew"])
def test_cache_scan_refuses_size_change_between_fstat_and_read(tmp_path, monkeypatch, change):
    root, leaf = scan_file(tmp_path, b"x" * 8)
    original_fdopen = os.fdopen

    @contextmanager
    def mutate(fd, mode):
        with original_fdopen(fd, mode) as stream:

            def read(requested):
                leaf.chmod(0o644)
                leaf.write_bytes(b"x" * (8 + change))
                leaf.chmod(0o444)
                return stream.read(requested)

            yield SimpleNamespace(fileno=stream.fileno, read=read)

    monkeypatch.setattr(os, "fdopen", mutate)
    with pytest.raises(Refused, match="^cache_changed_during_read$"):
        VERIFY["scan_tree"](root)


def test_cache_scan_file_budget_refused_before_read(tmp_path, monkeypatch):
    root, _ = scan_file(tmp_path, b"x" * 17)
    monkeypatch.setitem(VERIFY["scan_tree"].__globals__, "MAX_FILE_BYTES", 16)
    requests = []
    original_fdopen = os.fdopen

    @contextmanager
    def observe(fd, mode):
        with original_fdopen(fd, mode) as stream:

            def read(requested):
                requests.append(requested)
                return stream.read(requested)

            yield SimpleNamespace(fileno=stream.fileno, read=read)

    monkeypatch.setattr(os, "fdopen", observe)
    with pytest.raises(Refused, match="^unsafe_regular_file$"):
        VERIFY["scan_tree"](root)
    assert requests == []


@pytest.mark.parametrize(
    "mutation", ["missing_hash", "wrong_target", "wrong_version", "missing_component"]
)
def test_incomplete_pin_refused(tmp_path, mutation):
    _, pin, _ = artifact(tmp_path)
    if mutation == "missing_hash":
        pin["bundle"]["sha256"] = None
    elif mutation == "wrong_target":
        pin["target"] = "linux-arm64"
    elif mutation == "wrong_version":
        pin["versions"]["node"] = "latest"
    else:
        del pin["components"]["runtime"]
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(pin))
    with pytest.raises(Refused):
        VERIFY["load_pin"](path)


def test_each_elf_requirement_resolves_to_its_actual_provider():
    consumer = elf(needed=("libc.so.6",), requires={"libc.so.6": ["GLIBC_2.38"]})
    wrong = elf(soname="libc.so.6", defines=["GLIBC_2.36"])
    decoy = elf(soname="libdecoy.so.1", defines=["GLIBC_2.38"])
    files = {
        "node/consumer": consumer,
        "runtime/lib/libc.so.6": wrong,
        "runtime/lib/libdecoy.so.1": decoy,
    }
    pin = {"elf": [{"path": p, "metadata": VERIFY["elf_metadata"](v)} for p, v in files.items()]}
    with pytest.raises(Refused, match="elf_provider_version_mismatch"):
        VERIFY["verify_elf"](files, pin)


def test_exact_provider_version_passes():
    consumer = elf(needed=("libc.so.6",), requires={"libc.so.6": ["GLIBC_2.36"]})
    provider = elf(soname="libc.so.6", defines=["GLIBC_2.36"])
    files = {"node/consumer": consumer, "runtime/lib/libc.so.6": provider}
    pin = {"elf": [{"path": p, "metadata": VERIFY["elf_metadata"](v)} for p, v in files.items()]}
    VERIFY["verify_elf"](files, pin)


@pytest.mark.parametrize("data", [b"not ELF", elf(machine=183), elf()[:80]])
def test_wrong_or_truncated_elf_refused(data):
    with pytest.raises(Refused):
        VERIFY["elf_metadata"](data)


@pytest.mark.parametrize(
    "path", ["/tmp/cache", "/home/operator/cache", "/opt/miy/..", "/opt/miy/nested/cache"]
)
def test_install_contract_does_not_accept_mutable_outside_roots(path):
    with pytest.raises(Refused, match="cache_install_path_refused"):
        VERIFY["install_path"](Path(path), new=True)


def test_sdk_unit_preserves_app_owned_manifests_and_native_lifecycle():
    unit = (ROOT / "ops/codex-console/executor/miy-app-sdk-executor.service.example").read_text()
    for filename in ["package.json", "pnpm-lock.yaml", "pyproject.toml", ".npmrc"]:
        assert f"@SOURCE_ROOT@/{filename}" not in unit
    assert "--setenv NPM_CONFIG_USERCONFIG @SDK_ROOT@/profile/.npmrc" in unit
    for directive in [
        "PrivateNetwork=yes",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "CPUQuota=100%",
        "MemoryMax=1073741824",
        "MemorySwapMax=0",
        "TasksMax=64",
        "RuntimeMaxSec=270",
        "TimeoutStopSec=3",
        "KillMode=control-group",
        "Restart=no",
    ]:
        assert directive in unit
    assert "--ro-bind @SOURCE_ROOT@/.git @SOURCE_ROOT@/.git" in unit
    assert "--ro-bind @SDK_ROOT@/runtime/bin/env /usr/bin/env" in unit
    assert "--ro-bind @SDK_ROOT@/runtime/lib /usr/lib/x86_64-linux-gnu" in unit
    assert "--ro-bind /usr/lib" not in unit
    assert "-- @VENDOR_ROOT@/bin/codex exec-server" in unit
    assert "--ws-auth capability-token --ws-token-sha256 @TOKEN_SHA256@" in unit
    assert "[Install]" not in unit


def test_committed_pin_binds_frozen_graph_and_current_core_sdk():
    pin = VERIFY["load_pin"]()
    for name, expected in pin["source_inputs"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert pin["supported_graphs"] == ["web-api-v1", "web-api-postgres-v1"]
    assert pin["scope"]["arbitrary_dependency_acquisition"] is False
    assert pin["scope"]["service_activation"] == "explicit_core_operator"
    assert pin["package_manager"]["public_configuration"]["prefer-symlinked-executables"] is True
