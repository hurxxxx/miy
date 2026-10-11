from __future__ import annotations


from miy_api.core.settings import Settings
from miy_api.domains.ai import privacy_filter


def _settings(**overrides: object) -> Settings:
    values = {
        "postgres_dsn": ("postgresql+psycopg://miy_test:miy_test@127.0.0.1:5432/miy_test"),
        "opf_enabled": True,
        "opf_checkpoint": "openai/privacy-filter",
        "opf_device": "cuda",
    }
    values.update(overrides)
    return Settings(**values)


def test_privacy_filter_service_failure_fails_closed(monkeypatch) -> None:
    def raising_client(**_kwargs):
        raise RuntimeError("service down")

    monkeypatch.setattr(privacy_filter.httpx, "Client", raising_client)

    detection = privacy_filter.detect_privacy_filter_spans(
        ["public"],
        settings=_settings(opf_service_base_url="http://privacy.local"),
    )

    assert detection.enabled is True
    assert detection.status == "service_unavailable"
