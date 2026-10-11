from miy_worker.task_binding import task_app

celery_app = task_app(__name__)


@celery_app.task(name="documents.sync")
def sync_documents() -> dict[str, str]:
    return {"task": "documents.sync", "status": "scaffolded"}
