import json
from dataclasses import asdict
from time import monotonic

from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.core.llm_errors import LlmRuntimeError
from miy_api.domains.ai.decision_contracts import ChoiceAnswer
from miy_api.domains.ai.decisions import ChoiceQuestion, DecisionError, execute_decision
from miy_api.domains.ai.gateway import AiGatewayPolicyViolation, AiGatewayContextPack, LlmWorkloadContext, execute_llm
from miy_api.domains.ai.model_settings_service import list_selectable_workload_models
from miy_api.domains.ai.registry import AiCapabilityRegistry
from miy_api.domains.auth.models import User

from .schemas import TetrisCandidate, TetrisDecisionRequest, TetrisDecisionResponse, TetrisLanding, TetrisModelOption, TetrisModelsResponse, TetrisObservation, TetrisPlacement

WORKLOAD_ID = "tetris.play"
GENERATION_WORKLOAD_ID = "tetris.play.generation"
CHOICE_INSTRUCTION = (
    "Choose one landing to win, following state rules. Use 9-0 Tetris stacking while safe: "
    "build four rows around one open column and save I to attack. "
    "A safe setup is better than a single clear or merely lowering the board. "
    "Switch to survival clears for actual top-out danger, or attack immediately to finish the opponent."
)
# Keep the same choice budget for every model, including native endpoints that
# accept at most 26 options. The engine orders candidates by immediate/future value.
MAX_MODEL_CANDIDATES = 26


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
    shape = "/".join("".join(map(str, row)) for row in item.target.shape)
    wells = ",".join(
        f"{well.column}:{well.depth}:{well.ready_rows}:{well.filled_cells}"
        for well in item.wells
    ) or "-"
    return (
        f"piece={item.piece} hold={int(item.uses_hold)} reserve={item.hold_after or '-'} "
        f"x={item.target.x} y={item.target.y} shape={shape} "
        f"clear={item.cleared_lines} attack={max(0, item.cleared_lines - 1)} "
        f"holes={item.holes} height={item.max_height} sum_height={item.aggregate_height} "
        f"roughness={item.bumpiness} wells={wells} keys={item.key_presses}"
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
    candidates = payload.candidates[:MAX_MODEL_CANDIDATES]
    choices = {f"option_{index}": item for index, item in enumerate(candidates)}
    options = {
        f"option_{index}": _candidate_description(item)
        for index, item in enumerate(candidates)
    }
    if len(options) == 1:
        choices["wait"] = None
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
            "One decision commits to one landing. The engine follows a legal path one key at a time; "
            "reobserve after placement or if the plan becomes invalid. Gravity continues during requests and movement."
        ),
        "strategy": [
            "Avoid actual top-out danger (blocked spawn, a stack near the spawn area, or buried holes "
            "preventing recovery). A modest height increase on a low, hole-free board is not such danger.",
            "Build for repeated Tetris (4-line clears), not only immediate clears. "
            "On a low, hole-free board, leave one column open and fill the other nine across four rows. "
            "Prefer an edge well when starting; preserve an existing useful well rather than switching sides.",
            "Prepare this stack over several pieces, even before I is visible; keep it modest while waiting. "
            "Reserve a visible I for the four-row well instead of spending it just to flatten the board. "
            "Use current/next/hold and each then alternative; do not assume hidden pieces or an I arrival time.",
            "Do not cover the well or bury holes. While safe, preserve attack preparation instead of "
            "taking a single clear for no attack. Accept a higher, rougher stack to increase well ready_rows "
            "and filled_cells; do not optimize minimum height or score at the expense of the setup. "
            "Abandon the setup to avoid top-out or finish the opponent.",
            "Among similarly safe plans: Tetris > total attack > fewer holes > lower height. "
            "A deliberate well may increase roughness. Fewer keys only breaks otherwise equal ties.",
        ],
        "legend": (
            "Boards/shapes: rows top-down, columns left-right; x/y are zero-based. "
            "Board '.'=empty, G=garbage, other letters=locked tetrominoes; active is separate. "
            "Shape 1=occupied, 0=empty. Candidates are engine-computed legal landings. "
            "Each landing's x/y and slash-separated shape give its exact pose before rows clear; "
            "then poses apply after now's placement and line clears. "
            "now=first landing; then=alternative second landings (choose at most one). "
            "hold=1 swaps; reserve=hold afterward ('-' empty). next/spawn_blocked unknown=no forecast; "
            "spawn_blocked=1 means top-out. clear=lines removed; attack=garbage sent in a duel; "
            "holes=covered empty cells; height=max column height; sum_height=sum of column heights; "
            "roughness=sum of adjacent height differences; keys=inputs to complete that landing. "
            "wells=comma-separated column:depth:ready_rows:filled_cells after that landing ('-' none). "
            "Each well is a one-column shaft open from above, bounded by neighbors or a board edge. "
            "Depth is measured from its floor to the lower adjacent surface. "
            "In the four rows just above its floor, ready_rows have all other nine cells filled; "
            "filled_cells counts those other cells (0..36). Four ready rows enable a vertical-I Tetris. "
            "These are board geometry, not a guarantee that the next I can reach it before gravity. "
            "Deeper than four is not extra preparation; height/holes still measure danger. "
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
        selected = choices[choice]
        return TetrisDecisionResponse(
            action=selected.action if selected else "wait",
            placement=TetrisPlacement(target=selected.target, uses_hold=selected.uses_hold) if selected else None,
            latency_ms=latency,
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
