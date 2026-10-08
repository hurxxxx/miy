"""Fixed task wire and inactive preparation; no provider, broker or database."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from miy_api.core.worker_queue_contract import (
    WorkerProfileUnavailable,
    require_worker_profile_active,
)
from miy_api.domains.official_apps.recording_publications import PublicationMessage
from miy_api.domains.recording.pipeline_contracts import (
    MANAGED_HEADER,
    MANAGED_QUEUE,
    STAGES,
    RecordingCommandError,
    RecordingEnvelope,
    payload_digest,
    stage_args,
)


@pytest.mark.parametrize("version", [True, "1", 1.0, None, 2])
def test_envelope_does_not_coerce_protocol_versions(version):
    with pytest.raises(ValidationError):
        RecordingEnvelope.model_validate(
            dict(
                version=version,
                command_id=str(uuid4()),
                publication_id=str(uuid4()),
                payload_digest="a" * 64,
            )
        )


@pytest.mark.parametrize("stage", STAGES)
def test_existing_stage_args_and_public_signature_without_canvas(stage):
    recording, attempt, command, publication, task = [str(uuid4()) for _ in range(5)]
    result = SimpleNamespace(version=7, summary_text="Summary", verifier_note="Verified")
    args = stage_args(stage, recording, attempt, result)
    if stage == "transcribe":
        assert args == [recording, attempt]
    elif stage == "analyze_transcript":
        assert args == [{"recording_id": recording, "attempt_id": attempt}]
    else:
        assert args[0]["summary"] == "Summary" and args[0]["result_version"] == 7
        assert args[0]["agent_flow"] == ["domain.meeting", "meeting.transcript_summarizer"] + (
            ["verifier.grounding"] if stage == "persist_result" else []
        )
    calls = []

    class Celery:
        def signature(self, name, **kwargs):
            calls.append((name, kwargs))
            return SimpleNamespace(apply_async=lambda **options: calls.append(options))

    message = PublicationMessage(
        "recording." + stage,
        tuple(args),
        task,
        command,
        publication,
        payload_digest(args),
        attempt,
        None,
        0,
    )
    message.publish(Celery())
    assert calls[0] == ("recording." + stage, {"args": args, "kwargs": {}, "immutable": True})
    options = calls[1]
    assert options == dict(
        task_id=task,
        queue=MANAGED_QUEUE,
        serializer="json",
        retry=False,
        headers={
            MANAGED_HEADER: dict(
                version=1,
                command_id=command,
                publication_id=publication,
                payload_digest=payload_digest(args),
            )
        },
        root_id=attempt,
        parent_id=None,
        retries=0,
    )
    assert not {"chain", "link", "link_error"}.intersection(options)


def test_payload_digest_canonical_and_source_result_required():
    assert payload_digest([{"b": 2, "a": 1}]) == payload_digest([{"a": 1, "b": 2}])
    assert payload_digest([{"a": 1}]) != payload_digest([{"a": 2}])
    with pytest.raises(RecordingCommandError, match="result_missing"):
        stage_args("persist_result", "r", "a", None)
    with pytest.raises(WorkerProfileUnavailable):
        require_worker_profile_active("official")


def test_installed_celery_public_signature_has_no_automatic_successor(monkeypatch):
    from celery import Celery

    app = Celery("synthetic-recording-publication", broker="memory://", backend="cache+memory://")
    published = []

    def send_task(name, args=None, kwargs=None, **options):
        published.append((name, args, kwargs, options))
        return SimpleNamespace(id=options["task_id"])

    monkeypatch.setattr(app, "send_task", send_task)
    ids = [str(uuid4()) for _ in range(4)]
    message = PublicationMessage(
        "recording.transcribe",
        (ids[0], ids[1]),
        ids[2],
        ids[3],
        str(uuid4()),
        payload_digest([ids[0], ids[1]]),
        ids[1],
        None,
        0,
    )
    try:
        message.publish(app)
    finally:
        app.close()
    name, args, kwargs, options = published[0]
    assert name == "recording.transcribe" and tuple(args) == message.args and kwargs == {}
    assert options["retry"] is False and options["queue"] == MANAGED_QUEUE
    assert options["root_id"] == ids[1] and options["task_id"] == ids[2]
    assert not any(options.get(key) for key in ("chain", "link", "link_error"))
