"""Fixed root broker boundaries; fake system manager, no privileged operations."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "workspace_unit_broker", ROOT / "scripts/workbench-environment-broker.py"
)
broker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(broker)


class FakeManager:
    def __init__(self, config):
        self.config = config
        self.active = False
        self.foreign = False
        self.commands = []

    def states(self, units):
        return [
            {
                "Id": name,
                "LoadState": "loaded"
                if self.foreign or (self.config["unit_root"] / name).exists()
                else "not-found",
                "ActiveState": "active" if self.active else "inactive",
                "MainPID": "123" if self.active else "0",
                "ControlPID": "0",
                "FragmentPath": str(self.config["unit_root"] / name)
                if self.foreign or (self.config["unit_root"] / name).exists()
                else "",
            }
            for name in units
        ]

    def call(self, *args):
        self.commands.append(args)
        if args[0] in {"start", "stop"}:
            self.active = args[0] == "start"
        return b""


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {
            "repository_root": self.root / "repository",
            "worktree_root": self.root / "worktrees",
            "state_root": self.root / "state",
            "unit_root": self.root / "units",
            "template_root": ROOT / "ops/codex-console/executor",
            "vendor_root": Path("/opt/miy/vendor/@openai/native"),
            "sdk_root": Path("/opt/miy/miy-native-sdk-20261011-v3"),
            "executor_uid": os.getuid(),
            "executor_gid": os.getgid(),
            "private_port": 19622,
            "host_ports": [22100, 22101],
        }
        for key in ("repository_root", "worktree_root", "state_root", "unit_root"):
            self.config[key].mkdir(mode=0o700)
        self.id = str(uuid4())
        self.source = self.config["worktree_root"] / self.id / "personal-apps/equipment"
        self.source.mkdir(parents=True, mode=0o700)
        self.snapshot = {
            "id": self.id,
            "app_id": "equipment",
            "repository_root": str(self.config["repository_root"]),
            "worktree_path": str(self.config["worktree_root"] / self.id),
            "app_directory": "personal-apps/equipment",
            "branch": "feature/equipment-check",
            "base_revision": "a" * 40,
            "source_revision": "b" * 40,
            "profile_id": "app",
        }
        self.config["template_sha256"] = {
            suffix: broker.digest(self.template(suffix).read_bytes())
            for suffix in broker.SUFFIXES
        }
        self.native = FakeManager(self.config)
        # Unit/receipt fake roots are unprivileged. The actual root-owner reader
        # is separately tested below; no root install is needed by these tests.
        self.reader = patch.object(broker, "read", side_effect=self.read_fixture)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def template(self, suffix):
        return self.config["template_root"] / (
            "miy-app-sdk-managed" + suffix + ".example"
        )

    def read_fixture(self, path, **kwargs):
        self.assertFalse(Path(path).is_symlink())
        return Path(path).read_bytes()

    def request(self, action, snapshot=None, **kwargs):
        return broker.handle(
            self.config,
            {"action": action, "snapshot": snapshot or self.snapshot, **kwargs},
            native=self.native,
        )

    def install(self, snapshot=None, port=22100):
        snapshot = snapshot or self.snapshot
        source, _, stem = broker.identity(self.config, snapshot)
        rendered = broker.render(self.config, source, stem, port, "c" * 64)
        return self.request(
            "install",
            snapshot,
            host_port=port,
            token_sha256="c" * 64,
            units={name: broker.digest(raw) for name, raw in rendered.items()},
        )

    def test_fixed_lifecycle_runs_only_owned_three_units_with_executor_uid(self):
        installed = self.install()
        self.assertEqual(len(installed["units"]), 3)
        backend = next(
            p
            for p in self.config["unit_root"].iterdir()
            if p.name.endswith(".service") and "-proxy" not in p.name
        ).read_text()
        self.assertIn("User=" + str(os.getuid()), backend)
        self.assertIn("Group=" + str(os.getgid()), backend)
        self.assertIn("PrivateNetwork=yes", backend)
        self.assertIn("ProtectHome=tmpfs", backend)
        self.assertIn("TasksMax=256\n", backend)
        self.assertIn(
            "TasksMax=64\n",
            (
                self.config["unit_root"]
                / ("miy-wb-" + self.id.replace("-", "") + "-proxy.service")
            ).read_text(),
        )
        self.assertNotIn("/.git", backend)
        self.request("start")
        with self.assertRaises(broker.Refused):
            self.request("cleanup")
        self.request("stop")
        self.request("cleanup")
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.native.active)
        for command in self.native.commands:
            self.assertIn(command[0], {"daemon-reload", "start", "stop"})
            self.assertTrue(all(name.startswith("miy-wb-") for name in command[1:]))

    def legacy_installation(self):
        self.install()
        source, _, stem = broker.identity(self.config, self.snapshot)
        rendered = broker.render(
            self.config, source, stem, 22100, "c" * 64, legacy_budget=True
        )
        for name, raw in rendered.items():
            (self.config["unit_root"] / name).write_bytes(raw)
        receipt_path = self.config["state_root"] / (stem + ".json")
        receipt = json.loads(receipt_path.read_bytes())
        receipt["units"] = {name: broker.digest(raw) for name, raw in rendered.items()}
        broker.save_receipt(receipt_path, receipt)
        return stem, receipt_path, receipt

    def upgrade(self, token_sha256="c" * 64):
        source, _, stem = broker.identity(self.config, self.snapshot)
        rendered = broker.render(self.config, source, stem, 22100, token_sha256)
        return self.request(
            "upgrade-budget",
            token_sha256=token_sha256,
            units={name: broker.digest(raw) for name, raw in rendered.items()},
        )

    def test_legacy_budget_query_stop_cleanup_allowed_but_direct_start_refused(self):
        _, receipt_path, _ = self.legacy_installation()
        original = receipt_path.read_bytes()
        commands = self.native.commands.copy()
        self.request("query")
        with self.assertRaises(broker.Refused):
            self.request("start")
        self.assertEqual(receipt_path.read_bytes(), original)
        self.assertEqual(self.native.commands, commands)
        self.request("stop")
        self.request("cleanup")
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        self.assertFalse(any(c[0] == "start" for c in self.native.commands))

    def test_explicit_budget_upgrade_preserves_binding_port_and_proxy_and_syncs_intent(
        self,
    ):
        stem, receipt_path, original = self.legacy_installation()
        proxy = {
            name: (self.config["unit_root"] / name).read_bytes()
            for name in original["units"]
            if "-proxy" in name
        }
        parent = self.config["state_root"].stat()
        synced = []
        original_fsync, original_replace = os.fsync, os.replace

        def observe_fsync(fd):
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
                parent.st_dev,
                parent.st_ino,
            ):
                synced.append(True)
            return original_fsync(fd)

        def replace_after_intent(source, target):
            if Path(target) == self.config["unit_root"] / (stem + ".service"):
                pending = json.loads(receipt_path.read_bytes())
                self.assertEqual(pending["state"], "upgrading")
                self.assertEqual(pending["units"], original["units"])
                self.assertTrue(synced)
            return original_replace(source, target)

        commands = self.native.commands.copy()
        with (
            patch.object(os, "fsync", side_effect=observe_fsync),
            patch.object(os, "replace", side_effect=replace_after_intent),
        ):
            result = self.upgrade()
        upgraded = json.loads(receipt_path.read_bytes())
        self.assertEqual(upgraded["state"], "owned")
        self.assertEqual(upgraded["binding"], original["binding"])
        self.assertEqual(upgraded["host_port"], original["host_port"])
        self.assertEqual(upgraded["budget_upgrade"]["from_units"], original["units"])
        self.assertEqual(upgraded["budget_upgrade"]["to_units"], result["units"])
        backend = self.config["unit_root"] / (stem + ".service")
        self.assertEqual(stat.S_IMODE(backend.stat().st_mode), 0o644)
        self.assertIn(b"TasksMax=256\n", backend.read_bytes())
        for name, raw in proxy.items():
            self.assertEqual((self.config["unit_root"] / name).read_bytes(), raw)
        self.assertEqual(self.native.commands[len(commands) :], [("daemon-reload",)])
        commands = self.native.commands.copy()
        original_upgraded = receipt_path.read_bytes()
        self.assertEqual(self.upgrade(), result)
        self.assertEqual(receipt_path.read_bytes(), original_upgraded)
        self.assertEqual(self.native.commands, commands)

    def test_budget_upgrade_loss_holds_and_only_exact_explicit_continuation_finishes(
        self,
    ):
        stem, receipt_path, original = self.legacy_installation()
        original_call = self.native.call

        def lose_reload(*args):
            original_call(*args)
            if args == ("daemon-reload",):
                raise broker.Refused("workspace_operation_unknown")

        with (
            patch.object(self.native, "call", side_effect=lose_reload),
            self.assertRaises(broker.Refused),
        ):
            self.upgrade()
        pending = receipt_path.read_bytes()
        self.assertEqual(json.loads(pending)["state"], "upgrading")
        commands = self.native.commands.copy()
        self.request("query")
        for action in ("start", "stop", "cleanup"):
            with self.subTest(action=action), self.assertRaises(broker.Refused):
                self.request(action)
        with self.assertRaises(broker.Refused):
            self.upgrade(token_sha256="d" * 64)
        self.assertEqual(receipt_path.read_bytes(), pending)
        self.assertEqual(self.native.commands, commands)
        backend = self.config["unit_root"] / (stem + ".service")
        trusted = backend.read_bytes()
        backend.write_bytes(trusted + b"# foreign change\n")
        for operation in (lambda: self.request("query"), self.upgrade):
            with self.assertRaises(broker.Refused):
                operation()
        self.assertEqual(receipt_path.read_bytes(), pending)
        backend.write_bytes(trusted)
        result = self.upgrade()
        self.assertEqual(
            json.loads(receipt_path.read_bytes())["units"], result["units"]
        )
        self.assertFalse(any(c[0] == "start" for c in self.native.commands))
        self.assertEqual(
            json.loads(receipt_path.read_bytes())["budget_upgrade"]["from_units"],
            original["units"],
        )

    def test_budget_upgrade_requires_original_legacy_and_exact_inactive_pid_proof(self):
        self.install()
        with self.assertRaises(broker.Refused):
            self.upgrade()
        # A fresh current unit is not an implicit migration or upgrade receipt.
        self.assertFalse(any(c[0] == "start" for c in self.native.commands))
        self.request("cleanup")
        # Use another owned workspace because cleaned identities are never adopted.
        self.id = str(uuid4())
        self.snapshot.update(
            id=self.id, worktree_path=str(self.config["worktree_root"] / self.id)
        )
        self.source = (
            Path(self.snapshot["worktree_path"]) / self.snapshot["app_directory"]
        )
        self.source.mkdir(parents=True, mode=0o700)
        _, receipt_path, _ = self.legacy_installation()
        before = receipt_path.read_bytes()
        commands = self.native.commands.copy()
        original_states = self.native.states
        for properties in (
            {"ActiveState": "active"},
            {"MainPID": "123"},
            {"MainPID": None},
            {"ControlPID": None},
        ):

            def uncertain_states(names, properties=properties):
                states = original_states(names)
                states[0].update(properties)
                return states

            with (
                self.subTest(properties=properties),
                patch.object(self.native, "states", side_effect=uncertain_states),
                self.assertRaises(broker.Refused),
            ):
                self.upgrade()
        with self.assertRaises(broker.Refused):
            self.upgrade(token_sha256="d" * 64)
        self.assertEqual(receipt_path.read_bytes(), before)
        self.assertEqual(self.native.commands, commands)

    def test_nonstandard_budget_and_old_template_are_never_new_policy(self):
        stem, receipt_path, receipt = self.legacy_installation()
        backend = self.config["unit_root"] / (stem + ".service")
        backend.write_bytes(
            backend.read_bytes().replace(b"TasksMax=64\n", b"TasksMax=128\n")
        )
        receipt["units"][backend.name] = broker.digest(backend.read_bytes())
        broker.save_receipt(receipt_path, receipt)
        for action in ("query", "start", "stop", "cleanup"):
            with self.subTest(action=action), self.assertRaises(broker.Refused):
                self.request(action)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for suffix in broker.SUFFIXES:
                raw = self.template(suffix).read_bytes()
                if suffix == ".service":
                    raw = raw.replace(b"TasksMax=256\n", b"TasksMax=64\n")
                (root / self.template(suffix).name).write_bytes(raw)
            old_config = {
                **self.config,
                "template_root": root,
                "template_sha256": {
                    suffix: broker.digest(
                        (root / self.template(suffix).name).read_bytes()
                    )
                    for suffix in broker.SUFFIXES
                },
            }
            with self.assertRaises(broker.Refused):
                broker.render(old_config, self.source, stem, 22100, "c" * 64)

    def test_real_helper_broker_budget_handoff_preserves_token_source_and_stopped_state(
        self,
    ):
        spec = importlib.util.spec_from_file_location(
            "budget_handoff_helper", ROOT / "scripts/manage-workbench-environment.py"
        )
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        state = self.root / "helper-state"
        state.mkdir(mode=0o700)
        config = {
            **self.config,
            "state_root": state,
            "system_unit_broker": Path("/usr/local/libexec/miy-workbench-environment"),
            "socket_proxyd_path": Path("/usr/lib/systemd/systemd-socket-proxyd"),
        }
        owner = self

        class Bridge(helper.SystemBroker):
            def request(self, action, **values):
                return owner.request(action, **values)

            def ready(self, units, descriptor):
                if not owner.native.active:
                    helper.refuse("workspace_operation_unknown")

        native = Bridge(config, self.snapshot)

        def action(name):
            return helper.manage(
                config,
                self.snapshot,
                name,
                native=native,
                validate=lambda config, source: None,
            )

        with patch.object(helper, "host_port", return_value=22100):
            action("prepare")
        source, _, stem = broker.identity(self.config, self.snapshot)
        journal_path = state / self.id / "journal.json"
        descriptor_path = state / self.id / "descriptor.json"
        descriptor_bytes = descriptor_path.read_bytes()
        descriptor = json.loads(descriptor_bytes)
        legacy = helper.templates(
            config,
            source,
            stem,
            22100,
            descriptor["auth_bearer_token"],
            legacy_budget=True,
        )
        original = {name: broker.digest(raw) for name, raw in legacy.items()}
        for name, raw in legacy.items():
            (self.config["unit_root"] / name).write_bytes(raw)
        journal = json.loads(journal_path.read_bytes())
        journal["units"] = original
        helper.write_private(journal_path, helper.canonical(journal))
        receipt_path = self.config["state_root"] / (stem + ".json")
        receipt = json.loads(receipt_path.read_bytes())
        receipt["units"] = original
        broker.save_receipt(receipt_path, receipt)
        action("stop")
        starts = sum(c[0] == "start" for c in self.native.commands)
        self.assertEqual(action("upgrade-budget"), {"state": "stopped"})
        self.assertEqual(descriptor_path.read_bytes(), descriptor_bytes)
        upgraded = json.loads(journal_path.read_bytes())
        privileged = json.loads(receipt_path.read_bytes())
        self.assertEqual(upgraded["units"], privileged["units"])
        self.assertEqual(upgraded["budget_upgrade"], privileged["budget_upgrade"])
        self.assertEqual(upgraded["budget_upgrade"]["from_units"], original)
        self.assertEqual(upgraded["state"], "stopped")
        self.assertEqual(sum(c[0] == "start" for c in self.native.commands), starts)
        self.assertEqual(action("resume"), {"state": "ready"})
        self.assertEqual(descriptor_path.read_bytes(), descriptor_bytes)

    def test_source_guard_allows_only_exact_executor_owned_empty_root_git_mask(self):
        path = self.source / ".git"
        path.mkdir(mode=0o755)
        broker.source_guard(self.config, self.source)
        for unsafe in (
            "nonempty",
            "writable",
            "foreign_owner",
            "file",
            "symlink",
            "nested",
        ):
            with self.subTest(unsafe=unsafe):
                if path.exists():
                    path.rmdir()
                expected_owner = self.config["executor_uid"]
                if unsafe == "nonempty":
                    path.mkdir(mode=0o755)
                    (path / "metadata").write_text("synthetic")
                elif unsafe == "writable":
                    path.mkdir(mode=0o755)
                    path.chmod(0o777)
                elif unsafe == "foreign_owner":
                    path.mkdir(mode=0o755)
                    self.config["executor_uid"] = expected_owner + 1
                elif unsafe == "file":
                    path.write_text("synthetic")
                elif unsafe == "symlink":
                    path.symlink_to(self.source, target_is_directory=True)
                else:
                    (self.source / "nested").mkdir()
                    (self.source / "nested/.git").mkdir()
                with self.assertRaises(broker.Refused):
                    broker.source_guard(self.config, self.source)
                self.config["executor_uid"] = expected_owner
                if unsafe == "nonempty":
                    (path / "metadata").unlink()
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.exists():
                    path.rmdir()
                if unsafe == "nested":
                    (self.source / "nested/.git").rmdir()
                    (self.source / "nested").rmdir()

    def test_foreign_unit_and_changed_owned_bytes_receive_no_signal(self):
        self.native.foreign = True
        with self.assertRaises(broker.Refused):
            self.install()
        self.assertEqual(self.native.commands, [])
        self.native.foreign = False
        self.install()
        path = next(self.config["unit_root"].iterdir())
        path.write_bytes(path.read_bytes() + b"# changed\n")
        before = self.native.commands.copy()
        for action in ("start", "stop", "cleanup"):
            with self.assertRaises(broker.Refused):
                self.request(action)
        self.assertEqual(before, self.native.commands)

    def test_path_private_source_and_command_injection_hold_without_units(self):
        for mutation in (
            {"app_directory": "../../foreign"},
            {"worktree_path": str(self.config["repository_root"])},
            {"app_id": "equipment%"},
            {"branch": "feature/equipment\nExecStart=/bin/false"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(broker.Refused):
                self.install({**self.snapshot, **mutation})
        for name in (".git", ".env"):
            path = self.source / name
            path.write_text("synthetic")
            with self.assertRaises(broker.Refused):
                self.install()
            path.unlink()
        self.assertEqual(self.native.commands, [])

    def test_hash_port_and_request_shape_do_not_expand_privileged_commands(self):
        for action in ("restart", "enable", "daemon-reload", "/bin/sh"):
            with self.assertRaises(broker.Refused):
                self.request(action)
        with self.assertRaises(broker.Refused):
            self.request("query", argv=["/bin/sh"])
        with self.assertRaises(broker.Refused):
            self.install(port=22222)
        with self.assertRaises(broker.Refused):
            self.request("install", host_port=22100, token_sha256="c" * 64, units={})
        self.config["template_sha256"][".service"] = "0" * 64
        with self.assertRaises(broker.Refused):
            self.install()
        self.assertEqual(self.native.commands, [])

    def test_receipt_reserves_port_and_immutable_binding_without_source_revision(self):
        self.install()
        self.request("query", {**self.snapshot, "source_revision": "d" * 40})
        with self.assertRaises(broker.Refused):
            self.request("stop", {**self.snapshot, "branch": "feature/other"})
        second = {**self.snapshot, "id": str(uuid4()), "app_id": "second"}
        second["worktree_path"] = str(self.config["worktree_root"] / second["id"])
        second["app_directory"] = "personal-apps/second"
        (Path(second["worktree_path"]) / second["app_directory"]).mkdir(
            parents=True, mode=0o700
        )
        with self.assertRaises(broker.Refused):
            self.install(second)
        self.assertEqual(len(list(self.config["state_root"].glob("*.json"))), 1)

    def test_completed_cleanup_loss_is_reconciled_by_query_without_unit_commands(self):
        self.install()
        self.request("start")
        self.request("stop")
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        before = json.loads(receipt_path.read_bytes())
        original_call = self.native.call

        def lose_cleanup_reply(*args):
            original_call(*args)
            if args == ("daemon-reload",):
                raise broker.Refused("synthetic cleanup response loss")

        with (
            patch.object(self.native, "call", side_effect=lose_cleanup_reply),
            self.assertRaises(broker.Refused),
        ):
            self.request("cleanup")
        pending = json.loads(receipt_path.read_bytes())
        self.assertEqual(pending["state"], "cleaning")
        self.assertEqual(pending["binding"], before["binding"])
        self.assertEqual(pending["units"], before["units"])
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        commands = self.native.commands.copy()
        observed = self.request("query")
        self.assertTrue(all(s["LoadState"] == "not-found" for s in observed["states"]))
        self.assertEqual(json.loads(receipt_path.read_bytes())["state"], "cleaned")
        self.assertEqual(self.native.commands, commands)
        self.assertTrue(self.source.is_dir())
        self.assertEqual(self.request("query"), observed)
        for action in ("start", "stop", "cleanup"):
            with self.assertRaises(broker.Refused):
                self.request(action)
        self.assertEqual(self.native.commands, commands)

    def test_partial_cleanup_keeps_durable_intent_and_holds_without_replay(self):
        self.install()
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        original_unlink = Path.unlink
        deleted = []

        def interrupt_partial_delete(path, *args, **kwargs):
            if path.parent == self.config["unit_root"]:
                self.assertEqual(
                    json.loads(receipt_path.read_bytes())["state"], "cleaning"
                )
                if deleted:
                    raise OSError("synthetic partial cleanup interruption")
                deleted.append(path.name)
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(Path, "unlink", new=interrupt_partial_delete),
            self.assertRaises(OSError),
        ):
            self.request("cleanup")
        self.assertEqual(len(deleted), 1)
        self.assertEqual(len(list(self.config["unit_root"].iterdir())), 2)
        before = receipt_path.read_bytes()
        commands = self.native.commands.copy()
        for action in ("query", "start", "stop", "cleanup"):
            with self.assertRaises(broker.Refused):
                self.request(action)
        self.assertEqual(receipt_path.read_bytes(), before)
        self.assertEqual(self.native.commands, commands)
        self.assertTrue(self.source.is_dir())

    def test_cleanup_syncs_private_receipt_parent_before_first_unit_removal(self):
        self.install()
        parent = self.config["state_root"].stat()
        synced_parent = []
        original_fsync, original_unlink = os.fsync, Path.unlink

        def track_fsync(fd):
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
                parent.st_dev,
                parent.st_ino,
            ):
                synced_parent.append(True)
            return original_fsync(fd)

        def check_intent_before_unlink(path, *args, **kwargs):
            if path.parent == self.config["unit_root"]:
                self.assertTrue(synced_parent)
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(os, "fsync", side_effect=track_fsync),
            patch.object(Path, "unlink", new=check_intent_before_unlink),
        ):
            self.request("cleanup")
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)

    def test_unit_absence_without_cleanup_intent_is_not_adopted(self):
        self.install()
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        before = receipt_path.read_bytes()
        for path in self.config["unit_root"].iterdir():
            path.unlink()
        commands = self.native.commands.copy()
        with self.assertRaises(broker.Refused):
            self.request("query")
        self.assertEqual(receipt_path.read_bytes(), before)
        self.assertEqual(self.native.commands, commands)

    def test_cleanup_observation_holds_foreign_or_live_units_and_changed_binding(self):
        self.install()
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        receipt = json.loads(receipt_path.read_bytes())
        receipt["state"] = "cleaning"
        receipt_path.write_bytes(broker.canonical(receipt))
        for path in self.config["unit_root"].iterdir():
            path.unlink()
        before = receipt_path.read_bytes()
        commands = self.native.commands.copy()
        unit = self.config["unit_root"] / next(iter(receipt["units"]))
        with self.subTest(boundary="foreign bytes"):
            unit.write_bytes(b"foreign unit bytes\n")
            with self.assertRaises(broker.Refused):
                self.request("query")
            unit.unlink()
        with self.subTest(boundary="broken symlink"):
            unit.symlink_to(self.root / "absent-foreign-unit")
            with self.assertRaises(broker.Refused):
                self.request("query")
            unit.unlink()
        with self.subTest(boundary="live unit"):
            self.native.active = True
            with self.assertRaises(broker.Refused):
                self.request("query")
            self.native.active = False
        states = self.native.states(list(receipt["units"]))
        states[0]["ControlPID"] = "321"
        with (
            self.subTest(boundary="control process"),
            patch.object(self.native, "states", return_value=states),
            self.assertRaises(broker.Refused),
        ):
            self.request("query")
        states = self.native.states(list(receipt["units"]))
        states[0]["LoadState"] = "loaded"
        with (
            self.subTest(boundary="loaded unit cache"),
            patch.object(self.native, "states", return_value=states),
            self.assertRaises(broker.Refused),
        ):
            self.request("query")
        with (
            self.subTest(boundary="changed binding"),
            self.assertRaises(broker.Refused),
        ):
            self.request("query", {**self.snapshot, "branch": "feature/foreign"})
        self.assertEqual(receipt_path.read_bytes(), before)
        self.assertEqual(self.native.commands, commands)
        self.assertTrue(self.source.is_dir())

    def test_cleanup_absence_requires_service_pid_but_allows_socket_without_main_pid(
        self,
    ):
        self.install()
        _, _, stem = broker.identity(self.config, self.snapshot)
        receipt_path = self.config["state_root"] / (stem + ".json")
        receipt = json.loads(receipt_path.read_bytes())
        receipt["state"] = "cleaning"
        receipt_path.write_bytes(broker.canonical(receipt))
        for path in self.config["unit_root"].iterdir():
            path.unlink()
        before = receipt_path.read_bytes()
        commands = self.native.commands.copy()
        states = self.native.states(list(receipt["units"]))
        service = next(s for s in states if s["Id"].endswith(".service"))
        del service["MainPID"]
        with (
            patch.object(self.native, "states", return_value=states),
            self.assertRaises(broker.Refused),
        ):
            self.request("query")
        self.assertEqual(receipt_path.read_bytes(), before)
        service["MainPID"] = "0"
        socket = next(s for s in states if s["Id"].endswith(".socket"))
        del socket["MainPID"]
        with patch.object(self.native, "states", return_value=states):
            self.request("query")
        self.assertEqual(json.loads(receipt_path.read_bytes())["state"], "cleaned")
        self.assertEqual(self.native.commands, commands)

    def test_actual_root_reader_refuses_user_owned_or_symlinked_input(self):
        self.reader.stop()
        path = self.root / "private.json"
        path.write_text(json.dumps({"synthetic": True}))
        path.chmod(0o600)
        if os.getuid() != 0:
            with self.assertRaises(broker.Refused):
                broker.read(path, private=True)
        link = self.root / "link"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            broker.read(link)


if __name__ == "__main__":
    unittest.main()
