import csv
import hashlib
import importlib.util
import io
import json
import os
import runpy
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "sdk_producer", ROOT / "scripts/build-native-sdk-toolchain.py"
)
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


def archive(rows):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as packed:
        for name, kind, value in rows:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.mode = 0o644
                member.size = len(value)
                packed.addfile(member, io.BytesIO(value))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = value
                packed.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = value
                packed.addfile(member)
            elif kind == "fifo":
                member.type = tarfile.FIFOTYPE
                packed.addfile(member)
            elif kind == "setid":
                member.mode = 0o4755
                member.size = len(value)
                packed.addfile(member, io.BytesIO(value))
    return output.getvalue()


def test_verified_snapshot_is_not_reopened_when_external_input_path_changes(tmp_path):
    source = tmp_path / "distribution.tar.gz"
    content = archive([("package/payload", "file", b"attested")])
    source.write_bytes(content)
    snapshot = producer.snapshot(source, hashlib.sha256(content).hexdigest(), len(content))
    source.unlink()
    source.symlink_to(tmp_path / "unrelated-must-not-read")
    staged = producer.stage_inputs({"toolchain/distribution.tar.gz": snapshot}, tmp_path)
    assert (staged / "toolchain/distribution.tar.gz").read_bytes() == content
    target = tmp_path / "selected"
    producer.extract_distribution(snapshot, target, "package", lambda name: True)
    assert (target / "payload").read_bytes() == b"attested"


@pytest.mark.parametrize("kind", ["digest", "size", "symlink", "hardlink", "fifo"])
def test_external_artifact_changes_refuse_before_any_extraction(tmp_path, kind):
    source = tmp_path / "input"
    value = b"public"
    source.write_bytes(value)
    digest = hashlib.sha256(value).hexdigest()
    expected_size = len(value)
    if kind == "digest":
        source.write_bytes(b"changed")
        expected_size = 7
    elif kind == "size":
        expected_size += 1
    elif kind == "symlink":
        source.unlink()
        source.symlink_to(tmp_path / "not-read")
    elif kind == "hardlink":
        os.link(source, tmp_path / "shared")
    elif kind == "fifo":
        source.unlink()
        os.mkfifo(source)
    with pytest.raises((producer.ProducerRefused, OSError)):
        producer.snapshot(source, digest, expected_size)


@pytest.mark.parametrize(
    "rows",
    [
        [("/package/outside", "file", b"x")],
        [("package/../outside", "file", b"x")],
        [("other/payload", "file", b"x")],
        [("package/payload", "file", b"a"), ("package/payload", "file", b"b")],
        [("package/payload", "setid", b"x")],
        [("package/pipe", "fifo", b"")],
        [("package/link", "hardlink", "package/file")],
        [("package/link", "symlink", "../../outside")],
        [("package/link", "symlink", "/outside")],
        [("package/link", "symlink", "missing")],
        [("package/a", "symlink", "b"), ("package/b", "symlink", "a")],
    ],
)
def test_unsafe_distribution_members_never_write_outside_owned_tree(tmp_path, rows):
    destination = tmp_path / "tree"
    with pytest.raises(producer.ProducerRefused):
        producer.extract_distribution(archive(rows), destination, "package", lambda name: True)
    assert not (tmp_path / "outside").exists()


def test_distribution_links_created_after_regular_bytes_and_select_only_declared_members(tmp_path):
    content = archive(
        [
            ("package/link", "symlink", "nested/payload"),
            ("package/nested/payload", "file", b"public"),
            ("package/unselected", "file", b"unused"),
        ]
    )
    destination = tmp_path / "tree"
    producer.extract_distribution(
        content, destination, "package", lambda name: name != "unselected"
    )
    assert (destination / "link").read_bytes() == b"public"
    assert os.readlink(destination / "link") == "nested/payload"
    assert not (destination / "unselected").exists()


