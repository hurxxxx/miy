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

from .schemas import TetrisCandidate, TetrisDecisionRequest, TetrisDecisionResponse, TetrisLanding, TetrisModelOption, TetrisModelsResponse, TetrisObservation

WORKLOAD_ID = "tetris.play"
GENERATION_WORKLOAD_ID = "tetris.play.generation"
CHOICE_INSTRUCTION = "Choose the best first placement using the rules and priorities in state."


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
        f"piece={item.piece} hold={int(item.uses_hold)} reserve={item.hold_after or '-'} "
        f"clear={item.cleared_lines} attack={max(0, item.cleared_lines - 1)} "
        f"holes={item.holes} height={item.max_height} sum_height={item.aggregate_height} "
        f"roughness={item.bumpiness} keys={item.key_presses}"
    )


def _candidate_description(item: TetrisCandidate) -> str:
    blocked = "unknown" if item.next_spawn_blocked is None else str(int(item.next_spawn_blocked))
    description = (
        f"now: {_landing_description(item)}\n"
        f"next={item.next_piece or 'unknown'} spawn_blocked={blocked}"
    )
    for future in item.follow_ups:
        description += (
            f"\nthen: {_landing_description(future)} "
            f"total_clear={item.cleared_lines + future.cleared_lines} "
            f"total_attack={max(0, item.cleared_lines - 1) + max(0, future.cleared_lines - 1)}"
        )
    return description


def _observation(item: TetrisObservation) -> dict:
    # Preserve every public cell and the active piece's exact pose; row strings
    # avoid repeating JSON nulls and nested arrays in either model interface.
    data = item.model_dump(include=set(TetrisObservation.model_fields))
    data["board"] = [
        "".join("." if cell is None else "G" if cell == "garbage" else cell for cell in row)
        for row in item.board
    ]
    data["active"]["shape"] = ["".join(map(str, row)) for row in item.active.shape]
    return data


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
            "Make the opponent top out; stay alive. Score does not decide the winner."
            if payload.opponent else "Survive; maximize clears and score."
        ),
        "rules": (
            "10x20 Tetris; 7-bag; move/rotate/hard drop; full rows clear on lock. "
            "Hold once per piece; empty hold consumes next. "
            "Top-out loss: stack overflow or active/next piece cannot fit. "
            "One decision = first key press only, then reobserve. Gravity continues during requests."
        ),
        "strategy": [
            "Survival first; smaller clears for danger, or an immediate winning attack.",
            "Prefer safe Tetris (4-line clears). Plan with current/next/hold and each then alternative.",
            "For a visible Tetris setup, keep an accessible one-column well and reserve/use I. "
            "Do not block the well, bury holes, or assume hidden pieces.",
            "Among similarly safe plans: Tetris > total attack > fewer holes > lower height. "
            "A deliberate well may increase roughness. Fewer keys only breaks otherwise equal ties.",
        ],
        "legend": (
            "Boards/shapes: rows top-down, columns left-right; x/y are zero-based. "
            "Board '.'=empty, G=garbage, other letters=locked tetrominoes; active is separate. "
            "Shape 1=occupied, 0=empty. Candidates are engine-computed legal landings. "
            "now=first landing; then=alternative second landings (choose at most one). "
            "hold=1 swaps; reserve=hold afterward ('-' empty). next/spawn_blocked unknown=no forecast; "
            "spawn_blocked=1 means top-out. clear=lines removed; attack=garbage sent in a duel; "
            "holes=covered empty cells; height=max column height; sum_height=sum of column heights; "
            "roughness=sum of adjacent height differences; keys=inputs to complete that landing. "
            "total_clear/total_attack=now plus that then, never all alternatives together."
        ),
        "self": _observation(payload),
    }
    if payload.opponent:
        state["opponent"] = _observation(payload.opponent)
        state["attack_rules"] = (
            "Both players: clear 1/2/3/4 -> attack 0/1/2/3. "
            "Garbage rises immediately; 1 independently random hole per row. "
            "No cancellation, combo or B2B bonuses. "
            "One Tetris sends 3; two doubles send 2 total. "
            "Use the opponent's board to assess finishing attacks and incoming danger."
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
