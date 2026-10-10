import importlib.util
import subprocess
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drain = load("prod-app-drain")
slice_contract = load("prod-app-official-slice")


class DrainContractTests(unittest.TestCase):
    def fixture(
        self,
        *,
        consumers=None,
        depth=0,
        active=None,
        queue_error=None,
        transport="redis",
        unacked=(0, 0),
        ack_emulation=True,
    ):
        expected = {"prod-worker@owned": ("celery", "mail_sync")}
        replies = {name: [] for name in expected}
        inspection = SimpleNamespace(
            active_queues=lambda: (
                consumers
                if consumers is not None
                else {
                    "prod-worker@owned": [
                        {"name": name} for name in expected["prod-worker@owned"]
                    ]
                }
            ),
            active=lambda: active if active is not None else replies,
            reserved=lambda: replies,
            scheduled=lambda: replies,
        )
        declarations = []

        def declare(**kwargs):
            declarations.append(kwargs)
            if queue_error is not None:
                raise queue_error
            return SimpleNamespace(message_count=depth)

        pipeline = SimpleNamespace(
            hlen=lambda key: None,
            zcard=lambda key: None,
            execute=lambda: unacked,
        )
        client = SimpleNamespace(pipeline=lambda **_: nullcontext(pipeline))
        channel = SimpleNamespace(
            queue_declare=declare,
            ack_emulation=ack_emulation,
            qos=SimpleNamespace(
                unacked_key="native-owned-unacked",
                unacked_index_key="native-owned-index",
            ),
            conn_or_acquire=lambda: nullcontext(client),
        )
        connection = SimpleNamespace(
            channel=lambda: nullcontext(channel),
            transport=SimpleNamespace(driver_type=transport),
        )
        app = SimpleNamespace(
            control=SimpleNamespace(inspect=lambda **_: inspection),
            connection_for_read=lambda: nullcontext(connection),
        )
        return app, expected, declarations

    def test_exact_empty_snapshot_is_read_only(self):
        app, expected, declarations = self.fixture()
        self.assertTrue(drain.assert_empty(app, expected))
        self.assertEqual(
            declarations,
            [
                {"queue": "celery", "passive": True},
                {"queue": "mail_sync", "passive": True},
            ],
        )

    def test_queued_or_active_work_prevents_cutover(self):
        for options in (
            {"depth": 1},
            {"active": {"prod-worker@owned": [{"id": "work"}]}},
            {"unacked": (1, 1)},
        ):
            with self.subTest(options=options):
                app, expected, _ = self.fixture(**options)
                self.assertFalse(drain.assert_empty(app, expected))

    def test_unavailable_or_inconsistent_native_unacked_inventory_holds(self):
        for counts in ((0, 1), (-1, -1), (True, True), None):
            with self.subTest(counts=counts):
                app, expected, _ = self.fixture(unacked=counts)
                with self.assertRaisesRegex(
                    drain.DrainUnavailable, "unacked_inventory"
                ):
                    drain.assert_empty(app, expected)
        app, expected, _ = self.fixture()
        with app.connection_for_read() as connection:
            with connection.channel() as channel:
                del channel.qos
        with self.assertRaisesRegex(drain.DrainUnavailable, "unacked_inventory"):
            drain.assert_empty(app, expected)

    def test_native_disabled_ack_emulation_has_no_persistent_unacked_store(self):
        app, expected, _ = self.fixture(ack_emulation=False, unacked=None)
        self.assertTrue(drain.assert_empty(app, expected))

    def test_missing_competing_or_wrong_queue_consumers_hold(self):
        for consumers in (
            {},
            {"unowned": []},
            {"prod-worker@owned": [{"name": "other"}]},
        ):
            with self.subTest(consumers=consumers):
                app, expected, _ = self.fixture(consumers=consumers)
                with self.assertRaises(drain.DrainUnavailable):
                    drain.assert_empty(app, expected)

    def test_drain_requires_two_observations_and_is_bounded(self):
        app, expected, declarations = self.fixture()
        ticks = iter((0, 0, 1))
        drain.await_drain(
            app,
            expected,
            timeout=3,
            monotonic=lambda: next(ticks),
            sleep=lambda _: None,
        )
        self.assertEqual(len(declarations), 4)
        app, expected, _ = self.fixture(depth=1)
        ticks = iter((0, 0, 2))
        with self.assertRaisesRegex(drain.DrainUnavailable, "drain_timeout"):
            drain.await_drain(
                app,
                expected,
                timeout=1,
                monotonic=lambda: next(ticks),
                sleep=lambda _: None,
            )

    def test_only_native_redis_404_is_an_empty_live_subscription(self):
        class ChannelError(Exception):
            def __init__(self, code):
                self.reply_code = code

        with patch.dict(
            "sys.modules",
            {"kombu.exceptions": SimpleNamespace(ChannelError=ChannelError)},
        ):
            for code in (404, "404"):
                app, expected, _ = self.fixture(queue_error=ChannelError(code))
                self.assertTrue(drain.assert_empty(app, expected))
            for error, transport in (
                (ChannelError(404), "amqp"),
                (ChannelError("404"), "amqp"),
                (ChannelError(404.0), "redis"),
                (ChannelError(" 404"), "redis"),
                (ChannelError("404 "), "redis"),
                (ChannelError("0404"), "redis"),
                (ChannelError(True), "redis"),
                (ChannelError(500), "redis"),
                (OSError(), "redis"),
            ):
                with self.subTest(error=error, transport=transport):
                    app, expected, _ = self.fixture(
                        queue_error=error, transport=transport
                    )
                    with self.assertRaises(drain.DrainUnavailable):
                        drain.assert_empty(app, expected)

    def test_installed_virtual_passive_empty_queue_uses_native_404_form(self):
        try:
            from kombu.exceptions import ChannelError
            from kombu.transport.virtual import Channel
        except ImportError:
            self.skipTest(
                "Native transport regression requires the worker dependency environment"
            )
        native_channel = SimpleNamespace(
            _has_queue=lambda *_args, **_kwargs: False,
            connection=SimpleNamespace(
                client=SimpleNamespace(virtual_host="/synthetic")
            ),
        )
        with self.assertRaises(ChannelError) as observed:
            Channel.queue_declare(native_channel, queue="synthetic-owned", passive=True)
        self.assertIs(type(observed.exception.reply_code), str)
        self.assertEqual(observed.exception.reply_code, "404")
        app, expected, _ = self.fixture(queue_error=observed.exception)
        self.assertTrue(drain.assert_empty(app, expected))


