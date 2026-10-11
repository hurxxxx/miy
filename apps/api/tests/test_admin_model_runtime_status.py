from __future__ import annotations

from types import SimpleNamespace
import json

import httpx
import pytest

from miy_api.core.settings import Settings
from miy_api.domains.admin.model_runtime_status_service import (
    collect_model_runtime_status,
)


def _runtime_db(**overrides):
    row = SimpleNamespace(
        provider_kind="local",
        display_name="Local LLM",
        enabled=True,
        endpoint_url="http://local-llm:8000/v1",
        api_key_ciphertext="test-ciphertext",
        default_model_id=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return SimpleNamespace(
        get=lambda *_args: row,
        scalars=lambda *_args: SimpleNamespace(all=lambda: ["local"]),
        rollback=lambda: None,
    )


def _settings(**overrides: object) -> Settings:
    values = {
        "postgres_dsn": ("postgresql+psycopg://miy_test:miy_test@127.0.0.1:5432/miy_test"),
        "inference_gateway_base_url": "http://current-server:18080",
        "inference_gateway_api_key": "gateway-secret",
        "model_status_diagnostic_targets_json": json.dumps(
            [
                {
                    "id": "local-model-a",
                    "display_name": "Local Model A",
                    "endpoint_url": "http://dgx-102:8000/v1",
                    "provider_id": "local",
                    "role": "redundancy",
                },
                {
                    "id": "local-model-b",
                    "display_name": "Local Model B",
                    "endpoint_url": "http://dgx-103:8001/v1",
                    "provider_id": "local",
                    "role": "redundancy",
                },
            ]
        ),
    }
    values.update(overrides)
    return Settings(**values)


def _gateway_health() -> dict[str, object]:
    return {
        "ready": True,
        "models": {
            "embedding": {
                "task": "embedding",
                "model": "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
                "loaded": True,
            },
            "asr": {
                "task": "asr",
                "model": "CohereLabs/cohere-transcribe-03-2026",
                "loaded": True,
            },
        },
    }


def _llm_models() -> dict[str, object]:
    return {
        "object": "list",
        "data": [{"id": "legacy-env-model", "object": "model"}],
    }


@pytest.mark.anyio
async def test_named_local_connections_are_probed_independently_without_holding_db(client):
    from miy_api.core.db import get_session_factory
    from miy_api.domains.ai.model_settings_models import (
        AiModelCatalogEntry,
        AiModelProviderConfig,
    )

    with get_session_factory()() as db:
        for identifier, port in (("conn_gpu_a", 8001), ("conn_gpu_b", 8002)):
            row = AiModelProviderConfig(
                provider_id=identifier,
                provider_kind="openai_compatible",
                display_name=identifier,
                route_mode="local",
                credential_kind="none",
                enabled=True,
                endpoint_url=f"http://127.0.0.1:{port}/v1",
                default_model_id=identifier + "-model",
            )
            db.add(row)
            db.flush()
            db.add(
                AiModelCatalogEntry(
                    id=row.default_model_id,
                    provider_id=identifier,
                    model_key="synthetic-model",
                    display_name="Synthetic",
                    capabilities_json=["chat"],
                    enabled=True,
                )
            )
        db.commit()
        seen = []

        def handler(request):
            assert not db.in_transaction()
            seen.append(request.url.port)
            if request.url.port == 8002:
                raise httpx.ConnectError("private transport detail", request=request)
            return httpx.Response(200, json={"data": [{"id": "synthetic-model"}]})

        result = await collect_model_runtime_status(
            _settings(inference_gateway_base_url="", model_status_diagnostic_targets_json="[]"),
            db=db,
            transport=httpx.MockTransport(handler),
        )
        assert sorted(seen) == [8001, 8002]
        assert result.status == "degraded"
        serving = {
            target.provider_id: target.status
            for target in result.targets
            if target.role == "serving"
        }
        assert serving == {"conn_gpu_a": "online", "conn_gpu_b": "offline"}
        assert "private transport detail" not in result.model_dump_json()
