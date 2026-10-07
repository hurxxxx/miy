from miy_worker.tasks import recording


def test_asr_and_persist_use_actual_celery_execution_deadlines():
    for task, hard, soft in (
        (recording.transcribe_recording, 3600, 3300),
        (recording.persist_recording_result, 300, None),
    ):
        assert task.time_limit == hard
        assert task.soft_time_limit == soft
        assert task._get_exec_options()["time_limit"] == hard
        assert task._get_exec_options()["soft_time_limit"] == soft
