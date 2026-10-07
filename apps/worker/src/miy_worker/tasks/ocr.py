from miy_worker.task_binding import task_app

celery_app = task_app(__name__)


@celery_app.task(name="ocr.normalize")
def normalize_ocr_asset() -> dict[str, str]:
    return {"task": "ocr.normalize", "status": "scaffolded"}
