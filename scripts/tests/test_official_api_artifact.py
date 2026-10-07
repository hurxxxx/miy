import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "official_api_artifact", ROOT / "ops/official-suite-api/verify.py"
)
artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact)


class ArtifactInputsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "repo"
        self.source = self.root / "apps/api/src"
        self.source.mkdir(parents=True)
        self.file = self.source / "app.py"
        self.file.write_bytes(b"synthetic source\n")
        self.outside = self.parent / "outside"
        self.outside.mkdir()
        (self.outside / "app.py").write_bytes(b"synthetic external file\n")
        inputs = patch.object(artifact, "INPUTS", ("apps/api/src",))
        inputs.start()
        self.addCleanup(inputs.stop)
        location = patch.object(
            artifact, "__file__", str(self.root / "ops/official-suite-api/verify.py")
        )
        location.start()
        self.addCleanup(location.stop)

    def freeze(self, name="context.tar"):
        output = self.root / ".runtime/official-api-artifact" / name
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            artifact.context(argparse.Namespace(output=str(output)))
        return output, json.loads(captured.getvalue())

    def test_regular_snapshot_has_matching_hashes_and_preserves_existing_archive(self):
        cache = self.source / "__pycache__"
        cache.mkdir()
        (cache / "app.pyc").write_bytes(b"ignored cache")
        output, manifest = self.freeze()
        content = output.read_bytes()
        self.assertEqual(
            manifest["context_sha256"], hashlib.sha256(content).hexdigest()
        )
        entries = {
            "apps/api/src/app.py": hashlib.sha256(self.file.read_bytes()).hexdigest()
        }
        self.assertEqual(
            manifest["input_sha256"],
            hashlib.sha256(artifact.canonical(entries)).hexdigest(),
        )
        with tarfile.open(output) as archive:
            self.assertEqual(archive.getnames(), ["apps/api/src/app.py"])
            entry = archive.getmembers()[0]
            self.assertTrue(entry.isfile())
            self.assertEqual(entry.mode, 0o644)
            self.assertEqual(archive.extractfile(entry).read(), self.file.read_bytes())
        with self.assertRaises(FileExistsError):
            self.freeze()
        self.assertEqual(output.read_bytes(), content)

    def test_declared_input_ancestor_symlink_is_rejected(self):
        external_source = self.outside / "api/src"
        external_source.mkdir(parents=True)
        (external_source / "app.py").write_bytes(b"synthetic external source\n")
        (self.root / "apps").rename(self.parent / "original-apps")
        (self.root / "apps").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            artifact.input_files(self.root)

    def test_root_and_root_ancestor_symlinks_are_rejected(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        ancestor = self.parent / "ancestor"
        ancestor.symlink_to(self.parent, target_is_directory=True)
        for root in (alias, ancestor / "repo"):
            with self.subTest(root=root.name), self.assertRaises(ValueError):
                artifact.input_files(root)

    def test_links_inside_source_are_rejected(self):
        for target in (self.outside / "app.py", self.outside):
            link = self.source / "linked"
            link.symlink_to(target, target_is_directory=target.is_dir())
            with self.subTest(directory=target.is_dir()), self.assertRaises(ValueError):
                artifact.input_files(self.root)
            link.unlink()

    def test_hardlinks_are_rejected_during_inventory_and_read(self):
        linked = self.source / "linked.py"
        os.link(self.outside / "app.py", linked)
        with self.assertRaises(ValueError):
            artifact.input_files(self.root)
        with self.assertRaises(ValueError):
            artifact.read_input(self.root, linked.relative_to(self.root))

    def test_special_files_are_rejected_without_waiting_for_a_writer(self):
        special = self.source / "pipe"
        os.mkfifo(special)
        with self.assertRaises(ValueError):
            artifact.input_files(self.root)
        with self.assertRaises(ValueError):
            artifact.read_input(self.root, special.relative_to(self.root))

    def test_environment_and_auth_files_are_rejected(self):
        for name in (".env", ".env.local", ".auth_info", ".auth_info.backup"):
            blocked = self.source / name
            blocked.write_bytes(b"synthetic forbidden input")
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifact.input_files(self.root)
            with self.assertRaises(ValueError):
                artifact.read_input(self.root, blocked.relative_to(self.root))
            blocked.unlink()

    def test_inventory_does_not_authorize_later_ancestor_replacement(self):
        files = artifact.input_files(self.root)
        self.source.rename(self.source.with_name("original"))
        self.source.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            artifact.read_input(self.root, files[0].relative_to(self.root))

    def test_inventory_does_not_authorize_later_hardlink_replacement(self):
        files = artifact.input_files(self.root)
        self.file.unlink()
        os.link(self.outside / "app.py", self.file)
        with self.assertRaises(ValueError):
            artifact.read_input(self.root, files[0].relative_to(self.root))

    def test_replacement_while_reading_is_detected_without_following_new_link(self):
        original_fdopen = os.fdopen
        read_content = []

        @contextlib.contextmanager
        def replacing_stream(*args, **kwargs):
            with original_fdopen(*args, **kwargs) as stream:
                self.file.unlink()
                self.file.symlink_to(self.outside / "app.py")

                class Reader:
                    def read(self):
                        content = stream.read()
                        read_content.append(content)
                        return content

                yield Reader()

        with (
            patch.object(artifact.os, "fdopen", replacing_stream),
            self.assertRaises(ValueError),
        ):
            artifact.read_input(self.root, "apps/api/src/app.py")
        self.assertEqual(read_content, [b"synthetic source\n"])

    def test_changed_input_leaves_no_success_and_partial_archive_cannot_be_reused(self):
        original_read = artifact.read_input
        for changed_read in (2, 3):
            self.file.write_bytes(b"synthetic source\n")
            calls = 0

            def changed(root, relative, when=changed_read):
                nonlocal calls
                calls += 1
                if calls == when:
                    self.file.write_bytes(b"changed source\n")
                return original_read(root, relative)

            output = (
                self.root
                / ".runtime/official-api-artifact"
                / f"partial-{changed_read}.tar"
            )
            captured = io.StringIO()
            with (
                patch.object(artifact, "read_input", changed),
                contextlib.redirect_stdout(captured),
                self.assertRaises(ValueError),
            ):
                artifact.context(argparse.Namespace(output=str(output)))
            self.assertEqual(captured.getvalue(), "")
            partial = output.read_bytes()
            with self.assertRaises(FileExistsError):
                self.freeze(output.name)
            self.assertEqual(output.read_bytes(), partial)
            self.freeze(f"complete-{changed_read}.tar")

    def test_output_ancestor_symlink_cannot_write_outside_root(self):
        (self.root / ".runtime").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.freeze()
        self.assertEqual(
            sorted(path.name for path in self.outside.iterdir()), ["app.py"]
        )

    def test_absolute_and_parent_traversal_input_paths_are_rejected(self):
        for relative in ("../outside/app.py", str(self.outside / "app.py")):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                artifact.read_input(self.root, relative)


if __name__ == "__main__":
    unittest.main()
