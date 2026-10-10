"""Operator ingress and filesystem isolation must fail before app execution."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget
from miy_api.core.settings import Settings


def binding(tmp_path, **changes):
    return IndependentDeliveryTarget(
        **{
            "app_id": "sample-independent",
            "installation_id": uuid4(),
            "source_root": tmp_path / "source",
            "work_root": tmp_path / "build",
            "state_root": tmp_path / "state",
            "toolchain_image": "sha256:" + "a" * 64,
            "ingress_image": "sha256:" + "b" * 64,
            "platform_origin": "https://platform.test",
            "platform_api_origin": "https://api.platform.test",
            **changes,
        }
    )


def production_binding(tmp_path, **changes):
    return binding(
        tmp_path,
        **{
            "environment": "production",
            "app_origin": "https://app.test",
            "loopback_port": 19431,
            **changes,
        },
    )


def settings(targets, environment="production"):
    return Settings(
        _env_file=None,
        environment=environment,
        seed_dev_login_account=False,
        object_storage_required=True,
        content_grant_signing_key="synthetic-operator-binding-test-key-20261010",
        hermes_terminal_resource_namespace="synthetic-production",
        independent_app_platform_origins=["https://platform.test"],
        independent_app_delivery_targets=targets,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"app_origin": None},
        {"loopback_port": None},
        {"app_origin": "http://127.0.0.1:19431"},
        {"app_origin": "https://platform.test"},
        {"app_origin": "https://api.platform.test"},
        {"app_origin": "https://user:password@app.test"},
        {"loopback_port": True},
        {"loopback_port": "19431"},
        {"loopback_port": 80},
        {"loopback_port": 65536},
    ],
)
def test_production_ingress_rejects_unsafe_or_missing_operator_bindings(tmp_path, changes):
    with pytest.raises(ValidationError):
        production_binding(tmp_path, **changes)


def test_only_production_control_plane_can_own_production_delivery(tmp_path):
    target = production_binding(tmp_path)
    with pytest.raises(ValidationError, match="production platform runtime"):
        settings([target], "development")
    assert settings([target]).independent_app_delivery_targets == [target]
    assert settings([], "development").independent_app_delivery_targets == []


def test_one_control_plane_can_keep_isolated_development_and_production_installations(tmp_path):
    development = binding(tmp_path / "development")
    production = production_binding(tmp_path / "production", source_root=development.source_root)
    assert settings([development, production]).independent_app_delivery_targets == [
        development,
        production,
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"app_origin": "https://app.test", "loopback_port": 19432},
        {"app_origin": "https://other.test", "loopback_port": 19431},
    ],
)
def test_production_installations_cannot_share_ingress(tmp_path, changes):
    first = production_binding(tmp_path / "first")
    second = production_binding(tmp_path / "second", **changes)
    with pytest.raises(ValidationError, match="distinct HTTPS origins and loopback ports"):
        settings([first, second])


@pytest.mark.parametrize("root", ["work_root", "state_root"])
def test_installations_cannot_share_build_or_runtime_state(tmp_path, root):
    first = binding(tmp_path / "first")
    second = binding(tmp_path / "second", **{root: getattr(first, root) / "nested"})
    with pytest.raises(ValidationError, match="separate build scratch and runtime state"):
        settings([first, second])


def test_server_development_preview_requires_a_complete_https_binding(tmp_path):
    for changes in ({"app_origin": "https://app.test"}, {"loopback_port": 19431}):
        with pytest.raises(ValidationError, match="HTTPS app origin and a fixed loopback port"):
            binding(tmp_path, **changes)
    target = binding(tmp_path, app_origin="https://app.test", loopback_port=19431)
    assert settings([target], "development").independent_app_delivery_targets == [target]


@pytest.mark.parametrize("port", [18779, 18780, 18781])
def test_delivery_cannot_reserve_platform_or_official_internal_listener(tmp_path, port):
    with pytest.raises(ValidationError, match="reserved first-party service port"):
        production_binding(tmp_path, loopback_port=port)
