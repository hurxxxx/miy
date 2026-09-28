import json
from dataclasses import asdict
from time import monotonic

from sqlalchemy.orm import Session

from open_work_hub_api.core.i18n import localized_http_exception
from open_work_hub_api.core.llm_errors import LlmRuntimeError
from open_work_hub_api.domains.ai.decision_contracts import ChoiceAnswer
from open_work_hub_api.domains.ai.decisions import ChoiceQuestion, DecisionError, execute_decision
from open_work_hub_api.domains.ai.gateway import AiGatewayPolicyViolation, AiGatewayContextPack, LlmWorkloadContext, execute_llm
from open_work_hub_api.domains.ai.model_settings_service import list_selectable_workload_models
from open_work_hub_api.domains.ai.registry import AiCapabilityRegistry
from open_work_hub_api.domains.auth.models import User

from .schemas import TetrisCandidate, TetrisDecisionRequest, TetrisDecisionResponse, TetrisLanding, TetrisModelOption, TetrisModelsResponse

WORKLOAD_ID = "tetris.play"
GENERATION_WORKLOAD_ID = "tetris.play.generation"
CHOICE_INSTRUCTION = "Choose the first legal landing that best follows the game rules and strategy in state."


def register_ai_capabilities(registry: AiCapabilityRegistry) -> None:
    registry.register_llm_workload(
        workload_id=WORKLOAD_ID,
        task_kind="tetris_play",
        owner_domain="tetris",
        app_id="tetris",
        description="Choose the next Tetris control from the current game state",
        label_key="tetris.AI play decision",
        description_key="tetris.Choose one control from the current board.",
        allow_model_selection=True,
        execution_kind="decision",
        required_capabilities=("decision",),
        default_runtime_adapter="decision",
        allowed_runtime_adapters=("decision",),
        default_route="external",
        allowed_routes=("external",),
    )

    registry.register_llm_workload(
        workload_id=GENERATION_WORKLOAD_ID,
        task_kind="tetris_play_generation", owner_domain="tetris", app_id="tetris",
        description="Choose a Tetris landing with a structured LLM result",
        label_key="tetris.AI play with LLM",
        description_key="tetris.Choose one control from the current board.",
        required_capabilities=("chat", "non_reasoning"),
        default_runtime_adapter="direct_completion",
        allowed_runtime_adapters=("direct_completion",),
        allow_model_selection=True, default_route="external",
        local_max_output_tokens=1024, external_max_output_tokens=1024,
    )


def models(db: Session) -> TetrisModelsResponse:
    options = []
    for kind, workload in (("decision", WORKLOAD_ID), ("generation", GENERATION_WORKLOAD_ID)):
        for item in list_selectable_workload_models(db, workload_id=workload, app_id="tetris"):
            data = asdict(item)
            data["model_id"] = data.pop("id")
            options.append(TetrisModelOption(kind=kind, **data))
    return TetrisModelsResponse(models=options)


