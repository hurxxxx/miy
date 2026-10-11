"""Owned task/Beat registry for inspection; starting it is explicitly refused."""

from miy_worker.profile_app import create_inactive_profile_app

celery_app = create_inactive_profile_app("official")
