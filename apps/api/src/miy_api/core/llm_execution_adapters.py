from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAIError,
)

from miy_api.core.i18n import LocalizedApiMessage
from miy_api.core.llm_adapters import StreamChunk, get_stream_adapter
from miy_api.core.llm_errors import LlmFailureReason, LlmProviderError
from miy_api.core.llm_official_providers import (
    check_official_provider_health,
    complete_official_provider_chat,
    stream_official_provider_chat,
)
from miy_api.core.llm_provider_registry import (
    external_llm_provider_descriptor,
    external_llm_provider_ids,
)

LlmExecutionHealthStatus = Literal["ready", "unavailable", "model_missing"]
SyncPoolClientFactory = Callable[[str, str | None], Any]
AsyncPoolClientFactory = Callable[[str, str | None], Any]


class LlmExecutionConfig(Protocol):
    pool: str
    provider: str
    base_url: str
    api_key: str
    default_model: str
    canonical_model: str
    healthcheck_timeout_seconds: float
    long_generation_timeout_seconds: float


class LlmExecutionAdapter(Protocol):
    adapter_id: str
    supports_tools: bool

    def complete(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
    ) -> Any: ...

    async def stream(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
        async_client_factory: AsyncPoolClientFactory,
    ) -> AsyncIterator[StreamChunk]: ...

    def check_health(
        self,
        config: LlmExecutionConfig,
        *,
        sync_client_factory: SyncPoolClientFactory,
    ) -> "LlmExecutionHealthResult": ...


@dataclass(frozen=True)
class LlmExecutionHealthResult:
    status: LlmExecutionHealthStatus
    detail: str | LocalizedApiMessage | None = None


_adapters_by_key: dict[tuple[str, str | None], LlmExecutionAdapter] = {}
_SYNC_ITERATOR_DONE = object()


def register_llm_execution_adapter(
    *,
    pool: str,
    provider: str | None,
    adapter: LlmExecutionAdapter,
) -> None:
    key = (_normalize_key(pool), _normalize_optional_key(provider))
    if key in _adapters_by_key:
        raise ValueError(f"LLM execution adapter already registered for {key}")
    _adapters_by_key[key] = adapter


def select_llm_execution_adapter(
    pool: str,
    provider: str | None,
) -> LlmExecutionAdapter:
    ensure_default_llm_execution_adapters_registered()
    normalized_pool = _normalize_key(pool)
    normalized_provider = _normalize_optional_key(provider)
    adapter = _adapters_by_key.get((normalized_pool, normalized_provider))
    if adapter is not None:
        return adapter
    if _can_use_pool_fallback(normalized_pool, normalized_provider):
        adapter = _adapters_by_key.get((normalized_pool, None))
        if adapter is not None:
            return adapter
    raise ValueError(
        f"no LLM execution adapter registered for {normalized_pool}/{normalized_provider}"
    )


def supports_tool_calling(pool: str, provider: str | None = None) -> bool:
    return select_llm_execution_adapter(pool, provider).supports_tools


def llm_execution_adapter_keys() -> tuple[str, ...]:
    ensure_default_llm_execution_adapters_registered()
    return tuple(sorted(f"{pool}:{provider or '*'}" for pool, provider in _adapters_by_key))


def reset_llm_execution_adapters() -> None:
    _adapters_by_key.clear()


def ensure_default_llm_execution_adapters_registered() -> None:
    openai_compatible = OpenAICompatibleLlmExecutionAdapter()
    official = OfficialProviderLlmExecutionAdapter()
    _register_default_adapter(
        pool="local",
        provider=None,
        adapter=openai_compatible,
    )
    _register_default_adapter(
        pool="external",
        provider=None,
        adapter=openai_compatible,
    )
    for provider in external_llm_provider_ids():
        descriptor = external_llm_provider_descriptor(provider)
        adapter = (
            openai_compatible
            if descriptor is not None and descriptor.execution_adapter_id == "openai_compatible"
            else official
            if descriptor is not None and descriptor.execution_adapter_id == "official"
            else None
        )
        if adapter is None:
            continue
        _register_default_adapter(
            pool="external",
            provider=provider,
            adapter=adapter,
        )