def test_archive_expansion_has_member_and_byte_budgets(monkeypatch):
    content = archive([("package/a", "file", b"a"), ("package/b", "file", b"b")])
    monkeypatch.setattr(producer, "MAX_ARCHIVE_MEMBERS", 1)
    with pytest.raises(producer.ProducerRefused, match="expanded_archive_budget"):
        list(producer.archive_members(content))
    monkeypatch.setattr(producer, "MAX_ARCHIVE_MEMBERS", 10)
    monkeypatch.setattr(producer, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(producer.ProducerRefused, match="expanded_archive_budget"):
        list(producer.archive_members(content))


@pytest.mark.parametrize(
    "url",
    [
        "http://nodejs.org/file",
        "https://nodejs.org.evil.test/file",
        "https://user:secret@nodejs.org/file",
        "https://127.0.0.1/file",
        "https://nodejs.org:80/file",
        "https://nodejs.org/file#fragment",
    ],
)
def test_public_acquisition_rejects_nonpublic_origins_before_dns_or_network(monkeypatch, url):
    monkeypatch.setattr(
        producer.socket, "getaddrinfo", lambda *a, **k: pytest.fail("unexpected DNS")
    )
    with pytest.raises(producer.ProducerRefused, match="public_origin_refused"):
        producer.public_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_allowlisted_name_resolving_to_private_address_refuses(monkeypatch, address):
    monkeypatch.setattr(
        producer.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (address, 443))]
    )
    with pytest.raises(producer.ProducerRefused, match="public_address_refused"):
        producer.public_url("https://nodejs.org/file")


@pytest.mark.parametrize(
    "cdn_host", ["production.cloudflare.docker.com", "production.cloudfront.docker.com"]
)
def test_redirect_does_not_forward_public_registry_bearer_to_other_origin(monkeypatch, cdn_host):
    monkeypatch.setattr(
        producer.socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    request = Request(
        "https://registry-1.docker.io/v2/library/node/blobs/public",
        headers={"Authorization": "Bearer synthetic-public-only"},
    )
    redirected = producer.PublicRedirect().redirect_request(
        request, None, 307, "Temporary Redirect", {}, "https://" + cdn_host + "/public"
    )
    assert not redirected.has_header("Authorization")


@pytest.mark.parametrize(
    "url",
    [
        "https://production.cloudfront.docker.com.evil.test/public",
        "http://production.cloudfront.docker.com/public",
        "https://synthetic@production.cloudfront.docker.com/public",
        "https://production.cloudfront.docker.com:80/public",
    ],
)
def test_registry_redirect_rejects_unknown_or_unsafe_destination_before_dns(monkeypatch, url):
    monkeypatch.setattr(
        producer.socket, "getaddrinfo", lambda *a, **k: pytest.fail("unexpected DNS")
    )
    request = Request(
        "https://registry-1.docker.io/v2/library/node/blobs/public",
        headers={"Authorization": "Bearer synthetic-public-only"},
    )
    with pytest.raises(producer.ProducerRefused, match="public_origin_refused"):
        producer.PublicRedirect().redirect_request(
            request, None, 307, "Temporary Redirect", {}, url
        )


def test_exact_official_cdn_redirect_still_refuses_private_dns(monkeypatch):
    monkeypatch.setattr(
        producer.socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("10.0.0.1", 443))],
    )
    request = Request(
        "https://registry-1.docker.io/v2/library/node/blobs/public",
        headers={"Authorization": "Bearer synthetic-public-only"},
    )
    with pytest.raises(producer.ProducerRefused, match="public_address_refused"):
        producer.PublicRedirect().redirect_request(
            request,
            None,
            307,
            "Temporary Redirect",
            {},
            "https://production.cloudfront.docker.com/public",
        )


def test_new_output_never_overwrites_existing_or_symlink_target(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "preserve").write_bytes(b"original")
    with pytest.raises(producer.ProducerRefused):
        producer.new_directory(existing)
    alias = tmp_path / "alias"
    alias.symlink_to(existing)
    with pytest.raises(producer.ProducerRefused):
        producer.new_directory(alias)
    assert (existing / "preserve").read_bytes() == b"original"


