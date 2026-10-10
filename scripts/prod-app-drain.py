"""Read-only, bounded queue drain gate, sent to the current worker via stdin.

Use the running artifact's Celery/Kombu contracts. Never read payloads, copy or
purge a queue, revoke tasks, or republish work. Incomplete replies are a HOLD.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable


class DrainUnavailable(RuntimeError):
    pass


def native_unacked_empty(connection, channel) -> bool:
    """Count only native Redis QoS stores, without reading delivery metadata."""
    if connection.transport.driver_type != "redis":
        return True
    try:
        if type(channel.ack_emulation) is not bool:
            raise DrainUnavailable("unacked_inventory")
        if not channel.ack_emulation:
            # The native transport disables its visibility-timeout store.
            return True
        qos = channel.qos
        if not all(
            isinstance(key, str) and key
            for key in (qos.unacked_key, qos.unacked_index_key)
        ):
            raise DrainUnavailable("unacked_inventory")
        with channel.conn_or_acquire() as client:
            # A native atomic snapshot avoids mismatched counts while workers
            # acknowledge. Both operations count entries; neither reads data.
            with client.pipeline(transaction=True) as pipeline:
                pipeline.hlen(qos.unacked_key)
                pipeline.zcard(qos.unacked_index_key)
                counts = pipeline.execute()
        if (
            not isinstance(counts, (list, tuple))
            or len(counts) != 2
            or any(type(count) is not int or count < 0 for count in counts)
            or counts[0] != counts[1]
        ):
            raise DrainUnavailable("unacked_inventory")
        return counts[0] == 0
    except Exception:
        raise DrainUnavailable("unacked_inventory") from None


def assert_empty(app, consumers: dict[str, tuple[str, ...]]) -> bool:
    inspector = app.control.inspect(timeout=5)
    queues = inspector.active_queues()
    if not isinstance(queues, dict) or set(queues) != set(consumers):
        raise DrainUnavailable("consumer_inventory")
    for consumer, expected in consumers.items():
        entries = queues[consumer]
        if not isinstance(entries, list) or any(
            not isinstance(item, dict) for item in entries
        ):
            raise DrainUnavailable("consumer_queue_inventory")
        names = [item.get("name") for item in entries]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise DrainUnavailable("consumer_queue_inventory")
    empty = True
    for method in (inspector.active, inspector.reserved, inspector.scheduled):
        replies = method()
        if not isinstance(replies, dict) or set(replies) != set(consumers):
            raise DrainUnavailable("work_inventory")
        if any(not isinstance(entries, list) for entries in replies.values()):
            raise DrainUnavailable("work_inventory")
        empty = empty and all(not entries for entries in replies.values())
    with app.connection_for_read() as connection:
        if hasattr(connection, "ensure_connection"):
            connection.ensure_connection(max_retries=0, timeout=5)
        with connection.channel() as channel:
            # Kombu's native transport owns queue size (including Redis priority
            # buckets). Only Redis's documented empty-key 404 is handled below;
            # no host key naming or opaque payload inspection is introduced.
            for queue in sorted(
                {queue for queues in consumers.values() for queue in queues}
            ):
                try:
                    result = channel.queue_declare(queue=queue, passive=True)
                    count = result.message_count
                except Exception as error:
                    from kombu.exceptions import ChannelError

                    # Redis removes its list key after the last delivery. An
                    # empty, already-attested live subscription therefore has
                    # no key and Kombu's passive declare returns exact 404.
                    # Kombu's virtual transport reports the canonical code as
                    # a string; py-amqp can also provide the integer form.
                    # Other transports/errors still cannot prove emptiness.
                    if (
                        isinstance(error, ChannelError)
                        and type(error.reply_code) in (int, str)
                        and error.reply_code in (404, "404")
                        and connection.transport.driver_type == "redis"
                    ):
                        count = 0
                    else:
                        raise DrainUnavailable("queue_depth") from None
                if type(count) is not int or count < 0:
                    raise DrainUnavailable("queue_depth")
                empty = empty and count == 0
            empty = native_unacked_empty(connection, channel) and empty
    return empty


def await_drain(
    app,
    consumers: dict[str, tuple[str, ...]],
    *,
    timeout: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = monotonic() + timeout
    consecutive = 0
    while monotonic() < deadline:
        consecutive = consecutive + 1 if assert_empty(app, consumers) else 0
        if consecutive == 2:
            return
        sleep(2)
    raise DrainUnavailable("drain_timeout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consumer", action="append", required=True, help="hostname|profile"
    )
    parser.add_argument("--timeout", type=int, default=3900)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3900:
        raise DrainUnavailable("drain_timeout_bound")
    sys.path[:0] = ["apps/worker/src", "apps/api/src"]
    from celery import Celery
    from miy_worker.settings import get_settings

    consumers = {}
    for binding in args.consumer:
        consumer, profile = binding.split("|", 1)
        if not consumer or consumer in consumers:
            raise DrainUnavailable("consumer_inventory")
        if profile == "legacy":
            from miy_worker.queue_contract import celery_worker_queue_argument

            queues = tuple(celery_worker_queue_argument().split(","))
        elif profile in ("platform", "official"):
            from miy_api.core.worker_queue_contract import worker_profile_queues

            queues = worker_profile_queues(profile)
        else:
            raise DrainUnavailable("consumer_profile")
        consumers[consumer] = queues
    settings = get_settings()
    app = Celery("miy-release-drain", broker=settings.broker_url)
    # Broker operations are bounded independently of the total drain deadline.
    app.conf.broker_connection_timeout = 5
    app.conf.broker_connection_retry = False
    app.conf.broker_connection_max_retries = 0
    app.conf.broker_transport_options = {
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "max_retries": 0,
    }
    await_drain(app, consumers, timeout=args.timeout)
    print(
        "Production queue drain passed: exact consumers, queues, work and native unacked stores are empty."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not print exceptions: broker connection diagnostics may contain a
        # credential URL, and Celery replies can contain customer task metadata.
        print(
            "Production queue drain unavailable or incomplete; activation HOLD.",
            file=sys.stderr,
        )
        os._exit(1)
