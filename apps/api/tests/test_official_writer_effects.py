"""Representative external effects must begin behind the actual source fence."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from dev_accounts import configure_company_app_access
from test_meeting import _create_meeting
from test_official_writer_fence import change
from test_official_writer_fence import writer as writer
from test_pms_issues import _create_issue, _create_task_list

from miy_api.domains.auth.models import User
from miy_api.domains.diagrams import router as diagrams
from miy_api.domains.diagrams.models import Diagram
from miy_api.domains.files import external_lifecycle
from miy_api.domains.files import router as files_router
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.meeting import file_storage
from miy_api.domains.meeting import service as meeting
from miy_api.domains.pms import attachments
from miy_api.domains.recording import blob_store
from miy_api.domains.recording import service as recording
from miy_api.domains.recording.models import RecordingStaging
from miy_api.domains.video_chat import service as video


@pytest.fixture
def effects(client, writer, monkeypatch, tmp_path):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(
            db, app_ids=["pms", "meeting", "diagrams", "files", "recording", "video-chat"]
        )
    objects, puts, removes = {}, [], []

    def put(*, storage_key, data=None, content=None, **kwargs):
        value = data if data is not None else content
        if hasattr(value, "read"):
            value = value.read()
        objects[storage_key] = value
        puts.append(storage_key)

    def remove(storage_key):
        removes.append(storage_key)
        objects.pop(storage_key, None)

    store = SimpleNamespace(put=put, remove=lambda **kwargs: remove(kwargs["storage_key"]))
    monkeypatch.setattr(attachments, "task_attachment_object_store", lambda: store)
    monkeypatch.setattr(file_storage, "put_attachment_object", put)
    monkeypatch.setattr(file_storage, "remove_attachment_object", remove)
    monkeypatch.setattr(diagrams, "put_diagram_object", put)
    monkeypatch.setattr(diagrams, "read_diagram_object", lambda key: objects[key])
    monkeypatch.setattr(
        diagrams, "remove_diagram_object", lambda **kwargs: remove(kwargs["storage_key"])
    )
    monkeypatch.setattr(blob_store, "put_recording_bytes", put)
    monkeypatch.setattr(recording, "_enqueue_pipeline_or_mark_failed", lambda *args, **kwargs: None)
    spool = SimpleNamespace(
        allocate=Mock(return_value=tmp_path / "synthetic"), write_chunk=Mock(), cleanup=Mock()
    )
    monkeypatch.setattr(blob_store, "default_spool_store", lambda: spool)
    headers = {"Authorization": "Bearer " + admin["token"]}
    token = admin["token"]
    task_list = _create_task_list(client, token)
    task = _create_issue(client, token, task_list["id"], title="Fence")
    pms_path = f"/api/v1/pms/tasks/{task['id']}/attachments"
    pms = client.post(
        pms_path, headers=headers, files={"file": ("pms.txt", b"original", "text/plain")}
    )
    assert pms.status_code == 201, pms.text
    meet = _create_meeting(client, token, title="Fence", attendees=[])
    meeting_path = f"/api/v1/meeting/meetings/{meet['id']}/files"
    meet_file = client.post(
        meeting_path, headers=headers, files={"file": ("meeting.txt", b"original", "text/plain")}
    )
    assert meet_file.status_code == 200, meet_file.text
    diagram = client.post(
        "/api/v1/diagrams/items", headers=headers, json={"title": "Fence", "xml": "<original/>"}
    )
    assert diagram.status_code == 201, diagram.text
    stage = client.post(
        "/api/v1/recording/recordings/staging",
        headers=headers,
        json={"idempotency_key": str(uuid4()), "mime_type": "audio/webm"},
    )
    assert stage.status_code == 201, stage.text
    vid = client.post("/api/v1/video-chat/sessions", headers=headers, json={"title": "Fence"})
    assert vid.status_code == 201, vid.text
    token_signer = Mock(wraps=video.create_livekit_join_token)
    monkeypatch.setattr(video, "create_livekit_join_token", token_signer)
    puts.clear()
    removes.clear()
    spool.allocate.reset_mock()
    return SimpleNamespace(
        factory=factory,
        admin=admin,
        headers=headers,
        objects=objects,
        puts=puts,
        removes=removes,
        spool=spool,
        pms_path=pms_path,
        pms=pms.json(),
        meeting_path=meeting_path,
        meeting=meet_file.json(),
        diagram=diagram.json(),
        staging=stage.json(),
        video=vid.json(),
        token_signer=token_signer,
    )


@pytest.mark.parametrize("accepted", [False, True])
def test_diagram_commit_unknown_never_overwrites_or_removes_original(effects, accepted):
    e = effects
    before = dict(e.objects)
    with e.factory() as db:
        user = db.get(User, e.admin["user"]["id"])
        original = db.get(Diagram, e.diagram["id"]).source_storage_key
        commit = db.commit

        def uncertain():
            if accepted:
                commit()
            raise OSError("synthetic unknown commit")

        db.commit = uncertain
        with pytest.raises(OSError):
            diagrams.update_diagram_item(
                e.diagram["id"],
                diagrams.UpdateDiagramRequest(version=1, xml="<new/>", preview_png_data_url=None),
                db,
                user,
            )
        db.rollback()
    assert all(e.objects[key] == value for key, value in before.items()) and e.removes == []
    assert len(e.puts) == 1 and e.puts[0] != original
    with e.factory() as db:
        pointer = db.get(Diagram, e.diagram["id"]).source_storage_key
        assert pointer == (e.puts[0] if accepted else original)


@pytest.mark.parametrize("accepted", [False, True])
def test_files_upload_unknown_preserves_bytes_with_or_without_committed_row(
    client, writer, monkeypatch, accepted
):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(db, app_ids=["files"])
    original_upload = files_router.files_service.upload_file
    objects, removes, ids = {}, [], []

    def put(*, storage_key, content, **kwargs):
        objects[storage_key] = content.read()

    monkeypatch.setattr(files_router.files_service.file_storage, "put_file_object", put)
    monkeypatch.setattr(
        files_router.files_service, "remove_storage_object_immediately", removes.append
    )

    def upload(db, **kwargs):
        row = original_upload(db, **kwargs)
        ids.append(row.id)
        commit = db.commit

        def uncertain():
            if accepted:
                commit()
            raise OSError("private commit acknowledgement lost")

        db.commit = uncertain
        return row

    monkeypatch.setattr(files_router.files_service, "upload_file", upload)
    response = client.post(
        "/api/v1/files/upload",
        headers={"Authorization": "Bearer " + admin["token"]},
        files={"file": ("synthetic.txt", b"preserve bytes", "text/plain")},
    )
    assert response.status_code == 500, response.text
    assert response.headers["X-MIY-Error-Code"] == "files.metadata_save_unknown"
    assert "private" not in response.text and "acknowledgement" not in response.text
    assert len(objects) == 1 and list(objects.values()) == [b"preserve bytes"]
    assert removes == [] and len(ids) == 1
    with factory() as db:
        row = db.get(FileManagerFile, ids[0])
        assert (row is not None) == accepted
        if row is not None:
            assert row.storage_key in objects


@pytest.mark.parametrize("finish", ["rollback_savepoint", "commit_outer", "unknown_session"])
def test_external_file_savepoint_does_not_decide_outer_commit(writer, monkeypatch, finish):
    factory, admin, _ = writer
    key = "synthetic/nested/" + str(uuid4())
    file_id = str(uuid4())
    removed = []
    monkeypatch.setattr(
        external_lifecycle.files_service, "remove_storage_object_immediately", removed.append
    )
    with factory() as db:
        root = db.begin()
        nested = db.begin_nested()
        db.add(
            FileManagerFile(
                id=file_id,
                owner_id=admin["user"]["id"],
                filename="nested.txt",
                content_type="text/plain",
                size_bytes=1,
                storage_key=key,
                visibility="private",
            )
        )
        db.flush()
        external_lifecycle._register_storage_compensation(db, key)
        if finish == "rollback_savepoint":
            nested.rollback()
            assert removed == [key]
            db.commit()
        elif finish == "rollback_outer":
            nested.commit()
            assert removed == []
            db.rollback()
        elif finish == "commit_outer":
            nested.commit()
            db.commit()
        else:
            dialect = db.get_bind().dialect
            real_commit = dialect.do_commit

            def lose_ack(connection):
                real_commit(connection)
                raise OSError("synthetic root acknowledgement lost")

            with monkeypatch.context() as patch:
                patch.setattr(dialect, "do_commit", lose_ack)
                with pytest.raises(OSError):
                    (root.commit if finish == "unknown_root_handle" else db.commit)()
                db.rollback()
        assert external_lifecycle._PENDING_STORAGE_COMPENSATIONS_KEY not in db.info
    committed = finish in {"commit_outer", "unknown_root_handle", "unknown_session"}
    with factory() as db:
        assert (db.get(FileManagerFile, file_id) is not None) == committed
    assert removed == ([] if committed else [key])


@pytest.mark.parametrize("outcome", ["unknown_before", "unknown_after", "accepted"])
def test_meeting_delete_preserves_spool_until_commit_ack(effects, monkeypatch, outcome):
    from miy_api.domains.meeting.models import Meeting

    e = effects
    meeting_id = e.meeting["id"]
    with e.factory.begin() as db:
        staging = db.get(RecordingStaging, e.staging["id"])
        staging.initial_target_app = "meeting"
        staging.initial_target_type = "meeting"
        staging.initial_target_id = meeting_id
    if outcome == "drain":
        with e.factory.begin() as db:
            change(db, e.admin)
    with e.factory() as db:
        real_commit = db.commit
        if outcome.startswith("unknown"):

            def uncertain():
                if outcome == "unknown_after":
                    real_commit()
                raise OSError("synthetic delete acknowledgement lost")

            db.commit = uncertain
        if outcome == "accepted":
            meeting.delete_meeting(
                db, user=db.get(User, e.admin["user"]["id"]), meeting_id=meeting_id
            )
        else:
            with pytest.raises(Exception) as failure:
                meeting.delete_meeting(
                    db, user=db.get(User, e.admin["user"]["id"]), meeting_id=meeting_id
                )
            if outcome == "drain":
                assert failure.value.orig.sqlstate == "55000"
            else:
                assert isinstance(failure.value, OSError)
    assert e.spool.cleanup.call_count == (1 if outcome == "accepted" else 0)
    with e.factory() as db:
        preserved = outcome in {"drain", "unknown_before"}
        assert (db.get(Meeting, meeting_id) is not None) == preserved
        assert (db.get(RecordingStaging, e.staging["id"]) is not None) == preserved


@pytest.mark.parametrize("operation", ["delete", "meeting_retry"])
def test_drained_recording_source_never_revokes_an_existing_job(effects, monkeypatch, operation):
    from miy_api.domains.meeting import recordings as meeting_recordings
    from miy_api.domains.meeting.models import Meeting
    from miy_api.domains.recording.models import Recording, RecordingTarget

    e = effects
    recording_id = str(uuid4())
    meeting_id = e.meeting["id"]
    with e.factory.begin() as db:
        db.add(
            Recording(
                id=recording_id,
                owner_id=e.admin["user"]["id"],
                storage_key="synthetic/" + recording_id,
                audio_status="saved",
                transcript_status="failed",
                summary_status="pending",
                celery_task_id="synthetic-job",
            )
        )
        db.flush()
        db.add(
            RecordingTarget(
                id=str(uuid4()),
                recording_id=recording_id,
                target_app="meeting",
                target_type="meeting",
                target_id=meeting_id,
                added_by_id=e.admin["user"]["id"],
            )
        )
    with e.factory.begin() as db:
        change(db, e.admin)
    revoke = Mock()
    monkeypatch.setattr(recording, "revoke_recording_task", revoke)
    with e.factory() as db:
        user = db.get(User, e.admin["user"]["id"])
        meet = db.get(Meeting, meeting_id)
        with pytest.raises(Exception) as failure:
            if operation == "delete":
                recording.delete_recording(db, user=user, recording_id=recording_id)
            elif operation == "retry":
                recording.retry_recording(db, user=user, recording_id=recording_id)
            elif operation == "meeting_retry":
                recording.retry_meeting_recording(
                    db, user=user, meeting=meet, recording_id=recording_id
                )
            elif operation == "meeting_archive":
                recording.archive_meeting_recording(
                    db, user=user, meeting=meet, recording_id=recording_id
                )
            else:
                meeting_recordings.cleanup_meeting_recordings(db, meeting=meet)
        assert failure.value.orig.sqlstate == "55000"
    assert not revoke.called
    with e.factory() as db:
        row = db.get(Recording, recording_id)
        assert row.celery_task_id == "synthetic-job" and row.trashed_at is None
        assert row.transcript_status == "failed"
