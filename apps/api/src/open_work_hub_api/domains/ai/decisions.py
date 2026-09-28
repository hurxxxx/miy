"""Public facade for registered decision workloads."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from open_work_hub_api.domains.ai.audit import log_llm_call
from open_work_hub_api.domains.ai.decision_adapters import get_decision_adapter
from open_work_hub_api.domains.ai.decision_contracts import (
    ChoiceQuestion,
    ScoreQuestion,
    ProbabilityQuestion,
    DecisionInput,
    DecisionQuestion,
    DecisionResponse,
    DecisionError,
)
from open_work_hub_api.domains.ai.gateway import (
    AiGatewayDecision,
    LlmWorkloadContext,
    LlmWorkloadMetadata,
    prepare_structured_workload,
)
from open_work_hub_api.domains.ai.registry import get_ai_capability_registry


@dataclass(frozen=True)
class DecisionResult:
    response: DecisionResponse
    metadata: LlmWorkloadMetadata
    security: AiGatewayDecision
    latency_ms: int


def execute_decision(
    workload_id: str,
    context: LlmWorkloadContext,
    db: Session,
    *,
    state: str | dict[str, Any] | list[Any],
    questions: dict[str, DecisionQuestion],
    selected_model_id: str | None = None,
    sensitivity_labels: tuple[str, ...] = (),
    source_kinds: tuple[str, ...] = (),
    content_origin: str = "user_prompt",
) -> DecisionResult:
    """One bounded native call, with catalog selection only for opted-in workloads."""
    workload = get_ai_capability_registry().get_llm_workload(workload_id)
    if workload is None or workload.execution_kind != "decision":
        raise DecisionError("decision_workload_required")
    try:
        payload = DecisionInput(state=state, questions=questions)
    except (ValidationError, ValueError, RecursionError):
        raise DecisionError("decision_input_invalid") from None
    execution, masked = prepare_structured_workload(
        workload_id,
        context,
        db,
        payload=payload.model_dump(),
        selected_model_id=selected_model_id,
        sensitivity_labels=sensitivity_labels,
        source_kinds=source_kinds,
        content_origin=content_origin,
    )
    config = execution.llm_execution.config
    started = monotonic()
    result: DecisionResponse | None = None
    error: str | None = None
    try:
        request = DecisionInput.model_validate(masked)
        result = get_decision_adapter(config.provider).execute(config, request)
        result.validate_answers(request)
    except DecisionError as exc:
        error = exc.code
        raise
    except (ValueError, TypeError):
        error = "decision_response_invalid"
        raise DecisionError(error) from None
    except Exception:
        error = "decision_unavailable"
        raise DecisionError(error) from None
    finally:
        latency_ms = round((monotonic() - started) * 1000)
        log_llm_call(
            source=context.source,
            actor_user_id=context.actor_user_id,
            principal_kind=context.principal_kind,
            principal_id=context.principal_id,
            task_kind=workload.task_kind,
            workload_id=workload_id,
            app_id=execution.request.app or "",
            execution_kind="decision",
            connection_id=config.connection_id,
            provider=config.provider,
            requested_model=config.default_model,
            model=result.model if result is not None else config.default_model,
            policy=execution.decision.policy,
            chosen_pool=config.pool,
            decision_reason=",".join(execution.decision.reason_codes),
            forced_local=False,
            pii_hits=list(execution.decision.pii_hits),
            status="error" if error else "ok",
            error=error,
            latency_ms=latency_ms,
            usage=result.usage.model_dump(exclude_none=True) if result is not None else None,
            **execution.audit_fields(),
        )
    assert result is not None
    return DecisionResult(
        response=result,
        security=execution.decision,
        latency_ms=latency_ms,
        metadata=LlmWorkloadMetadata(
            workload_id,
            config.connection_id or "",
            config.provider,
            result.model,
            config.pool,
            execution_kind="decision",
            requested_model=config.default_model,
        ),
    )


__all__ = [
    "execute_decision",
    "DecisionResult",
    "DecisionError",
    "ChoiceQuestion",
    "ScoreQuestion",
    "ProbabilityQuestion",
]
