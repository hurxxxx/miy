import pytest


def test_owned_worker_refuses_foreign_partial_excluded_queues_and_embedded_beat_before_construction(
    monkeypatch,
):
    from miy_worker.first_party_app import FirstPartyConsumerApp, FirstPartyBeatApp

    consumer = FirstPartyConsumerApp("owned", broker="memory://", set_as_current=False)
    consumer._first_party_owned_queues = frozenset(
        {"miy.official.celery", "miy.official.recording"}
    )
    for options in (
        {"queues": "miy.platform.celery"},
        {"queues": "miy.official.celery"},
        {"exclude_queues": "miy.official.recording"},
        {"beat": True},
    ):
        with pytest.raises(RuntimeError, match="first_party_"):
            consumer.Worker(**options)
    with pytest.raises(RuntimeError, match="single_owner"):
        consumer.Beat()
    beat = FirstPartyBeatApp("scheduler", broker="memory://", set_as_current=False)
    with pytest.raises(RuntimeError, match="cannot_consume"):
        beat.Worker()
