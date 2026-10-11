from __future__ import annotations

from datetime import datetime, timezone

import pytest
from dev_accounts import auth_headers, dev_login

from miy_api.core.db import get_session_factory
from miy_api.domains.ai.model_settings_models import (
    AiModelCatalogEntry,
    AiModelPolicyDefault,
    AiModelProviderConfig,
    AiModelRouteOverride,
)
from miy_api.domains.ai.model_settings_service import (
    AiModelSettingsError,
    ai_model_registry_digest,
    resolve_ai_model_workload_route,
)


def admin(client):
    return auth_headers(dev_login(client)["token"])


def seed(db, connection_id, *, kind="openai_compatible", route="local", capabilities=None):
    connection = AiModelProviderConfig(
        provider_id=connection_id,
        provider_kind=kind,
        display_name=connection_id,
        route_mode=route,
        credential_kind="none",
        endpoint_url="http://127.0.0.1:11434/v1",
        enabled=True,
        version=1,
    )
    db.add(connection)
    db.flush()
    model = AiModelCatalogEntry(
        id=f"{connection_id}-model",
        provider_id=connection_id,
        model_key=f"test/{connection_id}",
        display_name=connection_id,
        capabilities_json=capabilities or ["chat", "tool_calling"],
        enabled=True,
        version=1,
    )
    db.add(model)
    db.flush()
    connection.default_model_id = model.id
    return connection, model


def test_global_app_and_workload_inherit_independently_and_shared_workload_is_scoped(client):
    with get_session_factory()() as db:
        a, ma = seed(db, "one")
        b, mb = seed(db, "two")
        db.merge(
            AiModelPolicyDefault(
                model_family="generation",
                app_id="",
                route_mode="local",
                provider_id=a.provider_id,
                max_output_tokens=32768,
            )
        )
        db.merge(
            AiModelPolicyDefault(
                model_family="generation",
                app_id="recording",
                route_mode="local",
                provider_id=b.provider_id,
                max_output_tokens=8192,
            )
        )
        db.add(
            AiModelRouteOverride(
                id="meeting-cap",
                app_id="meeting",
                workload_id="meeting_summary",
                local_max_output_tokens=2048,
            )
        )
        db.commit()
        meeting = resolve_ai_model_workload_route(
            db, workload_id="meeting_summary", app_id="meeting"
        )
        recording = resolve_ai_model_workload_route(
            db, workload_id="meeting_summary", app_id="recording"
        )
        assert (meeting.provider_id, meeting.max_output_tokens, meeting.output_cap_source) == (
            "one",
            2048,
            "workload",
        )
        assert (
            recording.provider_id,
            recording.max_output_tokens,
            recording.connection_source,
        ) == ("two", 8192, "app")
        with pytest.raises(AiModelSettingsError, match="workload_app_required"):
            resolve_ai_model_workload_route(db, workload_id="meeting_summary")
        db.get(AiModelPolicyDefault, ("generation", "", "local")).provider_id = "two"
        db.flush()
        assert (
            resolve_ai_model_workload_route(
                db, workload_id="meeting_summary", app_id="meeting"
            ).model_key
            == mb.model_key
        )
        assert db.get(AiModelRouteOverride, "meeting-cap").model_ids == {}


