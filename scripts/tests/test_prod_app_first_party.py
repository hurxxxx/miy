import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
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
            app, expected, _ = self.fixture(queue_error=ChannelError(404))
            self.assertTrue(drain.assert_empty(app, expected))
            for error, transport in (
                (ChannelError(404), "amqp"),
                (ChannelError(500), "redis"),
                (OSError(), "redis"),
            ):
                with self.subTest(error=error, transport=transport):
                    app, expected, _ = self.fixture(
                        queue_error=error, transport=transport
                    )
                    with self.assertRaises(drain.DrainUnavailable):
                        drain.assert_empty(app, expected)


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


if __name__ == "__main__":
    unittest.main()
