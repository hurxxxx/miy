"""Managed unit ownership/unknown-result boundaries; no service or network calls."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "workbench_environment", ROOT / "scripts/manage-workbench-environment.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class FakeNative:
    def __init__(self, config):
        self.config = config
        self.commands = []
        self.loaded = False
        self.active = False
        self.fail_ready = False
        self.foreign = False

    def states(self, units):
        states = [
            {
                "Id": name,
                "LoadState": "loaded" if self.loaded or self.foreign else "not-found",
                "ActiveState": "active" if self.active else "inactive",
                "MainPID": "123" if self.active else "0",
                "ControlPID": "0",
                "FragmentPath": str(self.config["unit_root"] / name)
                if self.loaded or self.foreign
                else "",
            }
            for name in units
        ]
        for item in states:
            if item["Id"].endswith(".socket"):
                item.pop("MainPID")
        return states

    def require(self, *args):
        self.commands.append(args)
        if args[0] == "start":
            self.loaded = self.active = True
        elif args[0] == "stop":
            self.active = False
        elif args[0] == "daemon-reload" and not list(self.config["unit_root"].iterdir()):
            self.loaded = False

    def inactive(self, units):
        return not self.active

    def ready(self, units, descriptor):
        if self.fail_ready or not self.active:
            helper.refuse("workspace_operation_unknown")


class ManagedEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.config = {
            "repository_root": self.root / "repository",
            "worktree_root": self.root / "worktrees",
            "state_root": self.root / "state",
            "unit_root": self.root / "units",
            "vendor_root": self.root / "vendor",
            "sdk_root": self.root / "sdk",
            "executor_uid": os.getuid(),
            "executor_gid": os.getgid(),
            "host_ports": [22345, 22346],
            "private_port": 19622,
            "socket_proxyd_path": Path("/usr/lib/systemd/systemd-socket-proxyd"),
        }
        for key in (
            "repository_root",
            "worktree_root",
            "state_root",
            "unit_root",
            "vendor_root",
            "sdk_root",
        ):
            self.config[key].mkdir(mode=0o700)
        self.identity = str(uuid4())
        worktree = self.config["worktree_root"] / self.identity
        self.source = worktree / "personal-apps/equipment"
        self.source.mkdir(parents=True, mode=0o700)
        self.snapshot = {
            "id": self.identity,
            "app_id": "equipment",
            "repository_root": str(self.config["repository_root"]),
            "worktree_path": str(worktree),
            "app_directory": "personal-apps/equipment",
            "branch": "feature/wb-equipment-test",
            "base_revision": "a" * 40,
            "source_revision": "b" * 40,
            "profile_id": "app",
        }
        self.native = FakeNative(self.config)
        self.port = patch.object(helper, "host_port", return_value=22345)
        self.port.start()
        self.addCleanup(self.port.stop)
        self.validations = []

    def validate(self, config, source):
        self.validations.append(source)

    def action(self, action, snapshot=None):
        return helper.manage(
            self.config,
            snapshot or self.snapshot,
            action,
            native=self.native,
            validate=self.validate,
        )

    def private(self, name):
        return self.config["state_root"] / self.identity / name

    def main_result(self, action):
        output = io.StringIO()
        with (
            patch.object(helper, "load_config", return_value=self.config),
            patch.object(
                helper.sys,
                "argv",
                ["managed-environment", "--config", "unused", action],
            ),
            patch.object(
                helper.sys,
                "stdin",
                SimpleNamespace(buffer=io.BytesIO(helper.canonical(self.snapshot))),
            ),
            redirect_stdout(output),
        ):
            result = helper.main()
        return result, json.loads(output.getvalue())

    def held_lock(self):
        fd = os.open(self.config["state_root"] / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd

    def test_main_describe_waits_for_real_exclusive_lock_then_manages_once(self):
        holder = self.held_lock()
        release = threading.Timer(0.2, fcntl.flock, args=(holder, fcntl.LOCK_UN))
        release.start()
        self.addCleanup(release.join)

        def manage_once(config, snapshot, action):
            # It remains an exclusive lock after waiting, not a shared bypass.
            with self.assertRaises(BlockingIOError):
                fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return {"state": "ready"}

        began = time.monotonic()
        with patch.object(helper, "manage", side_effect=manage_once) as manage:
            self.assertEqual(self.main_result("describe"), (0, {"state": "ready"}))
            manage.assert_called_once_with(self.config, self.snapshot, "describe")
        self.assertGreaterEqual(time.monotonic() - began, 0.15)

    def test_main_describe_real_contention_expires_without_running_manage(self):
        self.held_lock()
        began = time.monotonic()
        with patch.object(helper, "manage") as manage:
            self.assertEqual(
                self.main_result("describe"),
                (1, {"state": "error", "failure_code": "workspace_busy"}),
            )
            manage.assert_not_called()
        duration = time.monotonic() - began
        self.assertGreaterEqual(duration, 2.9)
        self.assertLess(duration, 4)

    def test_main_non_describe_contention_refuses_immediately_without_manage(self):
        self.held_lock()
        for action in ("prepare", "resume", "stop", "cleanup", "status"):
            with self.subTest(action=action), patch.object(helper, "manage") as manage:
                began = time.monotonic()
                self.assertEqual(
                    self.main_result(action),
                    (1, {"state": "error", "failure_code": "workspace_busy"}),
                )
                self.assertLess(time.monotonic() - began, 0.5)
                manage.assert_not_called()

    def test_main_describe_rejects_unsafe_lock_before_waiting_or_manage(self):
        self.held_lock()
        (self.config["state_root"] / ".lock").chmod(0o666)
        with (
            patch.object(helper, "acquire_lock") as acquire,
            patch.object(helper, "manage") as manage,
        ):
            self.assertEqual(
                self.main_result("describe"),
                (
                    1,
                    {
                        "state": "error",
                        "failure_code": "workspace_environment_unavailable",
                    },
                ),
            )
            acquire.assert_not_called()
            manage.assert_not_called()

    def test_prepare_describe_stop_resume_and_cleanup_preserve_token_and_source(self):
        self.assertEqual(self.action("prepare"), {"state": "ready"})
        descriptor = self.action("describe")
        token = descriptor["auth_bearer_token"]
        self.assertEqual(descriptor["source_root"], str(self.source))
        self.assertEqual(descriptor["toolchain_profile"], helper.PROFILE)
        self.assertEqual(self.private("descriptor.json").stat().st_mode & 0o777, 0o600)
        public_result = self.action("stop")
        self.assertEqual(public_result, {"state": "stopped"})
        self.assertNotIn(token, json.dumps(public_result))
        self.assertTrue(self.source.is_dir())
        self.assertEqual(self.action("resume"), {"state": "ready"})
        self.assertEqual(self.action("describe")["auth_bearer_token"], token)
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.private("descriptor.json").exists())
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        stop = next(command for command in self.native.commands if command[0] == "stop")
        self.assertTrue(stop[1].endswith("-proxy.socket"))
        self.assertTrue(stop[-1].endswith(".service"))

    def test_only_describe_emits_capability_and_declared_units_mount_only_app(self):
        self.assertNotIn("auth_bearer_token", self.action("prepare"))
        descriptor = self.action("describe")
        token = descriptor["auth_bearer_token"]
        units = list(self.config["unit_root"].iterdir())
        self.assertEqual(len(units), 3)
        backend = next(
            path for path in units if path.name.endswith(".service") and "-proxy" not in path.name
        ).read_text()
        self.assertIn("--bind " + str(self.source) + " " + str(self.source), backend)
        self.assertNotIn(str(self.config["repository_root"]), backend)
        self.assertNotIn(str(self.config["worktree_root"] / self.identity) + "/.git", backend)
        self.assertNotIn("/.git", backend)
        self.assertNotIn(token, "".join(path.read_text() for path in units))
        self.assertIn(hashlib.sha256(token.encode()).hexdigest(), backend)
        for requirement in (
            "PrivateNetwork=yes",
            "ProtectHome=tmpfs",
            "--clearenv",
            "--die-with-parent",
            "--cap-drop ALL",
            "--ro-bind",
            "TasksMax=256",
        ):
            self.assertIn(requirement, backend)
        self.assertNotIn("User=", backend)
        self.assertNotIn("Group=", backend)
        proxy = next(path for path in units if path.name.endswith("-proxy.service")).read_text()
        self.assertIn("TasksMax=64", proxy)

    def legacy_environment(self):
        self.action("prepare")
        journal_path = self.private("journal.json")
        journal = helper.read_json(journal_path)
        descriptor = helper.read_json(self.private("descriptor.json"))
        stem = "miy-wb-" + self.identity.replace("-", "")
        legacy = helper.templates(
            self.config,
            self.source,
            stem,
            journal["host_port"],
            descriptor["auth_bearer_token"],
            legacy_budget=True,
        )
        for name, raw in legacy.items():
            helper.write_private(self.config["unit_root"] / name, raw, private_parent=False)
        journal["units"] = {name: helper.sha(raw) for name, raw in legacy.items()}
        helper.write_private(journal_path, helper.canonical(journal))
        return journal

    def test_legacy_budget_observation_and_cleanup_never_prepare_or_resume_it(self):
        self.legacy_environment()
        descriptor = self.private("descriptor.json").read_bytes()
        journal = self.private("journal.json").read_bytes()
        commands = self.native.commands.copy()
        self.assertEqual(self.action("status"), {"state": "ready"})
        self.assertEqual(self.action("describe"), json.loads(descriptor))
        self.assertEqual(self.private("journal.json").read_bytes(), journal)
        for action in ("prepare", "resume", "upgrade-budget"):
            with self.subTest(action=action), self.assertRaises(helper.Refused):
                self.action(action)
        self.assertEqual(self.native.commands, commands)
        self.assertEqual(self.private("descriptor.json").read_bytes(), descriptor)
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        self.assertTrue(self.source.is_dir())
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        self.assertEqual(sum(c[0] == "start" for c in self.native.commands), 1)

    def test_explicit_stopped_budget_upgrade_preserves_identity_and_allows_later_resume(
        self,
    ):
        original = self.legacy_environment()
        descriptor = self.private("descriptor.json").read_bytes()
        proxy = {
            path.name: path.read_bytes()
            for path in self.config["unit_root"].iterdir()
            if "-proxy" in path.name
        }
        self.action("stop")
        commands = self.native.commands.copy()
        self.assertEqual(self.action("upgrade-budget"), {"state": "stopped"})
        updated = helper.read_json(self.private("journal.json"))
        for field in ("id", "binding", "host_port"):
            self.assertEqual(updated[field], original[field])
        self.assertEqual(updated["budget_upgrade"]["from_units"], original["units"])
        self.assertEqual(updated["budget_upgrade"]["to_units"], updated["units"])
        self.assertEqual(self.private("descriptor.json").read_bytes(), descriptor)
        for name, raw in proxy.items():
            self.assertEqual((self.config["unit_root"] / name).read_bytes(), raw)
        backend = next(p for p in self.config["unit_root"].iterdir() if "-proxy" not in p.name)
        self.assertIn(b"TasksMax=256\n", backend.read_bytes())
        self.assertEqual(self.native.commands[len(commands) :], [("daemon-reload",)])
        journal = self.private("journal.json").read_bytes()
        commands = self.native.commands.copy()
        self.assertEqual(self.action("upgrade-budget"), {"state": "stopped"})
        self.assertEqual(self.native.commands, commands)
        self.assertEqual(self.private("journal.json").read_bytes(), journal)
        self.assertEqual(self.action("resume"), {"state": "ready"})

    def test_budget_upgrade_active_or_missing_pid_proof_keeps_original_receipts(self):
        self.legacy_environment()
        self.action("stop")
        journal = self.private("journal.json").read_bytes()
        units = {p.name: p.read_bytes() for p in self.config["unit_root"].iterdir()}
        commands = self.native.commands.copy()
        original_states = self.native.states
        for properties in (
            {"ActiveState": "active"},
            {"MainPID": "123"},
            {"MainPID": None},
            {"ControlPID": "1"},
            {"ControlPID": None},
        ):

            def uncertain_states(names, properties=properties):
                result = original_states(names)
                result[0].update(properties)
                return result

            with (
                self.subTest(properties=properties),
                patch.object(self.native, "states", side_effect=uncertain_states),
                self.assertRaises(helper.Refused),
            ):
                self.action("upgrade-budget")
        self.assertEqual(self.private("journal.json").read_bytes(), journal)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.config["unit_root"].iterdir()}, units
        )
        self.assertEqual(self.native.commands, commands)

    def test_budget_upgrade_loss_is_held_until_same_explicit_continuation(self):
        self.legacy_environment()
        self.action("stop")
        descriptor = self.private("descriptor.json").read_bytes()
        original_require = self.native.require

        def lose_reload(*args):
            original_require(*args)
            if args == ("daemon-reload",):
                raise helper.Refused("workspace_operation_unknown")

        with (
            patch.object(self.native, "require", side_effect=lose_reload),
            self.assertRaises(helper.Refused),
        ):
            self.action("upgrade-budget")
        pending = self.private("journal.json").read_bytes()
        self.assertEqual(json.loads(pending)["state"], "upgrading")
        commands = self.native.commands.copy()
        self.assertEqual(self.action("status"), {"state": "unknown"})
        for action in ("prepare", "resume", "describe", "stop", "cleanup"):
            with self.subTest(action=action), self.assertRaises(helper.Refused):
                self.action(action)
        self.assertEqual(self.private("journal.json").read_bytes(), pending)
        self.assertEqual(self.native.commands, commands)
        self.assertEqual(self.action("upgrade-budget"), {"state": "stopped"})
        self.assertEqual(self.private("descriptor.json").read_bytes(), descriptor)
        self.assertFalse(self.native.active)
        self.assertEqual(sum(c[0] == "start" for c in self.native.commands), 1)

    def test_budget_upgrade_refuses_changed_descriptor_or_nonstandard_budget(self):
        self.legacy_environment()
        self.action("stop")
        descriptor_path = self.private("descriptor.json")
        original_descriptor = descriptor_path.read_bytes()
        descriptor = json.loads(original_descriptor)
        descriptor["auth_bearer_token"] = "x" * 64
        helper.write_private(descriptor_path, helper.canonical(descriptor))
        journal_path = self.private("journal.json")
        original_journal = journal_path.read_bytes()
        commands = self.native.commands.copy()
        with self.assertRaises(helper.Refused):
            self.action("upgrade-budget")
        self.assertEqual(journal_path.read_bytes(), original_journal)
        helper.write_private(descriptor_path, original_descriptor)
        backend = next(p for p in self.config["unit_root"].iterdir() if "-proxy" not in p.name)
        raw = backend.read_bytes().replace(b"TasksMax=64\n", b"TasksMax=128\n")
        helper.write_private(backend, raw, private_parent=False)
        journal = json.loads(original_journal)
        journal["units"][backend.name] = helper.sha(raw)
        helper.write_private(journal_path, helper.canonical(journal))
        changed = journal_path.read_bytes()
        for action in ("upgrade-budget", "resume", "cleanup"):
            with self.subTest(action=action), self.assertRaises(helper.Refused):
                self.action(action)
        self.assertEqual(journal_path.read_bytes(), changed)
        self.assertEqual(self.native.commands, commands)

    def test_snapshot_allows_only_exact_executor_owned_empty_root_git_mask(self):
        path = self.source / ".git"
        path.mkdir(mode=0o755)
        helper.snapshot_identity(self.config, self.snapshot)
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
                with self.assertRaises(helper.Refused):
                    helper.snapshot_identity(self.config, self.snapshot)
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

    def test_native_npm_vendor_scope_is_literal_without_accepting_specifier_injection(
        self,
    ):
        scoped = self.config["vendor_root"] / "node_modules/@openai/vendor"
        config = {**self.config, "vendor_root": scoped}
        stem = "miy-wb-" + self.identity.replace("-", "")
        rendered = helper.templates(config, self.source, stem, 22345, "synthetic-token")
        self.assertIn(str(scoped).encode(), rendered[stem + ".service"])
        self.assertNotIn(b"@VENDOR_ROOT@", rendered[stem + ".service"])
        for name in ("percent%", "white space", 'quote"', "line\nbreak", "@SDK_ROOT@"):
            with self.subTest(name=name), self.assertRaises(helper.Refused):
                helper.templates(
                    {**config, "vendor_root": self.config["vendor_root"] / name},
                    self.source,
                    stem,
                    22345,
                    "synthetic-token",
                )

    def test_system_broker_request_is_fixed_and_never_receives_capability_token(self):
        config = {
            **self.config,
            "system_unit_broker": Path("/usr/local/libexec/miy-workbench-environment"),
        }
        native = helper.SystemBroker(config, self.snapshot)
        token = "synthetic-secret-only-user-descriptor"
        rendered = helper.templates(
            config,
            self.source,
            "miy-wb-" + self.identity.replace("-", ""),
            22345,
            token,
        )
        hashes = {name: helper.sha(raw) for name, raw in rendered.items()}
        with patch.object(
            helper.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps({"units": hashes}).encode()
            ),
        ) as invoke:
            native.install(rendered, 22345, token)
        argv = invoke.call_args.args[0]
        self.assertEqual(
            argv,
            ["/usr/bin/sudo", "-n", "/usr/local/libexec/miy-workbench-environment"],
        )
        request = json.loads(invoke.call_args.kwargs["input"])
        self.assertNotIn(token, json.dumps(request))
        self.assertEqual(request["token_sha256"], helper.sha(token.encode()))
        self.assertEqual(request["units"], hashes)
        self.assertIn(b"User=", rendered[next(iter(rendered))])
        with self.assertRaises(helper.Refused):
            native.require("restart", "foreign.service")

    def test_changed_source_commit_keeps_binding_but_changed_branch_refuses(self):
        self.action("prepare")
        changed = {**self.snapshot, "source_revision": "c" * 40}
        self.assertEqual(self.action("describe", changed)["source_root"], str(self.source))
        with self.assertRaisesRegex(helper.Refused, "workspace_environment_changed"):
            self.action("describe", {**changed, "branch": "feature/other"})

    def test_foreign_loaded_unit_is_not_overwritten(self):
        self.native.foreign = True
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("prepare")
        self.assertEqual(self.native.commands, [])
        self.assertEqual(list(self.config["state_root"].iterdir()), [])

    def test_lost_start_is_observed_without_another_start_or_token_rotation(self):
        self.native.fail_ready = True
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("prepare")
        original = self.private("descriptor.json").read_bytes()
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("prepare")
        self.native.fail_ready = False
        self.assertEqual(self.action("describe")["source_root"], str(self.source))
        self.assertEqual(self.private("descriptor.json").read_bytes(), original)
        self.assertEqual(
            len([command for command in self.native.commands if command[0] == "start"]),
            1,
        )

    def test_modified_unit_holds_stop_and_cleanup_without_signals(self):
        self.action("prepare")
        unit = next(self.config["unit_root"].iterdir())
        unit.write_bytes(unit.read_bytes() + b"# foreign change\n")
        before = self.native.commands.copy()
        for action in ("stop", "cleanup"):
            with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
                self.action(action)
        self.assertEqual(self.native.commands, before)
        self.assertTrue(unit.exists())

    def test_path_identity_and_private_source_entries_fail_before_unit_actions(self):
        mutations = [
            {"worktree_path": str(self.config["repository_root"])},
            {"app_directory": "../.git"},
            {"repository_root": str(self.root)},
            {"profile_id": "unapproved"},
            {"id": self.identity.upper()},
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(helper.Refused):
                self.action("prepare", {**self.snapshot, **change})
        for name in (".env", ".env.production", ".git"):
            path = self.source / name
            path.write_text("synthetic")
            with self.subTest(name=name), self.assertRaises(helper.Refused):
                self.action("prepare")
            path.unlink()
        (self.source / "escape").symlink_to(self.root)
        with self.assertRaises(helper.Refused):
            self.action("prepare")
        self.assertEqual(self.native.commands, [])

    def test_stopping_receipt_requires_readonly_confirmation_before_resume(self):
        self.action("prepare")
        path = self.private("journal.json")
        journal = helper.read_json(path)
        journal["state"] = "stopping"
        helper.write_private(path, helper.canonical(journal))
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("resume")
        self.native.active = False
        with self.assertRaisesRegex(helper.Refused, "workspace_environment_unavailable"):
            self.action("describe")
        self.assertEqual(helper.read_json(path)["state"], "stopped")
        self.assertEqual(self.action("resume"), {"state": "ready"})

    def test_cleanup_after_source_removal_only_removes_owned_units(self):
        self.action("prepare")
        self.source.rmdir()
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        self.assertFalse(self.source.exists())

    def test_port_pool_uses_journal_reservations_and_never_reuses_unknown(self):
        self.port.stop()
        record = self.config["state_root"] / "another"
        record.mkdir(mode=0o700)
        helper.write_private(
            record / "journal.json",
            helper.canonical({"state": "unknown", "host_port": 22345}),
            new=True,
        )
        with patch.object(helper.socket, "socket") as network:
            connection = network.return_value.__enter__.return_value
            self.assertEqual(helper.host_port(self.config), 22346)
            connection.bind.assert_called_once_with(("127.0.0.1", 22346))
            connection.bind.side_effect = OSError("synthetic occupied")
            with self.assertRaisesRegex(helper.Refused, "workspace_environment_capacity"):
                helper.host_port(self.config)

    def test_native_stop_observation_handles_socket_without_mainpid(self):
        native = helper.Native(self.config)
        with patch.object(
            native,
            "states",
            return_value=[
                {"Id": "example.socket", "ActiveState": "inactive", "ControlPID": "0"},
                {
                    "Id": "example.service",
                    "ActiveState": "inactive",
                    "MainPID": "0",
                    "ControlPID": "0",
                },
            ],
        ):
            self.assertTrue(native.inactive(["example.socket", "example.service"]))
        with patch.object(
            native,
            "states",
            return_value=[{"Id": "example.service", "ActiveState": "inactive", "MainPID": "123"}],
        ):
            self.assertFalse(native.inactive(["example.service"]))

    def test_status_is_readonly_public_metadata_without_descriptor_read_or_token(self):
        self.assertEqual(self.action("status"), {"state": "unknown"})
        self.action("prepare")
        before = self.private("journal.json").read_bytes()
        descriptor = self.private("descriptor.json")
        descriptor.unlink()
        self.assertEqual(self.action("status"), {"state": "ready"})
        self.assertEqual(self.private("journal.json").read_bytes(), before)
        self.native.active = False
        self.assertEqual(self.action("status"), {"state": "unknown"})

    def test_waiting_stop_continues_only_after_exact_native_inactive_without_another_signal(
        self,
    ):
        self.action("prepare")
        journal = helper.read_json(self.private("journal.json"))
        journal["state"] = "stopping"
        helper.write_private(self.private("journal.json"), helper.canonical(journal))
        before = self.native.commands.copy()
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("stop")
        self.native.active = False
        self.assertEqual(self.action("status"), {"state": "stopped"})
        self.assertEqual(self.action("stop"), {"state": "stopped"})
        self.assertEqual(self.native.commands, before)

    def test_lost_stop_ack_status_persists_stopped_then_resume_starts_once(self):
        self.action("prepare")
        original = self.private("descriptor.json").read_bytes()
        writer = helper.write_private

        def lose_stopped_write(path, raw, **kwargs):
            if path == self.private("journal.json") and json.loads(raw)["state"] == "stopped":
                raise OSError("synthetic final stop acknowledgement loss")
            return writer(path, raw, **kwargs)

        with patch.object(helper, "write_private", side_effect=lose_stopped_write):
            with self.assertRaises(OSError):
                self.action("stop")
        self.assertEqual(helper.read_json(self.private("journal.json"))["state"], "stopping")
        before = self.native.commands.copy()
        self.assertEqual(self.action("status"), {"state": "stopped"})
        self.assertEqual(helper.read_json(self.private("journal.json"))["state"], "stopped")
        self.assertEqual(self.action("stop"), {"state": "stopped"})
        self.assertEqual(self.native.commands, before)
        self.assertEqual(self.action("resume"), {"state": "ready"})
        self.assertEqual(sum(command[0] == "start" for command in self.native.commands), 2)
        self.assertEqual(self.private("descriptor.json").read_bytes(), original)

    def test_lost_cleanup_final_write_status_finishes_same_cleanup_without_native_replay(
        self,
    ):
        self.action("prepare")
        writer = helper.write_private

        def lose_cleaned_write(path, raw, **kwargs):
            if path == self.private("journal.json") and json.loads(raw)["state"] == "cleaned":
                raise OSError("synthetic final cleanup acknowledgement loss")
            return writer(path, raw, **kwargs)

        with patch.object(helper, "write_private", side_effect=lose_cleaned_write):
            with self.assertRaises(OSError):
                self.action("cleanup")
        self.assertEqual(helper.read_json(self.private("journal.json"))["state"], "cleaning")
        self.assertEqual(list(self.config["unit_root"].iterdir()), [])
        self.assertFalse(self.private("descriptor.json").exists())
        # Model the native daemon-reload result without making any system calls.
        self.native.loaded = False
        before = self.native.commands.copy()
        self.assertEqual(self.action("status"), {"state": "cleaned"})
        self.assertEqual(helper.read_json(self.private("journal.json"))["state"], "cleaned")
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        self.assertEqual(self.native.commands, before)
        self.assertTrue(self.source.is_dir())

    def test_cleanup_observation_keeps_original_descriptor_until_explicit_continuation(
        self,
    ):
        self.action("prepare")
        descriptor = self.private("descriptor.json")
        original = descriptor.read_bytes()
        native_require = self.native.require

        def lose_after_reload(*args):
            native_require(*args)
            if args == ("daemon-reload",):
                raise OSError("synthetic interruption before descriptor removal")

        with patch.object(self.native, "require", side_effect=lose_after_reload):
            with self.assertRaises(OSError):
                self.action("cleanup")
        self.assertEqual(helper.read_json(self.private("journal.json"))["state"], "cleaning")
        before = self.native.commands.copy()
        self.assertEqual(self.action("status"), {"state": "cleaned"})
        self.assertEqual(descriptor.read_bytes(), original)
        self.assertEqual(self.action("stop"), {"state": "cleaned"})
        self.assertEqual(descriptor.read_bytes(), original)
        with self.assertRaisesRegex(helper.Refused, "workspace_environment_unavailable"):
            self.action("describe")
        self.assertEqual(self.action("cleanup"), {"state": "cleaned"})
        self.assertFalse(descriptor.exists())
        self.assertEqual(self.native.commands, before)

    def test_partial_cleaning_and_foreign_units_cannot_be_adopted_or_replayed(self):
        self.action("prepare")
        journal_path = self.private("journal.json")
        journal = helper.read_json(journal_path)
        journal["state"] = "cleaning"
        helper.write_private(journal_path, helper.canonical(journal))
        self.native.active = False
        units = list(self.config["unit_root"].iterdir())
        for path in units[:2]:
            path.unlink()
        before = self.native.commands.copy()
        original_journal = journal_path.read_bytes()
        self.assertEqual(self.action("status"), {"state": "unknown"})
        for action in ("cleanup", "stop", "resume", "prepare", "describe"):
            with (
                self.subTest(action=action),
                self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"),
            ):
                self.action(action)
        self.assertEqual(journal_path.read_bytes(), original_journal)
        units[2].write_bytes(b"foreign unit")
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("status")
        units[2].unlink()
        units[2].symlink_to(self.root / "missing")
        self.assertEqual(self.action("status"), {"state": "unknown"})
        changed = {**self.snapshot, "branch": "feature/different-intent"}
        with self.assertRaisesRegex(helper.Refused, "workspace_environment_changed"):
            self.action("status", changed)
        self.assertEqual(journal_path.read_bytes(), original_journal)
        self.assertEqual(self.native.commands, before)

    def test_cleaning_requires_exact_absence_and_native_zero_process_proof(self):
        self.action("prepare")
        journal_path = self.private("journal.json")
        journal = helper.read_json(journal_path)
        journal["state"] = "cleaning"
        helper.write_private(journal_path, helper.canonical(journal))
        for path in self.config["unit_root"].iterdir():
            path.unlink()
        self.native.active = False
        self.native.loaded = False
        before = self.native.commands.copy()
        original_journal = journal_path.read_bytes()
        units = list(journal["units"])
        states = self.native.states(units)
        service_index = next(i for i, item in enumerate(states) if item["Id"].endswith(".service"))
        for key, value in (
            ("LoadState", "loaded"),
            ("ActiveState", "active"),
            ("MainPID", "123"),
            ("MainPID", None),
            ("ControlPID", "123"),
        ):
            changed = [dict(item) for item in states]
            if value is None:
                changed[service_index].pop(key)
            else:
                changed[service_index][key] = value
            with (
                self.subTest(key=key, value=value),
                patch.object(self.native, "states", return_value=changed),
            ):
                self.assertEqual(self.action("status"), {"state": "unknown"})
                with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
                    self.action("cleanup")
            self.assertEqual(journal_path.read_bytes(), original_journal)
        with patch.object(self.native, "states", return_value=states[:2]):
            with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
                self.action("status")
        self.assertEqual(self.action("status"), {"state": "cleaned"})
        self.assertEqual(self.native.commands, before)

    def test_cleanup_never_deletes_foreign_or_changed_private_descriptor(self):
        self.action("prepare")
        descriptor_path = self.private("descriptor.json")
        original = descriptor_path.read_bytes()
        before = self.native.commands.copy()
        journal_path = self.private("journal.json")
        original_journal = journal_path.read_bytes()
        descriptor = json.loads(original)
        descriptor["auth_bearer_token"] = "x" * 64
        helper.write_private(descriptor_path, helper.canonical(descriptor))
        with self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"):
            self.action("cleanup")
        self.assertTrue(descriptor_path.exists())
        self.assertEqual(journal_path.read_bytes(), original_journal)
        self.assertEqual(self.native.commands, before)
        helper.write_private(descriptor_path, original)
        self.action("cleanup")
        after = self.native.commands.copy()
        # Already-cleaned remains constrained by original descriptor/unit ownership.
        helper.write_private(descriptor_path, helper.canonical(descriptor), new=True)
        for action in ("status", "cleanup", "stop"):
            with (
                self.subTest(action=action),
                self.assertRaisesRegex(helper.Refused, "workspace_operation_unknown"),
            ):
                self.action(action)
        self.assertTrue(descriptor_path.exists())
        self.assertEqual(self.native.commands, after)


class ManagedSourceVerifierTests(unittest.TestCase):
    def test_explicit_managed_source_keeps_vendor_pin_and_empty_dependencies_checks(
        self,
    ):
        verify = helper.verifier()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "node_modules").mkdir()
            sdk = source / "vendor/miy-app-sdk"
            (sdk / "src").mkdir(parents=True)
            pin = {"source_inputs": {}}
            for name in (
                "package.json",
                "src/index.mjs",
                "src/file-picker.mjs",
                "src/index.test.mjs",
            ):
                raw = (ROOT / "packages/app-sdk" / name).read_bytes()
                (sdk / name).write_bytes(raw)
                pin["source_inputs"]["packages/app-sdk/" + name] = hashlib.sha256(raw).hexdigest()
            verify.verify_source_mounts(source, pin, managed=True)
            with self.assertRaises(OSError):
                verify.verify_source_mounts(source, pin)
            (source / ".git").mkdir()
            (source / ".git/metadata").write_text("synthetic metadata")
            verify.verify_source_mounts(source, pin)
            with self.assertRaisesRegex(
                verify.ToolchainRefused, "managed_source_git_metadata_present"
            ):
                verify.verify_source_mounts(source, pin, managed=True)
            (source / ".git/metadata").unlink()
            (source / ".git").rmdir()
            (source / "node_modules/foreign").write_text("synthetic")
            with self.assertRaisesRegex(
                verify.ToolchainRefused, "source_dependencies_target_not_empty"
            ):
                verify.verify_source_mounts(source, pin, managed=True)
            (source / "node_modules/foreign").unlink()
            (sdk / "src/index.mjs").write_text("changed SDK")
            with self.assertRaisesRegex(verify.ToolchainRefused, "source_sdk_input_mismatch"):
                verify.verify_source_mounts(source, pin, managed=True)


if __name__ == "__main__":
    unittest.main()