def test_connection_keys_are_encrypted_write_only_preserved_rotated_and_clearable(client):
    headers = admin(client)
    digest = ai_model_registry_digest()
    secret = "synthetic-local-key-only"
    created = client.post(
        "/api/v1/admin/ai-model-settings/connections",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "provider_kind": "openai_compatible",
            "route_mode": "local",
            "preset": "vllm",
            "display_name": "Private GPU",
            "endpoint_url": "http://127.0.0.1:8000/v1",
            "credential_kind": "api_key",
            "api_key": secret,
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    connection = next(
        row for row in created.json()["providers"] if row["display_name"] == "Private GPU"
    )
    assert connection["enabled"] is False
    assert secret not in created.text and connection["has_api_key"]
    identifier = connection["provider_id"]
    with get_session_factory()() as db:
        ciphertext = db.get(AiModelProviderConfig, identifier).api_key_ciphertext
        assert ciphertext != secret and secret not in ciphertext
    for action in ({}, {"api_key": "rotated-synthetic-key"}, {"clear_api_key": True}):
        response = client.put(
            f"/api/v1/admin/ai-model-settings/providers/{identifier}",
            headers=headers,
            json={
                "expected_registry_digest": digest,
                "expected_version": connection["version"],
                "enabled": False,
                "endpoint_url": connection["endpoint_url"],
                **action,
            },
        )
        assert response.status_code == 200, response.text
        connection = next(
            row for row in response.json()["providers"] if row["provider_id"] == identifier
        )
        assert secret not in response.text and "rotated-synthetic-key" not in response.text
        with get_session_factory()() as db:
            current = db.get(AiModelProviderConfig, identifier).api_key_ciphertext
            if not action:
                assert current == ciphertext
            elif "api_key" in action:
                assert current and current != ciphertext
            else:
                assert current is None and not connection["has_api_key"]
    # Same provider family may have independent credentials and identity.
    second = client.post(
        "/api/v1/admin/ai-model-settings/connections",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "provider_kind": "openai_compatible",
            "route_mode": "local",
            "display_name": "Second GPU",
            "credential_kind": "none",
            "endpoint_url": "http://127.0.0.1:8001/v1",
        },
    )
    assert second.status_code == 201
    assert (
        len(
            [
                row
                for row in second.json()["providers"]
                if row["provider_kind"] == "openai_compatible"
            ]
        )
        == 2
    )


