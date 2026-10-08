"""Read-only Files result-stamp compatibility check before forward runtime cutover.

The production supervisor stops the old writers for the complete check/start
handoff. A standalone check proves only its observed current generation; it
cannot stop other writers or authorize a deployment.
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import signal
import sys
from typing import Literal, Protocol

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from miy_api.domains.files.models import FileManagerFile

GATE_VERSION = "files-result-stamp-v1"
CHECK_SECONDS = 120
CLEANUP_SECONDS = 5
_SAFE_GENERATION_ERRORS = frozenset(
    {
        "source_baseline_unavailable",
        "active_generation_pair_invalid",
        "physical_generation_missing",
        "partial_physical_generation",
        "projection_resource_count_mismatch",
        "projection_identity_mismatch",
        "opensearch_document_count_mismatch",
        "qdrant_point_count_mismatch",
        "opensearch_projection_content_mismatch",
        "qdrant_projection_content_mismatch",
        "projection_queues_not_drained",
        "active_generation_configuration_drift",
        "stored_validation_evidence_invalid",
        "stored_validation_evidence_diverged",
        "active_release_gate_not_ready",
    }
)
_SAFE_REASONS = _SAFE_GENERATION_ERRORS | {
    "configuration_invalid",
    "source_result_stamp_missing",
    "current_generation_not_ready",
    "generation_verification_failed",
    "deadline_unavailable",
    "deadline_exceeded",
    "verification_effect_forbidden",
    "cutover_check_failed",
}


class FilesCutoverSettings(Protocol):
    rag_enabled: bool
    files_retrieval_enabled: bool


class FilesContentCutoverRefused(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = (
            reason if type(reason) is str and reason in _SAFE_REASONS else "cutover_check_failed"
        )
        super().__init__("files_content_cutover_refused")


class _DeadlineExpired(BaseException):
    pass


@dataclass(frozen=True, slots=True)
class FilesContentCutoverReceipt:
    mode: Literal["inactive", "empty_source", "verified"]
    gate_version: str = GATE_VERSION


def check_files_content_cutover(
    *,
    settings: FilesCutoverSettings,
    session_factory: Callable[[], Session],
    verify_active: Callable[[], object],
) -> FilesContentCutoverReceipt:
    """Complete the versioned check without a mark-complete or fallback input.

    The trusted composition supplies the existing runner's actual verify_active
    method; its complete Source/physical projection hashes include extracted_at.
    No nonempty source is treated as empty merely because no artifact is ready.
    """
    if type(settings.rag_enabled) is not bool or type(settings.files_retrieval_enabled) is not bool:
        raise FilesContentCutoverRefused("configuration_invalid")
    if not settings.rag_enabled or not settings.files_retrieval_enabled:
        return FilesContentCutoverReceipt("inactive")
    try:
        from miy_api.core.model_registry import import_all_models

        import_all_models()
        with session_factory() as db, db.no_autoflush:
            count = db.scalar(select(func.count()).select_from(FileManagerFile))
            missing_stamp = db.scalar(
                select(FileManagerFile.id)
                .where(
                    FileManagerFile.deleted_at.is_(None),
                    FileManagerFile.extraction_status == "ready",
                    FileManagerFile.extracted_at.is_(None),
                )
                .limit(1)
            )
        if count == 0:
            return FilesContentCutoverReceipt("empty_source")
        if missing_stamp is not None:
            raise FilesContentCutoverRefused("source_result_stamp_missing")
        result = verify_active()
        if (
            getattr(result, "deployment_enabled", None) is not True
            or getattr(result, "ready", None) is not True
        ):
            raise FilesContentCutoverRefused("current_generation_not_ready")
    except FilesContentCutoverRefused:
        raise
    except Exception as error:
        reason = getattr(error, "code", None)
        safe_reason = (
            reason
            if type(reason) is str and reason in _SAFE_GENERATION_ERRORS
            else "generation_verification_failed"
        )
        raise FilesContentCutoverRefused(safe_reason) from None
    return FilesContentCutoverReceipt("verified")


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    """Bound this owned synchronous Linux process; never escape into a thread."""
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise FilesContentCutoverRefused("deadline_unavailable")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signal, _frame) -> None:
        raise _DeadlineExpired()

    installed = False
    try:
        try:
            signal.signal(signal.SIGALRM, expired)
            installed = True
            signal.setitimer(signal.ITIMER_REAL, seconds)
        except (ValueError, OSError):
            raise FilesContentCutoverRefused("deadline_unavailable") from None
        yield
    finally:
        if installed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            finally:
                signal.signal(signal.SIGALRM, previous)


@contextmanager
def _readonly_session(factory: Callable[[], Session]) -> Iterator[Session]:
    from miy_api.core.model_registry import import_all_models

    import_all_models()
    with factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        db.execute(text("SET LOCAL lock_timeout = '5000ms'"))
        yield db


def _forbid_effect(*_args, **_kwargs):
    raise FilesContentCutoverRefused("verification_effect_forbidden")


def _verification_materializer(*, session_factory, settings):
    from miy_api.domains.retrieval.files_generation_materializer import (
        FilesCachedProjectionMaterializer,
    )

    class CutoverReadMaterializer(FilesCachedProjectionMaterializer):
        # A nonempty Source table can contain only tombstones/unsupported files.
        # Their unresolved jobs still require actual reconciliation evidence.
        requires_empty_reconciliation = True

    return CutoverReadMaterializer(
        session_factory=session_factory,
        settings=settings,
        keyword_client_factory=_forbid_effect,
        rag_service_factory=_forbid_effect,
    )


def main(argv: Sequence[str] | None = None) -> int:
    if list(sys.argv[1:] if argv is None else argv):
        print(f"status=failed gate={GATE_VERSION} reason=arguments_invalid", file=sys.stderr)
        return 1
    backends = None
    receipt = None
    reason = "cutover_check_failed"
    try:
        with _deadline(CHECK_SECONDS):
            from miy_api.core.settings import get_settings

            settings = get_settings()

            def session_factory():
                from miy_api.core.db import get_session_factory

                return _readonly_session(get_session_factory())

            def verify_active():
                nonlocal backends
                from miy_api.domains.retrieval.files_generation_backends import (
                    FilesPhysicalGenerationBackends,
                )
                from miy_api.domains.retrieval.files_generation_runner import FilesGenerationRunner

                backends = FilesPhysicalGenerationBackends(
                    settings, embedding_dimensions_resolver=_forbid_effect
                )
                runner = FilesGenerationRunner(
                    session_factory=session_factory,
                    settings=settings,
                    backends=backends,
                    materializer=_verification_materializer(
                        session_factory=session_factory,
                        settings=settings,
                    ),
                )
                return runner.verify_active()

            receipt = check_files_content_cutover(
                settings=settings, session_factory=session_factory, verify_active=verify_active
            )
    except FilesContentCutoverRefused as error:
        reason = error.reason if error.reason in _SAFE_REASONS else "cutover_check_failed"
    except _DeadlineExpired:
        reason = "deadline_exceeded"
    except BaseException:
        # No raw SQL parameters, artifact body, model/endpoint or credentials.
        reason = "cutover_check_failed"
    finally:
        if backends is not None:
            try:
                with _deadline(CLEANUP_SECONDS):
                    backends.close()
            except BaseException:
                # Closing a read client cannot replace completed verification or
                # the original fixed refusal. It never grants another attempt.
                pass
    if receipt is None:
        print(f"status=failed gate={GATE_VERSION} reason={reason}", file=sys.stderr)
        return 1
    print(f"status=ok gate={GATE_VERSION} result={receipt.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
