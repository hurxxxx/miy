from typing import Literal

LlmFailureReason = Literal["rate_limited", "output_limit", "timeout"]


class LlmRuntimeError(RuntimeError):
    """Provider-neutral failure exposed by high-level LLM helpers."""

    def __init__(self, message: str, *, reason_code: LlmFailureReason | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class LlmProviderError(LlmRuntimeError):
    """Provider or provider-SDK failure normalized at the adapter seam."""

    def __init__(
        self,
        message: str,
        *,
        pool: str | None = None,
        provider: str | None = None,
        reason_code: LlmFailureReason | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code)
        self.pool = pool
        self.provider = provider