def _landing_description(item: TetrisLanding) -> str:
    return (
        f"Place {item.piece} {'using hold' if item.uses_hold else 'without hold'}; "
        f"reserve afterward: {item.hold_after or 'empty'}. "
        f"Clear {item.cleared_lines} lines (send {max(0, item.cleared_lines - 1)} garbage lines in a duel); {item.holes} covered holes; "
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
            f"Total lines over both placements: {item.cleared_lines + future.cleared_lines}. "
            f"Total garbage rows over both placements in a duel: "
            f"{max(0, item.cleared_lines - 1) + max(0, future.cleared_lines - 1)}.]"
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
    state = {
        "game": "Tetris duel" if payload.opponent else "Tetris solo",
        "goal": (
            "Win by making the opponent top out while you remain alive; score alone does not decide the winner."
            if payload.opponent else "Survive and maximize line clears and score, favoring four-line clears."
        ),
        "rules": (
            "The board is 10 columns by 20 rows. Move and rotate falling tetrominoes to fill entire rows; "
            "all completed rows clear together when a piece locks. You lose if the stack overflows or "
            "there is no room for the active or next piece. Hold exchanges the active piece with the reserve once per piece; "
            "empty hold consumes the visible next piece. The engine supplies legal landing outcomes. "
            "Only the chosen landing's first key press runs, then we observe again. Gravity never waits."
        ),
        "strategy": [
            "Prefer a safe four-line clear (Tetris) over smaller clears. Prioritize creating and completing "
            "four-line opportunities across the current and next placements, not merely flattening the stack.",
            "Use the visible current, next and held pieces and the two-placement forecasts. When they support "
            "a four-line setup, preserve an accessible one-column well and save or use an I piece via hold. "
            "Do not block the well, bury holes, or assume an unseen I piece will arrive.",
            "Take smaller clears to prevent imminent top-out or dangerous stacking; survival overrides "
            "waiting for four lines. In a duel, take an immediate smaller attack if it can finish the opponent.",
            "Compare each possible follow-up separately. For similarly safe plans, prefer four-line clears "
            "and greater total garbage sent in a duel, then fewer holes and lower height. A deliberate open "
            "well can justify extra surface roughness. Break equivalent ties with fewer key presses.",
        ],
        "active_piece": payload.active.kind,
        "next_piece": payload.next,
        "hold_piece": payload.hold,
        "can_hold": payload.can_hold,
        "level": payload.level,
    }
    if payload.opponent:
        state["opponent"] = payload.opponent.model_dump()
        state["attack_rules"] = (
            "Both players follow the same rules: clearing 1 line sends no attack; "
            "clearing 2/3/4 lines at once immediately sends 1/2/3 garbage rows to the opponent. "
            "Rows rise from the bottom and push the stack upward; each has one independently random hole. "
            "No attack cancellation or combo bonus. One four-line clear sends 3 rows, while two separate "
            "two-line clears send only 2 total. Favor safe four-line attacks and use the opponent's visible "
            "stack to judge finishing opportunities and the risk of incoming attacks."
        )
    kind = payload.model_choice.kind if payload.model_choice else "decision"
    selection = payload.model_choice.model_id if payload.model_choice else None
    context = LlmWorkloadContext(source=f"api.tetris.play.{kind}", actor_user_id=user.id, app_id="tetris")
    try:
        if kind == "decision":
            result = execute_decision(
                WORKLOAD_ID, context, db, state=state,
                selected_model_id=selection,
                questions={"action": ChoiceQuestion(
                    instructions=CHOICE_INSTRUCTION,
                    options=options,
                )}, source_kinds=("game_state",),
            )
            answer = result.response.answers["action"]
            if not isinstance(answer, ChoiceAnswer) or answer.choice not in choices:
                raise DecisionError("decision_response_invalid")
            choice = answer.choice
            latency = result.latency_ms
            metadata = result.metadata
        else:
            started = monotonic()
            generated = execute_llm(
                GENERATION_WORKLOAD_ID, context, db,
                messages=[],
                context_pack=AiGatewayContextPack(
                    messages=[
                        {"role": "system", "content": CHOICE_INSTRUCTION + " Submit only the structured choice; do not explain."},
                        {"role": "user", "content": json.dumps({"state": state, "options": options}, ensure_ascii=False)},
                    ],
                    source_kinds=("game_state",), content_origin="user_prompt",
                ),
                selected_model_id=selection,
                output_schema={
                    "type": "object", "properties": {"choice": {"type": "string", "enum": list(choices)}},
                    "required": ["choice"], "additionalProperties": False,
                },
                # The common workload policy disables reasoning for every model.
                temperature=0, max_tokens=1024,
                timeout_seconds=30,
            )
            value = generated.completion.structured_output
            if (
                not isinstance(value, dict) or set(value) != {"choice"}
                or not isinstance(value["choice"], str) or value["choice"] not in choices
            ):
                raise DecisionError("decision_response_invalid")
            choice = value["choice"]
            latency = round((monotonic() - started) * 1000)
            metadata = generated.metadata
        return TetrisDecisionResponse(
            action=choices[choice], latency_ms=latency,
            model=metadata.model, provider=metadata.provider, kind=kind,
        )
    except AiGatewayPolicyViolation as exc:
        raise localized_http_exception(status_code=403, code="tetris.ai_blocked") from exc
    except (DecisionError, LlmRuntimeError) as exc:
        if isinstance(exc, LlmRuntimeError):
            if exc.reason_code == "rate_limited":
                raise localized_http_exception(status_code=429, code="tetris.ai_rate_limited") from exc
            if exc.reason_code == "output_limit":
                raise localized_http_exception(status_code=502, code="tetris.ai_output_limit") from exc
            if exc.reason_code == "timeout":
                raise localized_http_exception(status_code=504, code="tetris.ai_timeout") from exc
        raise localized_http_exception(status_code=502, code="tetris.ai_failed") from exc
