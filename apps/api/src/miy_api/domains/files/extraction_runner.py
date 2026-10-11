"""Inactive fixed local runner. It owns each fresh Source Session and COMMIT."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files.artifact_contract import validate_file_extraction_artifact
from miy_api.domains.files.extraction_contracts import (
    FileExtractionBoundInput,
    FileExtractionCommitUnknown,
    FileExtractionComputedResult,
    FileExtractionControlError,
    FileExtractionInput,
    FileExtractionNeedsOcr,
    FileExtractionReceipt,
    FileExtractionRefused,
    FileExtractionRequestSpec,
)
from miy_api.domains.files.source_extraction_bootstrap import (
    FileExtractionBootstrapProbe,
    FileExtractionBootstrapWorkset,
)


def _require_synchronous_caller() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise FileExtractionRefused("synchronous_runner_required")


class _NoOcrRuntime:
    @property
    def ocr_provider_name(self):
        raise AssertionError("local extraction must not inspect a provider")

    def extract_text(self, **kwargs):
        raise AssertionError("local extraction must not dispatch OCR")


def compute_local_file_extraction(bound: FileExtractionBoundInput) -> FileExtractionComputedResult:
    """Pure compute after input-bind ACK. No database Session or provider exists."""
    from miy_api.domains.files.rag_projection import (
        UnsupportedFileForRetrieval,
        extract_file_artifact,
    )

    try:
        artifact = extract_file_artifact(
            file=bound.parser_input,
            content=bound.content,
            rag_service=_NoOcrRuntime(),
            allow_ocr=False,
        )
        artifact = validate_file_extraction_artifact(
            file_id=bound.parser_input.id,
            content_checksum=artifact.content_checksum,
            text=artifact.text,
            blocks=[block.to_dict() for block in artifact.blocks],
            metadata=artifact.metadata,
        )
        if artifact.content_checksum != bound.receipt.input_sha256:
            raise FileExtractionRefused("bound_input_checksum_conflict")
        return FileExtractionComputedResult("ready", artifact.content_checksum, artifact)
    except FileExtractionNeedsOcr:
        return FileExtractionComputedResult("ocr_required", bound.receipt.input_sha256)
    except UnsupportedFileForRetrieval:
        return FileExtractionComputedResult("unsupported", bound.receipt.input_sha256)
    except FileExtractionRefused:
        raise
    except Exception:
        # Only local parser failures arrive here: storage/admission ran in the
        # prior stage, and the OCR control never enters the legacy degradation catch.
        return FileExtractionComputedResult("failed", bound.receipt.input_sha256)


class FileExtractionRunner:
    def __init__(self, source_session_factory: Callable[[], Session]) -> None:
        self._factory = source_session_factory

    def _owned(self, phase: str, function, **kwargs):
        _require_synchronous_caller()
        try:
            db = self._factory()
        except SQLAlchemyError:
            raise FileExtractionRefused("source_session_factory_failed") from None
        owns_session = False
        try:
            commands.require_fresh_file_extraction_session(db)
            owns_session = True
            result = function(db, **kwargs)
            receipt = result.receipt if isinstance(result, FileExtractionBoundInput) else result
            try:
                db.commit()
            except BaseException:
                try:
                    db.rollback()
                except BaseException:
                    pass
                raise FileExtractionCommitUnknown(
                    phase,
                    receipt if isinstance(receipt, FileExtractionReceipt) else None,
                    retained_result=result,
                ) from None
            if isinstance(result, FileExtractionBoundInput):
                return replace(result, receipt=replace(result.receipt, provisional=False))
            if isinstance(result, FileExtractionReceipt):
                return replace(result, provisional=False)
            if isinstance(result, FileExtractionBootstrapProbe):
                return replace(
                    result,
                    provisional=False,
                    members=tuple(
                        replace(member, receipt=replace(member.receipt, provisional=False))
                        if member.receipt is not None
                        else member
                        for member in result.members
                    ),
                )
            return result
        finally:
            if owns_session:
                try:
                    db.close()
                except BaseException:
                    # Best-effort cleanup neither overrides a control nor changes
                    # the recorded COMMIT acknowledgement into another outcome.
                    pass

    def capture(
        self, *, actor_user_id: str, execution_ref: str, file_id: str
    ) -> FileExtractionInput:
        return self._owned(
            "capture",
            commands.capture_file_extraction_input,
            actor_user_id=actor_user_id,
            execution_ref=execution_ref,
            file_id=file_id,
        )

    def prepare(self, spec: FileExtractionRequestSpec) -> FileExtractionReceipt:
        return self._owned("prepare", commands.prepare_file_extraction, spec=spec)

    def probe_bootstrap(
        self, workset: FileExtractionBootstrapWorkset
    ) -> FileExtractionBootstrapProbe:
        return self._owned(
            "bootstrap_probe", commands.probe_file_extraction_workset, workset=workset
        )

    def observe(
        self,
        *,
        spec: FileExtractionRequestSpec,
        execution_ref: str | None = None,
        expected_result_digest: str | None = None,
        expected_claim_token: UUID | None = None,
        expected_input_sha256: str | None = None,
        require_original_execution: bool = False,
    ) -> FileExtractionReceipt:
        return self._owned(
            "observe",
            commands.observe_file_extraction,
            request_id=spec.request_id,
            request_digest=spec.digest(),
            actor_user_id=spec.actor_user_id,
            execution_ref=execution_ref or spec.execution_ref,
            expected_result_id=spec.result_id,
            expected_result_digest=expected_result_digest,
            expected_claim_token=expected_claim_token,
            expected_input_sha256=expected_input_sha256,
            require_original_execution=require_original_execution,
        )

    def observe_unknown(
        self,
        error: FileExtractionCommitUnknown,
        *,
        spec: FileExtractionRequestSpec,
        execution_ref: str | None = None,
        require_original_execution: bool = False,
    ) -> FileExtractionReceipt:
        retained = error.receipt
        if retained is None or (
            retained.request_id,
            retained.result_id,
            retained.event_id,
            retained.request_digest,
        ) != (spec.request_id, spec.result_id, spec.event_id, spec.digest()):
            raise FileExtractionRefused("retained_unknown_identity_required")
        return self.observe(
            spec=spec,
            execution_ref=execution_ref,
            expected_result_digest=retained.result_digest,
            expected_claim_token=retained.claim_token,
            expected_input_sha256=retained.input_sha256,
            require_original_execution=require_original_execution,
        )

    def run(self, spec: FileExtractionRequestSpec, *, claim_token: UUID) -> FileExtractionReceipt:
        _require_synchronous_caller()  # Before opening a Session, claim or storage.
        try:
            self.prepare(spec)
        except FileExtractionCommitUnknown as error:
            # One observation may establish the same prepare. Absence/refusal
            # never allocates a new ID or retries the write.
            try:
                self.observe_unknown(error, spec=spec, require_original_execution=True)
            except FileExtractionControlError:
                raise error from None
        try:
            claim = self._owned(
                "claim",
                commands.claim_file_extraction,
                request_id=spec.request_id,
                request_digest=spec.digest(),
                execution_ref=spec.execution_ref,
                claim_token=claim_token,
            )
            acquired = claim.newly_acquired
        except FileExtractionCommitUnknown as error:
            if error.receipt is None or not error.receipt.newly_acquired:
                raise
            try:
                claim = self.observe_unknown(error, spec=spec, require_original_execution=True)
            except FileExtractionControlError:
                raise error from None
            acquired = claim.state == "claimed"
        if not acquired:
            # An exact token replay is durable history, never a compute permit.
            return replace(claim, newly_acquired=False)
        # This original live frame consumed its single read permit. No loop,
        # fresh process, duplicate receipt or exception handler can recreate it.
        try:
            bound = self._owned(
                "input_bind",
                commands.bind_file_extraction_input,
                request_id=spec.request_id,
                request_digest=spec.digest(),
                execution_ref=spec.execution_ref,
                claim_token=claim_token,
            )
        except FileExtractionCommitUnknown as error:
            retained = error._retained_result
            if not isinstance(retained, FileExtractionBoundInput):
                raise
            try:
                observed = self.observe_unknown(error, spec=spec, require_original_execution=True)
            except FileExtractionControlError:
                raise error from None
            if observed.state != "input_bound" or observed.input_byte_count != len(
                retained.content
            ):
                raise error from None
            bound = replace(retained, receipt=observed)
        computed = compute_local_file_extraction(bound)
        # The bound input is used once outside DB locks. Apply uncertainty is
        # observation-only; it never returns to this parse statement.
        return self._owned(
            "apply",
            commands.apply_file_extraction_result,
            request_id=spec.request_id,
            request_digest=spec.digest(),
            execution_ref=spec.execution_ref,
            claim_token=claim_token,
            computed_result=computed,
        )
