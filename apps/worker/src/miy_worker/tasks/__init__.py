"""Tasks for the single selected Celery process profile (legacy by default)."""

from miy_worker.runtime import ensure_api_src_on_path
from miy_worker.task_binding import selected_profile
from miy_worker.task_catalog import load_profile_tasks

ensure_api_src_on_path()
load_profile_tasks(selected_profile())