def test_offline_store_refuses_symlinks_special_members_and_missing_path(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "v10/files").mkdir(parents=True)
    (store / "v10/index").mkdir()
    (store / "v10/files/public").write_bytes(b"known")
    producer.require_offline_store(store)
    (store / "alias").symlink_to(tmp_path / "not-read")
    with pytest.raises(producer.ProducerRefused, match="unsafe_public_store"):
        producer.require_offline_store(store)
    with pytest.raises(producer.ProducerRefused, match="explicit_public_store_required"):
        producer.require_offline_store(tmp_path / "absent")


def test_offline_store_copy_omits_only_public_tracking_metadata_without_reading_links(
    tmp_path, monkeypatch
):
    store = tmp_path / "store"
    (store / "v10/files").mkdir(parents=True)
    (store / "v10/index").mkdir()
    (store / "v10/projects").mkdir()
    (store / "v10/files/public").write_bytes(b"verified-package-bytes")
    (store / "v10/files/public").chmod(0o755)
    (store / "v10/index/package.json").write_bytes(b"public-index")
    link = store / "v10/projects" / ("a" * 32)
    link.symlink_to("/unrelated/must-never-read")
    original = producer.os.readlink

    def readlink(path, *args, **kwargs):
        if Path(path) == link:
            pytest.fail("tracking symlink target read")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(producer.os, "readlink", readlink)
    copied = tmp_path / "copied"
    producer.require_offline_store(store, copy_to=copied)
    assert (copied / "v10/files/public").read_bytes() == b"verified-package-bytes"
    assert (copied / "v10/index/package.json").read_bytes() == b"public-index"
    assert (copied / "v10/files/public").stat().st_mode & 0o777 == 0o700
    assert (copied / "v10/index/package.json").stat().st_mode & 0o777 == 0o600
    assert not (copied / "v10/projects").exists()
    assert link.is_symlink()


@pytest.mark.parametrize(
    "kind",
    [
        "tracking_name",
        "tracking_regular",
        "tracking_directory",
        "dependency_link",
        "index_link",
        "unknown_root",
        "hardlink",
        "writable",
    ],
)
def test_store_metadata_exception_never_admits_unknown_links_or_unsafe_dependencies(tmp_path, kind):
    store = tmp_path / "store"
    (store / "v10/files").mkdir(parents=True)
    (store / "v10/index").mkdir()
    (store / "v10/projects").mkdir()
    public = store / "v10/files/public"
    public.write_bytes(b"public")
    tracking = store / "v10/projects" / ("b" * 32)
    if kind == "tracking_name":
        (store / "v10/projects/unknown").symlink_to("not-read")
    elif kind == "tracking_regular":
        tracking.write_bytes(b"not-metadata")
    elif kind == "tracking_directory":
        tracking.mkdir()
    elif kind == "dependency_link":
        public.unlink()
        public.symlink_to("not-read")
    elif kind == "index_link":
        (store / "v10/index/link").symlink_to("not-read")
    elif kind == "unknown_root":
        (store / "unknown").mkdir()
    elif kind == "hardlink":
        os.link(public, tmp_path / "unrelated")
    else:
        public.chmod(0o666)
    with pytest.raises(producer.ProducerRefused):
        producer.require_offline_store(store, copy_to=tmp_path / "copied")


def test_default_assembler_has_no_silent_registry_fallback_or_output(tmp_path):
    destination = tmp_path / "new"
    with pytest.raises(producer.ProducerRefused, match="explicit_public_store_required"):
        producer.assemble({}, {}, tmp_path, destination)
    assert not destination.exists()


def test_low_storage_refuses_before_build_output(tmp_path, monkeypatch):
    monkeypatch.setattr(
        producer.os,
        "statvfs",
        lambda path: SimpleNamespace(f_bavail=10, f_frsize=1024, f_blocks=100),
    )
    with pytest.raises(producer.ProducerRefused, match="insufficient_build_headroom"):
        producer.assemble(
            {"bundle": {"regular_bytes": 1}}, {}, tmp_path, tmp_path / "new", offline_store=tmp_path
        )
    assert not (tmp_path / "new").exists()


