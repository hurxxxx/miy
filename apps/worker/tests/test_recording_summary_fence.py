from miy_worker.tasks import recording


def test_summary_tasks_use_actual_celery_execution_deadlines():
    for task, seconds in (
        (recording.analyze_transcript, 900),
        (recording.verify_transcript_summary, 600),
    ):
        assert task.time_limit == seconds
        assert task._get_exec_options()["time_limit"] == seconds
        # This slice does not invent a previously unspecified soft deadline.
        assert task.soft_time_limit is None
