"""Owned official consumer using current first-party authority and transactions."""

from miy_worker.first_party_app import create_first_party_worker

celery_app = create_first_party_worker(profile="official")