class OpenAICompatibleLlmExecutionAdapter:
    adapter_id = "openai_compatible"
    supports_tools = True

    def complete(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
    ) -> Any:
        client = sync_client_factory(
            config.pool,
            config.provider if config.pool == "external" else None,
        ).with_options(timeout=timeout_seconds)
        try:
            return client.chat.completions.create(**payload)
        except OpenAIError as error:
            raise _provider_error(config, error) from error

    async def stream(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
        async_client_factory: AsyncPoolClientFactory,
    ) -> AsyncIterator[StreamChunk]:
        del sync_client_factory
        adapter = get_stream_adapter(config.pool, config.provider)
        client = async_client_factory(
            config.pool,
            config.provider if config.pool == "external" else None,
        ).with_options(timeout=timeout_seconds)
        try:
            async for chunk in adapter.open_stream(client, payload):
                yield chunk
        except OpenAIError as error:
            raise _provider_error(config, error) from error

    def check_health(
        self,
        config: LlmExecutionConfig,
        *,
        sync_client_factory: SyncPoolClientFactory,
    ) -> LlmExecutionHealthResult:
        try:
            models = sync_client_factory(
                config.pool,
                config.provider if config.pool == "external" else None,
            ).models.list()
        except (APIConnectionError, APITimeoutError) as error:
            return LlmExecutionHealthResult(
                status="unavailable",
                detail=LocalizedApiMessage(
                    code="llm.provider_unavailable",
                    params={"reason": str(error)},
                ),
            )
        except APIStatusError as error:
            return LlmExecutionHealthResult(
                status="unavailable",
                detail=LocalizedApiMessage(
                    code="llm.provider_status_error",
                    params={"status_code": error.status_code, "message": error.message},
                ),
            )
        except OpenAIError as error:
            return LlmExecutionHealthResult(
                status="unavailable",
                detail=LocalizedApiMessage(
                    code="llm.provider_unavailable",
                    params={"reason": str(error)},
                ),
            )

        model_ids = {model.id for model in models.data}
        if config.default_model not in model_ids:
            return LlmExecutionHealthResult(
                status="model_missing",
                detail=LocalizedApiMessage(
                    code="llm.configured_model_missing",
                    params={"models": ", ".join(sorted(model_ids))},
                ),
            )
        return LlmExecutionHealthResult(status="ready")


class DirectCompletionAdapter:
    """One bounded text/JSON completion for explicitly opted-in workloads.

    This composes the existing provider transport; it owns no agent/tool loop,
    model selection, retry, fallback or audit. The common gateway owns those
    boundaries and validates workload admission before reaching this adapter.
    """

    adapter_id = "direct_completion"

    def complete(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        output_schema: dict[str, Any] | None,
        reasoning_effort: str,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
    ) -> dict[str, Any]:
        def failure(reason: str, code: LlmFailureReason | None = None) -> LlmProviderError:
            return LlmProviderError(
                f"Direct completion: {reason}", pool=config.pool, provider=config.provider,
                reason_code=code,
            )

        transport = select_llm_execution_adapter(config.pool, config.provider)
        if transport.adapter_id != "openai_compatible":
            raise failure("unsupported provider transport")
        if any(payload.get(key) is not None for key in (
            "tools", "tool_choice", "parallel_tool_calls", "functions", "function_call"
        )) or payload.get("stream"):
            raise failure("tools and streaming are unsupported")
        if set(payload.get("extra_body") or {}).intersection({
            "model", "models", "messages", "max_tokens", "max_completion_tokens",
            "response_format", "stream", "tools", "tool_choice", "parallel_tool_calls",
            "functions", "function_call", "provider", "plugins",
        }):
            raise failure("transport overrides are unsupported")

        validator = None
        request = dict(payload)
        if output_schema is not None:
            # Schema input is registered server code, but validation must still
            # never fetch remote references from the API host.
            def check_references(value: Any) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in {"$ref", "$dynamicRef"} and (
                            not isinstance(child, str) or not child.startswith("#")
                        ):
                            raise failure("only local schema references are supported")
                        check_references(child)
                elif isinstance(value, list):
                    for child in value:
                        check_references(child)

            check_references(output_schema)
            def deny_retrieval(uri: str) -> Any:
                raise NoSuchResource(ref=uri)

            try:
                Draft202012Validator.check_schema(output_schema)
                validator = Draft202012Validator(
                    output_schema, registry=Registry(retrieve=deny_retrieval)
                )
            except SchemaError:
                raise failure("invalid output schema") from None
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "workload_result", "strict": True, "schema": output_schema},
            }
        if config.provider == "openrouter":
            request["extra_body"] = {
                **(request.get("extra_body") or {}),
                # Hermes receives the resolved effort separately. Its shared
                # payload profile omits it, so the direct runtime must encode
                # the admitted value in OpenRouter's public request contract.
                "reasoning": {"effort": reasoning_effort},
                "provider": {"require_parameters": True, "allow_fallbacks": False},
            }

        try:
            response = transport.complete(
                config, request, timeout_seconds=timeout_seconds,
                sync_client_factory=sync_client_factory,
            )
        except LlmProviderError as error:
            # Provider error bodies can echo prompts/credentials. Keep the
            # common audit safe while retaining a useful error category.
            category = "provider request failed"
            code: LlmFailureReason | None = None
            if isinstance(error.__cause__, APITimeoutError):
                category = "provider timeout"
                code = "timeout"
            elif isinstance(error.__cause__, APIStatusError):
                category = f"provider HTTP {error.__cause__.status_code}"
                if error.__cause__.status_code == 429:
                    code = "rate_limited"
            raise failure(category, code) from None
        try:
            result = response if isinstance(response, dict) else response.model_dump(mode="json")
            choice = result["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if choice.get("finish_reason") == "length":
                raise failure("output token limit reached", "output_limit")
            if message.get("refusal"):
                raise failure("response refused")
            if (
                choice.get("finish_reason") != "stop"
                or message.get("tool_calls") or message.get("function_call")
                or not isinstance(content, str) or not content.strip()
            ):
                raise ValueError("incomplete response")
            if validator is not None:
                def reject_constant(_value: str) -> Any:
                    raise ValueError("non-JSON numeric constant")

                def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                    obj: dict[str, Any] = {}
                    for key, value in pairs:
                        if key in obj:
                            raise ValueError("duplicate key")
                        obj[key] = value
                    return obj

                structured = json.loads(
                    content, parse_constant=reject_constant, object_pairs_hook=unique_object
                )
                validator.validate(structured)
                result = {**result, "structured_output": structured}
            return result
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError, Unresolvable):
            raise failure("invalid or incomplete response") from None


