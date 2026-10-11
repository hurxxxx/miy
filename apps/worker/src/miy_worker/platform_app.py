"""Platform worker/Beat artifact; no active consumer or scheduler."""

from miy_worker.profile_app import create_inactive_profile_app

celery_app = create_inactive_profile_app("platform")
