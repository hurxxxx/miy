"""Native decision transport. No chat emulation, retries or fallback.

OpenRouter's public alpha Decisions endpoint is not implemented by the pinned
OpenAI SDK chat surface. This narrow HTTP adapter owns that documented wire API.
"""

from __future__ import annotations

import json
from time import monotonic
from typing import Protocol

import httpx

from mty_api.core.llm import LlmPoolConfig
from mty_api.core.llm_provider_registry import llm_provider_descriptor
from mty_api.domains.ai.decision_contracts import (
    MAX_DECISION_RESPONSE_BYTES,
    DECISION_TIMEOUT_SECONDS,
    ChoiceQuestion,
    ScoreQuestion,
    DecisionInput,
    DecisionResponse,
    DecisionError,
)


class DecisionAdapter(Protocol):
    def validate_endpoint(self, endpoint: str) -> None: ...

    def execute(self, config: LlmPoolConfig, request: DecisionInput) -> DecisionResponse: ...


class OpenRouterDecisionAdapter:
    def validate_endpoint(self, endpoint: str) -> None:
        # This key is never forwarded to an arbitrary gateway or redirect.
        if endpoint.rstrip("/") != "https://openrouter.ai/api/v1":
            raise DecisionError("decision_endpoint_unsupported")

    def execute(self, config: LlmPoolConfig, request: DecisionInput) -> DecisionResponse:
        self.validate_endpoint(config.base_url)
        questions = {}
        for key, question in request.questions.items():
            if isinstance(question, ChoiceQuestion):
                criteria = question.options
                kind = "choice"
            elif isinstance(question, ScoreQuestion):
                criteria = question.levels
                kind = "score"
            else:
                criteria = {"true": question.true_description, "false": question.false_description}
                kind = "noul"
            questions[key] = {
                "type": kind,
                "instructions": question.instructions,
                "criteria": criteria,
            }
        started = monotonic()
        try:
            with httpx.Client(timeout=DECISION_TIMEOUT_SECONDS, follow_redirects=False) as client:
                with client.stream(
                    "POST",
                    "https://openrouter.ai/api/alpha/decisions",
                    headers={"Authorization": f"Bearer {config.api_key}"},
                    json={
                        "model": config.default_model,
                        "state": request.state,
                        "questions": questions,
                    },
                ) as response:
                    if response.status_code != 200:
                        raise DecisionError(f"decision_http_{response.status_code}")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if monotonic() - started > DECISION_TIMEOUT_SECONDS:
                            raise DecisionError("decision_timeout")
                        data.extend(chunk)
                        if len(data) > MAX_DECISION_RESPONSE_BYTES:
                            raise DecisionError("decision_response_too_large")
            payload = json.loads(data)
            answers = payload["answers"]
            for answer in answers.values():
                if answer.get("type") == "noul":
                    answer["type"] = "probability"
                    answer["probability"] = answer.pop("noul")
                # Legend repeats caller-supplied score descriptions; do not expose it.
                answer.pop("legend", None)
            result = DecisionResponse.model_validate(
                {
                    "answers": answers,
                    "model": payload["model"],
                    "request_id": payload.get("id"),
                    "usage": payload.get("usage") or {},
                }
            )
            result.validate_answers(request)
            return result
        except DecisionError:
            raise
        except httpx.TimeoutException:
            raise DecisionError("decision_timeout") from None
        except httpx.HTTPError:
            raise DecisionError("decision_unavailable") from None
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            raise DecisionError("decision_response_invalid") from None


_adapters: dict[str, DecisionAdapter] = {"openrouter_decisions": OpenRouterDecisionAdapter()}


def register_decision_adapter(adapter_id: str, adapter: DecisionAdapter) -> None:
    """Composition/test seam, never supplied by a workload caller."""
    if not adapter_id or adapter_id in _adapters:
        raise ValueError("Decision adapter already registered or empty")
    _adapters[adapter_id] = adapter


def get_decision_adapter(provider: str) -> DecisionAdapter:
    descriptor = llm_provider_descriptor(provider)
    adapter = _adapters.get(descriptor.decision_adapter_id) if descriptor else None
    if adapter is None:
        raise DecisionError("decision_adapter_unavailable")
    return adapter