@pytest.mark.migration
def test_connection_migration_preserves_keys_and_forks_shared_app_overrides(postgres_dsn):
    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from test_alembic_migrations import _migration_config

    from alembic import command
    from miy_api.core.db import Base
    from miy_api.core.model_registry import import_all_models

    config = _migration_config(postgres_dsn)
    command.upgrade(config, "hermes_initial_snapshot_20260914")
    engine = sa.create_engine(postgres_dsn)
    try:
        with engine.begin() as connection:
            metadata = sa.MetaData()
            providers = sa.Table("ai_model_provider_configs", metadata, autoload_with=connection)
            overrides = sa.Table("ai_model_route_overrides", metadata, autoload_with=connection)
            connection.execute(
                providers.insert().values(
                    provider_id="local",
                    enabled=True,
                    api_key_ciphertext="preserve-ciphertext",
                    version=1,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            connection.execute(
                overrides.insert().values(
                    id="shared-summary",
                    workload_id="meeting_summary",
                    route_mode="local",
                    model_ids_json={},
                    local_max_output_tokens=2048,
                    version=3,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            connection.execute(
                overrides.insert().values(
                    id="retired-search",
                    workload_id="web_search.answer",
                    route_mode="local",
                    model_ids_json={},
                    version=2,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            connection.execute(
                overrides.insert().values(
                    id="legacy-null-scope",
                    workload_id="legacy.removed",
                    route_mode="local",
                    model_ids_json={},
                    version=4,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT api_key_ciphertext FROM ai_model_provider_configs WHERE provider_id='local'"
                    )
                )
                == "preserve-ciphertext"
            )
            rows = connection.execute(
                sa.text(
                    "SELECT app_id, local_max_output_tokens, version FROM ai_model_route_overrides WHERE workload_id='meeting_summary' ORDER BY app_id"
                )
            ).all()
            assert rows == [("meeting", 2048, 3), ("recording", 2048, 3)]
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT external_max_output_tokens FROM ai_model_route_overrides WHERE workload_id='bento.plan_presentation'"
                    )
                )
                == 16384
            )
            import_all_models()
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        from sqlalchemy.orm import Session

        from miy_api.domains.ai.model_settings_service import delete_ai_model_route_override

        with Session(engine) as db:
            assert db.get(AiModelRouteOverride, "legacy-null-scope").app_id is None
            with pytest.raises(AiModelSettingsError, match="version_conflict"):
                delete_ai_model_route_override(
                    db,
                    workload_id="legacy.removed",
                    expected_registry_digest=ai_model_registry_digest(),
                    expected_version=3,
                )
            delete_ai_model_route_override(
                db,
                workload_id="legacy.removed",
                expected_registry_digest=ai_model_registry_digest(),
                expected_version=4,
            )
            assert db.get(AiModelRouteOverride, "legacy-null-scope") is None
            assert db.get(AiModelRouteOverride, "retired-search").app_id == "web-search"
            delete_ai_model_route_override(
                db,
                workload_id="web_search.answer",
                app_id="web-search",
                expected_registry_digest=ai_model_registry_digest(),
                expected_version=2,
            )
            assert db.get(AiModelRouteOverride, "retired-search") is None
    finally:
        engine.dispose()


def test_saved_connection_probe_releases_db_during_io_and_rejects_concurrent_edits(
    client, monkeypatch
):
    from miy_api.domains.ai import model_settings_service as service
    from miy_api.domains.ai.model_discovery import DiscoveredProviderModel

    with get_session_factory()() as db:
        connection, model = seed(db, "probe")
        db.commit()

        def inventory(*_args, **_kwargs):
            assert not db.in_transaction(), "probe must release its DB checkout before provider I/O"
            return (DiscoveredProviderModel("test/probe", "Probe", ("chat", "tool_calling")),)

        monkeypatch.setattr(service, "discover_provider_models", inventory)
        assert service.probe_ai_model_connection(
            db,
            provider_id="probe",
            expected_version=1,
            expected_registry_digest=ai_model_registry_digest(),
        )
        db.commit()
        assert db.get(AiModelProviderConfig, "probe").verified_version == 1

        def changed(*args, **kwargs):
            result = inventory(*args, **kwargs)
            with get_session_factory()() as peer:
                peer.get(AiModelProviderConfig, "probe").version = 2
                peer.commit()
            return result

        monkeypatch.setattr(service, "discover_provider_models", changed)
        with pytest.raises(AiModelSettingsError, match="version_conflict"):
            service.probe_ai_model_connection(
                db,
                provider_id="probe",
                expected_version=1,
                expected_registry_digest=ai_model_registry_digest(),
            )


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/v1",
        "http://127.0.0.1/v1?api_key=secret",
    ],
)
def test_connection_endpoint_rejects_untrusted_local_urls(endpoint):
    from miy_api.domains.ai.model_settings_service import _validate_endpoint_url

    with pytest.raises(AiModelSettingsError):
        _validate_endpoint_url(endpoint, provider_id="example", route_mode="local")


def test_inherited_route_change_rejects_incompatible_model_and_rolls_back(client):
    headers = admin(client)
    with get_session_factory()() as db:
        local, _ = seed(db, "route-local")
        external, _ = seed(
            db, "route-external", kind="openai", route="external", capabilities=["chat"]
        )
        external.endpoint_url = "https://api.openai.com/v1"
        for connection in (local, external):
            db.merge(
                AiModelPolicyDefault(
                    model_family="generation",
                    app_id="",
                    route_mode=connection.route_mode,
                    provider_id=connection.provider_id,
                )
            )
        db.commit()
    response = client.put(
        "/api/v1/admin/ai-model-settings/workloads/chatbot/route?app_id=chatbot",
        headers=headers,
        json={
            "expected_registry_digest": ai_model_registry_digest(),
            "expected_version": 0,
            "route_mode": "external",
            "provider_id": None,
        },
    )
    assert response.status_code == 422, response.text
    with get_session_factory()() as db:
        assert resolve_ai_model_workload_route(db, workload_id="chatbot").route == "local"
