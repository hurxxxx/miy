"""One shared schedule owner for the unchanged platform/official task contract."""

from miy_worker.first_party_app import create_first_party_worker

celery_app = create_first_party_worker(profile="legacy", beat_only=True)
