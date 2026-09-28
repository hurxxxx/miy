from sqlalchemy.orm import Session

from open_work_hub_api.core.i18n import localized_http_exception
from open_work_hub_api.core.llm_errors import LlmProviderError
from open_work_hub_api.domains.ai.decision_contracts import ChoiceAnswer
from open_work_hub_api.domains.ai.decisions import ChoiceQuestion, DecisionError, execute_decision
from open_work_hub_api.domains.ai.gateway import AiGatewayPolicyViolation, LlmWorkloadContext
from open_work_hub_api.domains.ai.registry import AiCapabilityRegistry
from open_work_hub_api.domains.auth.models import User

from .schemas import TetrisCandidate, TetrisDecisionRequest, TetrisDecisionResponse, TetrisLanding

WORKLOAD_ID = "tetris.play"


def register_ai_capabilities(registry: AiCapabilityRegistry) -> None:
    registry.register_llm_workload(
        workload_id=WORKLOAD_ID,
        task_kind="tetris_play",
        owner_domain="tetris",
        app_id="tetris",
        description="Choose the next Tetris control from the current game state",
        label_key="tetris.AI play decision",
        description_key="tetris.Choose one control from the current board.",
        execution_kind="decision",
        required_capabilities=("decision",),
        default_runtime_adapter="decision",
        allowed_runtime_adapters=("decision",),
        default_route="external",
        allowed_routes=("external",),
    )


def _landing_description(item: TetrisLanding) -> str:
    return (
        f"Place {item.piece} {'using hold' if item.uses_hold else 'without hold'}; "
        f"reserve afterward: {item.hold_after or 'empty'}. "
        f"Clear {item.cleared_lines} lines; {item.holes} covered holes; "
        f"stack height {item.max_height}; total column heights {item.aggregate_height}; "
        f"surface roughness {item.bumpiness}; {item.key_presses} key presses."
    )


def _candidate_description(item: TetrisCandidate) -> str:
    description = _landing_description(item)
    if item.next_spawn_blocked:
        return description + " GAME OVER: the visible next piece cannot spawn."
    if item.next_piece is None:
        return description + " Empty hold consumed the visible next piece; the following piece is unknown. No forecast is available."
    description += f" Next active piece: {item.next_piece}. Possible second placements (only one can happen):"
    for future in item.follow_ups:
        description += (
            f" [{_landing_description(future)} "
            f"Total lines over both placements: {item.cleared_lines + future.cleared_lines}.]"
        )
    return description


def decide(db: Session, *, user: User, payload: TetrisDecisionRequest) -> TetrisDecisionResponse:
    # The browser's game engine supplies bounded hypothetical outcomes. They
    # are ephemeral game observations, not authoritative scores or access claims.
    choices = {f"option_{index}": item.action for index, item in enumerate(payload.candidates)}
    options = {
        f"option_{index}": _candidate_description(item)
        for index, item in enumerate(payload.candidates)
    }
    if len(options) == 1:
        choices["wait"] = "wait"
        options["wait"] = "Wait instead of completing the only reachable landing. Gravity still runs."
    try:
        result = execute_decision(
            WORKLOAD_ID,
            LlmWorkloadContext(source="api.tetris.play", actor_user_id=user.id, app_id="tetris"),
            db,
            state={
                "game": "Tetris",
                "goal": (
                    "Clear lines and survive. The engine has computed legal landing outcomes. "
                    "Avoid game over and covered holes. Compare immediate results with the "
                    "two-placement forecasts, including keeping or exchanging the reserve. "
                    "Set up the visible next piece, clear lines and keep a low flat stack. "
                    "Prefer fewer moves when outcomes are similar. Unknown future pieces are "
                    "not safe or unsafe forecasts; do not invent them. Choose the first landing; "
                    "only its first key press runs. Gravity continues and we observe again."
                ),
                "active_piece": payload.active.kind,
                "next_piece": payload.next,
                "hold_piece": payload.hold,
                "can_hold": payload.can_hold,
                "level": payload.level,
            },
            questions={
                "action": ChoiceQuestion(
                    instructions="Which first landing best balances survival, line clears and the next visible piece, considering the reserve?",
                    options=options,
                )
            },
            source_kinds=("game_state",),
        )
        answer = result.response.answers["action"]
        if not isinstance(answer, ChoiceAnswer) or answer.choice not in options:
            raise DecisionError("decision_response_invalid")
        return TetrisDecisionResponse(action=choices[answer.choice], latency_ms=result.latency_ms)
    except AiGatewayPolicyViolation as exc:
        raise localized_http_exception(status_code=403, code="tetris.ai_blocked") from exc
    except (DecisionError, LlmProviderError) as exc:
        raise localized_http_exception(status_code=502, code="tetris.ai_failed") from exc
