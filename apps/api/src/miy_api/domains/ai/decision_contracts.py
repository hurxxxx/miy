"""Bounded, provider-neutral contracts for semantic decisions.

A confidence is provider-reported evidence, not a calibrated safety guarantee.
Apps own thresholds, abstention, resource ACL and approval of resulting actions.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MAX_DECISION_BYTES = 262_144
MAX_DECISION_RESPONSE_BYTES = 262_144
DECISION_TIMEOUT_SECONDS = 30.0
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")]
Description = Annotated[str, Field(min_length=1, max_length=4096)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class DecisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ChoiceQuestion(DecisionContract):
    type: Literal["choice"] = "choice"
    instructions: Description
    options: dict[Identifier, Description] = Field(min_length=2, max_length=32)


class ScoreQuestion(DecisionContract):
    type: Literal["score"] = "score"
    instructions: Description
    levels: list[Description] = Field(min_length=2, max_length=32)


class ProbabilityQuestion(DecisionContract):
    type: Literal["probability"] = "probability"
    instructions: Description
    true_description: Description
    false_description: Description


DecisionQuestion = Annotated[
    ChoiceQuestion | ScoreQuestion | ProbabilityQuestion, Field(discriminator="type")
]


class DecisionInput(DecisionContract):
    state: str | dict[str, JsonValue] | list[JsonValue]
    questions: dict[Identifier, DecisionQuestion] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_payload(self) -> DecisionInput:
        try:
            encoded = json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False)
        except (ValueError, RecursionError):
            raise ValueError("decision_input_invalid") from None
        if len(encoded.encode("utf-8")) > MAX_DECISION_BYTES:
            raise ValueError("decision_input_too_large")
        return self


class ChoiceAnswer(DecisionContract):
    type: Literal["choice"] = "choice"
    choice: str
    confidence: Probability | None = None
    probabilities: dict[str, Probability]


class ScoreAnswer(DecisionContract):
    type: Literal["score"] = "score"
    score: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    confidence: Probability | None = None
    probabilities: dict[str, Probability]


class ProbabilityAnswer(DecisionContract):
    type: Literal["probability"] = "probability"
    probability: Probability


DecisionAnswer = Annotated[
    ChoiceAnswer | ScoreAnswer | ProbabilityAnswer, Field(discriminator="type")
]


class DecisionUsage(DecisionContract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class DecisionResponse(DecisionContract):
    answers: dict[str, DecisionAnswer]
    model: str = Field(min_length=1, max_length=256)
    request_id: str | None = Field(default=None, max_length=256)
    usage: DecisionUsage = Field(default_factory=DecisionUsage)

    def validate_answers(self, request: DecisionInput) -> None:
        if self.answers.keys() != request.questions.keys():
            raise ValueError("decision_answer_keys_mismatch")
        for key, question in request.questions.items():
            answer = self.answers[key]
            if question.type != answer.type:
                raise ValueError("decision_answer_type_mismatch")
            if isinstance(question, ProbabilityQuestion):
                continue
            if not isinstance(answer, (ChoiceAnswer, ScoreAnswer)):
                raise ValueError("decision_answer_type_mismatch")
            expected = (
                set(question.options)
                if isinstance(question, ChoiceQuestion)
                else {str(i) for i in range(len(question.levels))}
            )
            if (
                set(answer.probabilities) != expected
                or abs(sum(answer.probabilities.values()) - 1) > 0.01
            ):
                raise ValueError("decision_distribution_invalid")
            if isinstance(answer, ChoiceAnswer) and answer.choice not in expected:
                raise ValueError("decision_choice_invalid")
            if (
                isinstance(answer, ScoreAnswer)
                and isinstance(question, ScoreQuestion)
                and answer.score > len(question.levels) - 1
            ):
                raise ValueError("decision_score_invalid")


class DecisionError(RuntimeError):
    """Stable safe error code; provider bodies and user inputs are never included."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