def test_canonical_archive_repeats_exact_bytes_across_paths_times_and_creation_order(tmp_path):
    archives = []
    for number in range(2):
        root = tmp_path / str(number)
        root.mkdir()
        component = root / "node"
        component.mkdir()
        names = ["a", "b"] if number == 0 else ["b", "a"]
        for name in names:
            (component / name).write_bytes(name.encode())
            (component / name).chmod(0o444)
            os.utime(component / name, (number + 100, number + 100))
        (component / "link").symlink_to("a")
        component.chmod(0o555)
        root.chmod(0o555)
        records, _ = producer.verifier().scan_tree(root)
        output = tmp_path / (str(number) + ".tar.xz")
        producer.canonical_archive(root, output, records)
        archives.append(output.read_bytes())
    assert archives[0] == archives[1]
    with tarfile.open(fileobj=io.BytesIO(archives[0])) as packed:
        assert [row.name for row in packed] == ["node", "node/a", "node/b", "node/link"]
        assert all(
            row.uid == row.gid == row.mtime == 0 and row.uname == row.gname == ""
            for row in packed.getmembers()
        )


def test_private_build_environment_does_not_inherit_host_values(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_TOKEN", "never-transfer")
    environment = producer.build_environment(tmp_path, tmp_path / "bundle")
    assert "SYNTHETIC_TOKEN" not in environment
    assert environment["HOME"] == str(tmp_path / "home")
    assert environment["NPM_CONFIG_GLOBALCONFIG"] == "/dev/null"
    assert environment["PIP_CONFIG_FILE"] == "/dev/null"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert (tmp_path / "pnpm-workspace.yaml").exists()
    assert (tmp_path / "core.npmrc").read_text() == producer.CONFIG


def test_package_tool_output_and_deadline_are_bounded_and_child_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(producer, "MAX_OUTPUT", 16)
    with pytest.raises(producer.ProducerRefused, match="public_tool_output_budget"):
        producer.command([sys.executable, "-c", "print('x' * 32)"], tmp_path, {})
    with pytest.raises(producer.ProducerRefused, match="public_tool_timeout"):
        producer.command(
            [sys.executable, "-c", "import time; time.sleep(1)"], tmp_path, {}, timeout=0.02
        )
    assert producer.command([sys.executable, "-c", "print('done')"], tmp_path, {}) == b"done\n"


def test_exact_pinned_inputs_include_all_selected_graph_and_source_chain():
    pin = json.loads(producer.PIN_PATH.read_text())
    rows = producer.input_specifications(pin)
    assert sum(name.startswith("npm/") for name, *_ in rows) == 17
    assert sum(name.startswith("wheels/") for name, *_ in rows) == 24
    assert sum(name.startswith("oci/") for name, *_ in rows) == 7
    assert hashlib.sha256(producer.PIN_PATH.read_bytes()).hexdigest() == producer.PIN_SHA256
    assert producer.verifier().load_pin()["toolchain_id"] == "miy-native-sdk-20261009-v2"
    assert producer.verifier().load_pin()["runtime_scratch"]["bytes"] == 16777216


def test_pinned_oci_source_repository_matches_every_public_manifest_and_blob_namespace():
    pin = json.loads(producer.PIN_PATH.read_text())
    assert producer.oci_repository(pin) == "library/node"
    rows = [row for row in producer.input_specifications(pin) if row[0].startswith("oci/")]
    assert len(rows) == 7
    assert all(row[3].startswith("https://registry-1.docker.io/v2/library/node/") for row in rows)
    assert all("library/python" not in row[3] for row in rows)


@pytest.mark.parametrize(
    "repository", [None, "library/python", "untrusted/custom", "../node", "library/node:latest"]
)
def test_unknown_or_missing_public_oci_repository_refuses_before_network(repository, monkeypatch):
    pin = json.loads(producer.PIN_PATH.read_text())
    pin["provenance"]["OCI_selected_runtime"]["supplier"]["repository"] = repository
    monkeypatch.setattr(producer, "fetch", lambda *a, **k: pytest.fail("unexpected network"))
    with pytest.raises(producer.ProducerRefused, match="unsupported_public_oci_repository"):
        producer.input_specifications(pin)


def python_metadata(root, script_bytes):
    scripts = root / "bin"
    scripts.mkdir(parents=True)
    (scripts / "cli").write_bytes(script_bytes)
    metadata = root / "example-1.dist-info"
    metadata.mkdir()
    (metadata / "entry_points.txt").write_text("[console_scripts]\ncli = example:main\n")
    rows = [
        [
            "../../bin/cli",
            "sha256=" + hashlib.sha256(script_bytes).hexdigest(),
            str(len(script_bytes)),
        ],
        ["example/data,with-comma.txt", "sha256=retained", "4"],
        ["example-1.dist-info/RECORD", "", ""],
    ]
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerows(rows)
    (metadata / "RECORD").write_bytes(output.getvalue().encode())
    return metadata / "RECORD"


def test_console_record_normalization_is_standard_csv_and_path_independent(tmp_path):
    records = []
    for number in range(2):
        packages = tmp_path / str(number)
        record = python_metadata(packages, f"#!/public-build-{number}/python\n".encode())
        producer.omit_python_console_scripts(packages)
        assert not (packages / "bin").exists()
        records.append(record.read_bytes())
    assert records[0] == records[1]
    assert list(csv.reader(io.StringIO(records[0].decode(), newline=""))) == [
        ["example/data,with-comma.txt", "sha256=retained", "4"],
        ["example-1.dist-info/RECORD", "", ""],
    ]
    assert b'"example/data,with-comma.txt"' in records[0]
    assert records[0].endswith(b"\r\n")


@pytest.mark.parametrize(
    "kind", ["escape", "unknown", "missing", "duplicate", "malformed", "symlink"]
)
def test_console_normalization_refuses_unrecognized_rows_without_removing_scripts(tmp_path, kind):
    record = python_metadata(tmp_path, b"#!public\n")
    if kind == "escape":
        record.write_bytes(record.read_bytes() + b"../../outside,data,4\r\n")
    elif kind == "unknown":
        (tmp_path / "bin/unregistered").write_bytes(b"unused")
    elif kind == "missing":
        (tmp_path / "bin/cli").unlink()
    elif kind == "duplicate":
        record.write_bytes(record.read_bytes() + b"example-1.dist-info/RECORD,,\r\n")
    elif kind == "malformed":
        record.write_bytes(record.read_bytes() + b'"unterminated\r\n')
    else:
        (tmp_path / "bin/cli").unlink()
        (tmp_path / "bin/cli").symlink_to("not-read")
    before = record.read_bytes()
    with pytest.raises(producer.ProducerRefused):
        producer.omit_python_console_scripts(tmp_path)
    assert (tmp_path / "bin").is_dir()
    assert record.read_bytes() == before


def test_vite_scratch_reserves_only_one_new_empty_directory(tmp_path):
    producer.reserve_vite_scratch(tmp_path)
    assert (tmp_path / ".vite-temp").is_dir()
    assert list((tmp_path / ".vite-temp").iterdir()) == []
    with pytest.raises(producer.ProducerRefused, match="vite_scratch_target_already_exists"):
        producer.reserve_vite_scratch(tmp_path)


@pytest.mark.parametrize("kind", ["file", "populated", "symlink"])
def test_vite_scratch_does_not_hide_existing_bytes_or_links(tmp_path, kind):
    target = tmp_path / ".vite-temp"
    if kind == "file":
        target.write_bytes(b"existing")
    elif kind == "populated":
        target.mkdir()
        (target / "existing").write_bytes(b"existing")
    else:
        target.symlink_to("missing")
    with pytest.raises(producer.ProducerRefused, match="vite_scratch_target_already_exists"):
        producer.reserve_vite_scratch(tmp_path)


def source_mounts(root):
    (root / ".git").mkdir()
    (root / "node_modules").mkdir()
    producer.copy_sdk(root / "vendor/miy-app-sdk")
    (root / "package.json").write_text('{"scripts":{"build":"app-owned"}}')
    return json.loads(producer.PIN_PATH.read_text())


def canonical_source_mounts(root, template, monkeypatch):
    """Use the public app renderer itself, without injecting a vendor README."""
    monkeypatch.syspath_prepend(str(ROOT / "apps/api/src"))
    renderer = runpy.run_path(str(ROOT / "scripts/independent-app-env.py"))
    renderer["scaffold"](
        root,
        app_id="sdk-canonical-source",
        name="Synthetic SDK source",
        repository="https://example.test/synthetic-app.git",
        template=template,
    )
    (root / ".git").mkdir()
    (root / "node_modules").mkdir()
    return json.loads(producer.PIN_PATH.read_text())


@pytest.mark.parametrize("template", ["basic", "private-notes"])
def test_canonical_starter_source_preflight_accepts_four_functional_sdk_files(
    tmp_path, template, monkeypatch
):
    source = tmp_path / "canonical"
    pin = canonical_source_mounts(source, template, monkeypatch)
    vendor = source / "vendor/miy-app-sdk"
    assert {
        path.relative_to(vendor).as_posix() for path in vendor.rglob("*") if path.is_file()
    } == {
        "package.json",
        "src/index.mjs",
        "src/file-picker.mjs",
        "src/index.test.mjs",
    }
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert len(before) == 19
    producer.verifier().verify_source_mounts(source, pin)
    after = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert list((source / "node_modules").iterdir()) == []
    assert not (vendor / "README.md").exists()


def test_canonical_source_optional_sdk_readme_must_match_pin_without_source_changes(
    tmp_path, monkeypatch
):
    source = tmp_path / "canonical"
    pin = canonical_source_mounts(source, "basic", monkeypatch)
    readme = source / "vendor/miy-app-sdk/README.md"
    expected = (ROOT / "packages/app-sdk/README.md").read_bytes()
    readme.write_bytes(expected)
    producer.verifier().verify_source_mounts(source, pin)
    assert readme.read_bytes() == expected
    readme.write_bytes(b"different-public-document")
    with pytest.raises(producer.verifier().ToolchainRefused, match="source_sdk_input_mismatch"):
        producer.verifier().verify_source_mounts(source, pin)
    assert readme.read_bytes() == b"different-public-document"


@pytest.mark.parametrize(
    "required", ["package.json", "src/index.mjs", "src/file-picker.mjs", "src/index.test.mjs"]
)
def test_canonical_source_missing_functional_sdk_file_is_refused(tmp_path, monkeypatch, required):
    source = tmp_path / "canonical"
    pin = canonical_source_mounts(source, "basic", monkeypatch)
    target = source / "vendor/miy-app-sdk" / required
    target.unlink()
    with pytest.raises(producer.verifier().ToolchainRefused, match="source_sdk_inventory_mismatch"):
        producer.verifier().verify_source_mounts(source, pin)
    assert not target.exists()


@pytest.mark.parametrize(
    "kind",
    [
        "optional_symlink",
        "optional_hardlink",
        "optional_group_write",
        "functional_hardlink",
        "functional_group_write",
        "functional_directory_group_write",
        "extra_root",
        "extra_src",
    ],
)
def test_canonical_source_optional_document_does_not_weaken_target_boundaries(
    tmp_path, monkeypatch, kind
):
    source = tmp_path / "canonical"
    pin = canonical_source_mounts(source, "basic", monkeypatch)
    vendor = source / "vendor/miy-app-sdk"
    readme = vendor / "README.md"
    if kind == "optional_symlink":
        readme.symlink_to(tmp_path / "must-not-read")
    elif kind == "optional_hardlink":
        original = tmp_path / "public-document"
        original.write_bytes((ROOT / "packages/app-sdk/README.md").read_bytes())
        os.link(original, readme)
    elif kind == "optional_group_write":
        readme.write_bytes((ROOT / "packages/app-sdk/README.md").read_bytes())
        readme.chmod(0o664)
    elif kind == "functional_hardlink":
        os.link(vendor / "src/index.mjs", tmp_path / "public-functional-copy")
    elif kind == "functional_group_write":
        (vendor / "src/index.mjs").chmod(0o664)
    elif kind == "functional_directory_group_write":
        (vendor / "src").chmod(0o775)
    elif kind == "extra_root":
        (vendor / "unreviewed").write_bytes(b"must-not-hide")
    else:
        (vendor / "src/unreviewed.mjs").write_bytes(b"must-not-hide")
    with pytest.raises((producer.verifier().ToolchainRefused, OSError)):
        producer.verifier().verify_source_mounts(source, pin)
    assert (source / "node_modules").is_dir()
    assert list((source / "node_modules").iterdir()) == []


def test_source_preflight_checks_public_sdk_and_empty_targets_without_changing_app(tmp_path):
    pin = source_mounts(tmp_path)
    manifest = (tmp_path / "package.json").read_bytes()
    producer.verifier().verify_source_mounts(tmp_path, pin)
    assert (tmp_path / "package.json").read_bytes() == manifest
    assert not (tmp_path / "node_modules/.vite-temp").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "dependencies",
        "module_link",
        "vendor_link",
        "sdk_changed",
        "sdk_extra",
        "sdk_link",
        "git_link",
    ],
)
def test_source_preflight_refuses_shadowing_or_mismatched_mount_targets(tmp_path, kind):
    pin = source_mounts(tmp_path)
    if kind == "dependencies":
        (tmp_path / "node_modules/existing").write_bytes(b"keep")
    elif kind == "module_link":
        (tmp_path / "node_modules").rmdir()
        (tmp_path / "node_modules").symlink_to("unrelated")
    elif kind == "vendor_link":
        (tmp_path / "vendor").rename(tmp_path / "original-vendor")
        (tmp_path / "vendor").symlink_to("original-vendor")
    elif kind == "sdk_changed":
        (tmp_path / "vendor/miy-app-sdk/package.json").write_bytes(b"app-owned")
    elif kind == "sdk_extra":
        (tmp_path / "vendor/miy-app-sdk/custom").write_bytes(b"do-not-hide")
    elif kind == "sdk_link":
        target = tmp_path / "vendor/miy-app-sdk/src/index.mjs"
        target.unlink()
        target.symlink_to("not-read")
    else:
        (tmp_path / ".git").rmdir()
        (tmp_path / ".git").symlink_to("private-not-read")
    with pytest.raises((producer.verifier().ToolchainRefused, OSError)):
        producer.verifier().verify_source_mounts(tmp_path, pin)


