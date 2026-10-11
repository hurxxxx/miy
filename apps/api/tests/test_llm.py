from types import SimpleNamespace

import pytest

from miy_api.core import llm, llm_official_providers
from miy_api.core.settings import get_settings

LLM_ENV_KEYS = (
    "MIY_LLM_LOCAL_PROVIDER",
    "MIY_LLM_LOCAL_BASE_URL",
    "MIY_LLM_LOCAL_API_KEY",
    "MIY_LLM_LOCAL_DEFAULT_MODEL",
    "MIY_LLM_LOCAL_CANONICAL_MODEL",
    "MIY_LLM_LOCAL_LONG_GENERATION_TIMEOUT_SECONDS",
    "MIY_LLM_EXTERNAL_ALLOWED_PROVIDERS",
    "MIY_LLM_EXTERNAL_LONG_GENERATION_TIMEOUT_SECONDS",
    "MIY_LLM_OPENAI_BASE_URL",
    "MIY_LLM_OPENAI_DEFAULT_MODEL",
    "MIY_LLM_OPENAI_CANONICAL_MODEL",
    "MIY_LLM_ANTHROPIC_BASE_URL",
    "MIY_LLM_ANTHROPIC_DEFAULT_MODEL",
    "MIY_LLM_ANTHROPIC_CANONICAL_MODEL",
    "MIY_LLM_GEMINI_BASE_URL",
    "MIY_LLM_GEMINI_DEFAULT_MODEL",
    "MIY_LLM_GEMINI_CANONICAL_MODEL",
    "MIY_LLM_REQUEST_TIMEOUT_SECONDS",
    "MIY_LLM_HEALTHCHECK_ON_STARTUP",
    "MIY_LLM_REQUIRED",
)


class FakeModels:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def list(self) -> SimpleNamespace:
        return SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in self._ids])


class FakeChatCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            model=str(kwargs["model"]),
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class FakeClient:
    def __init__(self, ids: list[str], content: str = "ok") -> None:
        self.models = FakeModels(ids)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(content))


def _clear_pool_client_cache() -> None:
    cache_clear = getattr(llm.get_pool_client, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    async_cache_clear = getattr(llm.get_async_pool_client, "cache_clear", None)
    if async_cache_clear is not None:
        async_cache_clear()


def _admin_resolved_local_config() -> llm.LlmPoolConfig:
    return llm.LlmPoolConfig(
        pool="local",
        provider="vllm",
        base_url="http://local-llm:8000/v1",
        api_key="",
        default_model="local/current-moe-test-model",
        canonical_model="local/current-moe-test-model",
        healthcheck_timeout_seconds=5,
        long_generation_timeout_seconds=30,
        requires_credentials=False,
    )


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "MIY_POSTGRES_DSN",
        "postgresql+psycopg://miy_test:miy_test@127.0.0.1:5432/miy_test",
    )
    get_settings.cache_clear()
    _clear_pool_client_cache()
    yield
    get_settings.cache_clear()
    _clear_pool_client_cache()


def test_official_anthropic_stream_emits_deltas_usage_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: dict[str, object] = {}

    class _FakeAnthropicStream:
        text_stream = iter(["hel", "lo"])

        def get_final_message(self) -> SimpleNamespace:
            return SimpleNamespace(
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=2, output_tokens=3),
            )

    class _FakeAnthropicStreamManager:
        def __enter__(self) -> _FakeAnthropicStream:
            return _FakeAnthropicStream()

        def __exit__(self, *_args: object) -> None:
            return None

    class _FakeAnthropicMessages:
        def stream(self, **request: object) -> _FakeAnthropicStreamManager:
            captured_request.update(request)
            return _FakeAnthropicStreamManager()

    class _FakeAnthropicClient:
        messages = _FakeAnthropicMessages()

    monkeypatch.setattr(
        llm_official_providers,
        "_anthropic_client",
        lambda config, timeout_seconds: _FakeAnthropicClient(),
    )

    chunks = list(
        llm_official_providers.stream_official_provider_chat(
            SimpleNamespace(
                provider="anthropic",
                base_url="",
                api_key="test-key",
                default_model="claude-test",
            ),
            {
                "model": "claude-test",
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "hello"},
                ],
                "max_tokens": 11,
                "temperature": 0.2,
            },
            timeout_seconds=7,
        )
    )

    assert captured_request == {
        "model": "claude-test",
        "max_tokens": 11,
        "messages": [{"role": "user", "content": "hello"}],
        "system": "system",
        "temperature": 0.2,
    }
    assert [(chunk.kind, chunk.text, chunk.usage, chunk.finish_reason) for chunk in chunks] == [
        ("content", "hel", None, None),
        ("content", "lo", None, None),
        (
            "usage",
            None,
            {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            None,
        ),
        ("done", None, None, "stop"),
    ]


def test_official_gemini_stream_emits_deltas_usage_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: dict[str, object] = {}

    class _FakeGeminiModels:
        def generate_content_stream(self, **request: object):
            captured_request.update(request)
            yield SimpleNamespace(text="hel", usage_metadata=None, candidates=[])
            yield SimpleNamespace(
                text="lo",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=2,
                    candidates_token_count=3,
                    total_token_count=5,
                ),
                candidates=[SimpleNamespace(finish_reason="STOP")],
            )

    class _FakeGeminiClient:
        models = _FakeGeminiModels()

        def __enter__(self) -> "_FakeGeminiClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        llm_official_providers,
        "_gemini_client",
        lambda config, timeout_seconds: _FakeGeminiClient(),
    )

    chunks = list(
        llm_official_providers.stream_official_provider_chat(
            SimpleNamespace(
                provider="gemini",
                base_url="",
                api_key="test-key",
                default_model="gemini-test",
            ),
            {
                "model": "gemini-test",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 11,
                "temperature": 0.2,
            },
            timeout_seconds=7,
        )
    )

    assert captured_request["model"] == "gemini-test"
    assert captured_request["contents"] == "user: hello"
    assert getattr(captured_request["config"], "max_output_tokens") == 11
    assert [(chunk.kind, chunk.text, chunk.usage, chunk.finish_reason) for chunk in chunks] == [
        ("content", "hel", None, None),
        ("content", "lo", None, None),
        (
            "usage",
            None,
            {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            None,
        ),
        ("done", None, None, "stop"),
    ]