class OfficialSliceTests(unittest.TestCase):
    def test_owners_are_projected_from_current_inventories(self):
        official = "from miy_api.domains.files.router import router\nfrom miy_api.domains.auth.router import router"
        platform = "from miy_api.domains.auth.router import router"
        worker = 'WORKER_TASK_MODULES: dict = {"miy_worker.tasks.mail": ("official", ("mail.sync",)), "miy_worker.tasks.ocr": ("platform", ("ocr.normalize",))}'
        domains, tasks = slice_contract.owned_paths(official, platform, worker)
        self.assertEqual(domains, {"apps/api/src/miy_api/domains/files/"})
        self.assertEqual(tasks, {"apps/worker/src/miy_worker/tasks/mail.py"})
        slice_contract.assert_owned(
            [
                "apps/api/src/miy_api/domains/files/service.py",
                "apps/worker/src/miy_worker/tasks/mail.py",
                "apps/official-suite/src/main.tsx",
            ],
            domains,
            tasks,
        )

    def test_shared_contract_storage_or_unknown_source_requires_full_release(self):
        domains, tasks = {"apps/api/src/miy_api/domains/files/"}, set()
        for name in (
            "apps/api/src/miy_api/domains/files/models.py",
            "apps/api/src/miy_api/core/settings.py",
            "packages/contracts/src/index.ts",
            "apps/api/alembic/versions/new.py",
            "apps/worker/src/miy_worker/tasks/unknown.py",
            "apps/official-suite/project.json",
            "apps/official-suite/vite.config.ts",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                slice_contract.assert_owned([name], domains, tasks)


class ActualOfficialSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.revision = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        cls.sources = slice_contract.python_sources(ROOT, cls.revision)
        cls.owners = slice_contract.owned_paths(
            *(
                cls.sources[name]
                for name in (
                    "apps/api/src/miy_api/official_api_registry.py",
                    "apps/api/src/miy_api/platform_api_registry.py",
                    "apps/api/src/miy_api/core/worker_queue_contract.py",
                )
            )
        )
        cls.shared = slice_contract.shared_consumers(cls.sources, *cls.owners)

    def test_real_task_inventory_and_same_revision_slice(self):
        self.assertIn(
            "AI_GRAPH_RUN_TASK_NAME",
            self.sources["apps/api/src/miy_api/core/worker_queue_contract.py"],
        )
        self.assertIn("apps/worker/src/miy_worker/tasks/mail.py", self.owners[1])
        with patch.object(
            sys, "argv", ["slice", str(ROOT), self.revision, self.revision]
        ):
            slice_contract.main()

    def test_actual_shared_auth_and_rag_dependencies_require_full_release(self):
        for name in (
            "apps/api/src/miy_api/domains/pms/roles.py",
            "apps/api/src/miy_api/domains/files/core_projection.py",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.shared)
                with self.assertRaisesRegex(ValueError, "shared_consumer"):
                    slice_contract.assert_owned([name], *self.owners, self.shared)

    def test_actual_official_handler_can_use_the_slice(self):
        name = "apps/api/src/miy_api/domains/pms/router.py"
        self.assertNotIn(name, self.shared)
        slice_contract.assert_owned([name], *self.owners, self.shared)


class SharedConsumerProjectionTests(unittest.TestCase):
    domains = frozenset({"apps/api/src/miy_api/domains/files/"})
    helper = "apps/api/src/miy_api/domains/files/helper.py"

    def test_relative_transitive_dependency_is_shared(self):
        sources = {
            "apps/api/src/miy_api/core/entry.py": "from ..domains.files import bridge",
            "apps/api/src/miy_api/domains/files/bridge.py": "from . import helper",
            self.helper: "VALUE = 1",
        }
        self.assertIn(
            self.helper, slice_contract.shared_consumers(sources, self.domains, set())
        )

    def test_constant_dynamic_import_is_shared_but_unknown_target_holds(self):
        for call in (
            'load("miy_api.domains.files.helper")',
            'lib.import_module("miy_api.domains.files.helper")',
        ):
            sources = {
                "apps/api/src/miy_api/core/entry.py": "from importlib import import_module as load\nimport importlib as lib\n"
                + call,
                self.helper: "VALUE = 1",
            }
            self.assertIn(
                self.helper,
                slice_contract.shared_consumers(sources, self.domains, set()),
            )
        sources["apps/api/src/miy_api/core/entry.py"] = (
            "from importlib import import_module as load\nload(runtime_module)"
        )
        with self.assertRaisesRegex(ValueError, "unresolved_dynamic_module_owner"):
            slice_contract.shared_consumers(sources, self.domains, set())

    def test_ambiguous_relative_import_holds(self):
        sources = {
            "apps/api/src/miy_api/core/entry.py": "from ....unknown import helper",
            self.helper: "VALUE = 1",
        }
        with self.assertRaisesRegex(ValueError, "unresolved_relative_module_owner"):
            slice_contract.shared_consumers(sources, self.domains, set())

    def test_unconditional_official_registry_import_is_not_an_owner_boundary(self):
        sources = {
            "apps/api/src/miy_api/api_registry.py": "from miy_api.official_api_registry import official_router_specs",
            "apps/api/src/miy_api/official_api_registry.py": "from miy_api.domains.files import helper",
            self.helper: "VALUE = 1",
        }
        with self.assertRaisesRegex(ValueError, "unresolved_router_composition_owner"):
            slice_contract.shared_consumers(sources, self.domains, set())

    def test_task_name_expressions_are_not_executed(self):
        source = 'raise RuntimeError("must not execute source")\nWORKER_TASK_MODULES: dict = {"miy_worker.tasks.mail": ("official", dangerous())}'
        self.assertEqual(
            slice_contract.worker_owners(source),
            {"apps/worker/src/miy_worker/tasks/mail.py"},
        )
        for source in (
            'WORKER_TASK_MODULES: dict = {module_name: ("official", ())}',
            'WORKER_TASK_MODULES: dict = {"miy_worker.tasks.mail": (owner, ())}',
            'WORKER_TASK_MODULES: dict = {"miy_worker.tasks.mail": ("official", ()), "miy_worker.tasks.mail": ("platform", ())}',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                slice_contract.worker_owners(source)


if __name__ == "__main__":
    unittest.main()