@pytest.mark.parametrize("kind", ["missing", "symlink", "populated", "wrong_mode", "wrong_budget"])
def test_v2_scratch_contract_refuses_invalid_even_self_consistent_inventory(kind):
    checking = producer.verifier()
    records = [{"path": "node_modules", "kind": "directory", "mode": 0o555}]
    if kind != "missing":
        records.append({"path": "node_modules/.vite-temp", "kind": "directory", "mode": 0o555})
    if kind == "symlink":
        records[-1] = {"path": "node_modules/.vite-temp", "kind": "symlink", "target": "."}
    elif kind == "populated":
        records.append(
            {"path": "node_modules/.vite-temp/existing", "kind": "directory", "mode": 0o555}
        )
    elif kind == "wrong_mode":
        records[-1]["mode"] = 0o444
    pin = {
        "toolchain_id": checking.SDK_V2,
        "runtime_scratch": dict(checking.VITE_SCRATCH),
        "bundle": checking.summary(records),
        "components": {
            name: checking.summary([r for r in records if r["path"].split("/")[0] == name])
            for name in checking.COMPONENTS
        },
    }
    if kind == "wrong_budget":
        pin["runtime_scratch"]["bytes"] *= 2
    with pytest.raises(checking.ToolchainRefused):
        checking.verify_inventory(records, pin)