class OfficialProviderLlmExecutionAdapter:
    adapter_id = "official_provider"
    supports_tools = False

    def complete(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
    ) -> Any:
        del sync_client_factory
        try:
            return complete_official_provider_chat(
                config,
                payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as error:
            raise _provider_error(config, error) from error

    async def stream(
        self,
        config: LlmExecutionConfig,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        sync_client_factory: SyncPoolClientFactory,
        async_client_factory: AsyncPoolClientFactory,
    ) -> AsyncIterator[StreamChunk]:
        del sync_client_factory, async_client_factory
        stream = stream_official_provider_chat(
            config,
            payload,
            timeout_seconds=timeout_seconds,
        )
        try:
            async for chunk in _iterate_sync_stream(stream):
                yield chunk
        except Exception as error:
            raise _provider_error(config, error) from error

    def check_health(
        self,
        config: LlmExecutionConfig,
        *,
        sync_client_factory: SyncPoolClientFactory,
    ) -> LlmExecutionHealthResult:
        del sync_client_factory
        health = check_official_provider_health(
            config,
            timeout_seconds=config.healthcheck_timeout_seconds,
        )
        return LlmExecutionHealthResult(
            status=health.status,
            detail=health.detail,
        )


def _register_default_adapter(
    *,
    pool: str,
    provider: str | None,
    adapter: LlmExecutionAdapter,
) -> None:
    key = (_normalize_key(pool), _normalize_optional_key(provider))
    if key in _adapters_by_key:
        return
    register_llm_execution_adapter(pool=pool, provider=provider, adapter=adapter)


def _normalize_key(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_optional_key(value: str | None) -> str | None:
    normalized = _normalize_key(value or "")
    return normalized or None


def _can_use_pool_fallback(pool: str, provider: str | None) -> bool:
    if provider is None or pool != "external":
        return True
    descriptor = external_llm_provider_descriptor(provider)
    return bool(descriptor and descriptor.openai_compatible)


def _provider_error(
    config: LlmExecutionConfig,
    error: Exception,
) -> LlmProviderError:
    return LlmProviderError(
        str(error),
        pool=config.pool,
        provider=config.provider,
    )


async def _iterate_sync_stream(stream: Any) -> AsyncIterator[StreamChunk]:
    try:
        while True:
            chunk = await asyncio.to_thread(_next_sync_stream_chunk, stream)
            if chunk is _SYNC_ITERATOR_DONE:
                break
            yield chunk
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


def _next_sync_stream_chunk(stream: Any) -> StreamChunk | object:
    try:
        return next(stream)
    except StopIteration:
        return _SYNC_ITERATOR_DONE


__all__ = [
    "LlmExecutionAdapter",
    "LlmExecutionHealthResult",
    "OfficialProviderLlmExecutionAdapter",
    "OpenAICompatibleLlmExecutionAdapter",
    "ensure_default_llm_execution_adapters_registered",
    "llm_execution_adapter_keys",
    "register_llm_execution_adapter",
    "reset_llm_execution_adapters",
    "select_llm_execution_adapter",
    "supports_tool_calling",
]
