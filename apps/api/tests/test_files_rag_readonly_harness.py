from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "files_rag_readonly_harness.py"
    spec = importlib.util.spec_from_file_location("test_files_rag_readonly_harness_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:test"><w:body><w:p/></w:body></w:document>',
        )


def _write_encrypted_flag_docx(path: Path) -> None:
    _write_docx(path)
    content = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while True:
            position = content.find(signature, cursor)
            if position < 0:
                break
            flags = int.from_bytes(
                content[position + flag_offset : position + flag_offset + 2], "little"
            )
            content[position + flag_offset : position + flag_offset + 2] = (flags | 0x1).to_bytes(
                2, "little"
            )
            cursor = position + len(signature)
    path.write_bytes(content)


def _write_png(path: Path) -> None:
    Image.new("RGB", (2, 2), color=(12, 34, 56)).save(path, format="PNG")


def _exclusions(manifest: dict[str, object]) -> dict[str, int]:
    inventory = manifest["inventory"]
    assert isinstance(inventory, dict)
    exclusions = inventory["exclusions"]
    assert isinstance(exclusions, list)
    return {str(item["reason"]): int(item["file_count"]) for item in exclusions}


def _source_snapshot(source: Path) -> dict[str, str]:
    return {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_manifest_output_must_be_outside_source_and_source_stays_unchanged(
    tmp_path: Path, capsys
) -> None:
    harness = _load_script_module()
    source = tmp_path / "source"
    source.mkdir()
    secret_name = "NEVER_PRINT_THIS_FILENAME.txt"
    secret_body = "NEVER PRINT THIS BODY"
    (source / secret_name).write_text(secret_body, encoding="utf-8")
    before = _source_snapshot(source)

    inside = source / "manifest.json"
    assert harness.main(["--source", str(source), "--manifest-out", str(inside)]) == 2
    error_output = capsys.readouterr().out
    assert json.loads(error_output) == {
        "status": "error",
        "code": "manifest_output_inside_source",
    }
    assert not inside.exists()

    outside = tmp_path / "manifest.json"
    assert harness.main(["--source", str(source), "--manifest-out", str(outside)]) == 0
    stdout = capsys.readouterr().out
    from_stdout = json.loads(stdout)
    from_disk = json.loads(outside.read_text(encoding="ascii"))
    assert from_stdout == from_disk
    assert secret_name not in stdout
    assert secret_body not in stdout
    assert _source_snapshot(source) == before
