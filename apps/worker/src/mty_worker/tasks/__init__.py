"""Background tasks for the worker app."""

from mty_worker.runtime import ensure_api_src_on_path

ensure_api_src_on_path()

from mty_worker.tasks import (  # noqa: E402, F401
    ai_graph,
    documents,
    file_storage_cleanup,
    hermes,
    hermes_terminal,
    mail,
    media,
    meeting,
    ocr,
    rag_sync,
    recording,
    search_index,
)
