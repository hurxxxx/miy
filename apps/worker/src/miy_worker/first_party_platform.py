"""Owned platform consumer; no official task or Beat owner is started."""

from miy_worker.first_party_app import create_first_party_worker

celery_app = create_first_party_worker(profile="platform")
