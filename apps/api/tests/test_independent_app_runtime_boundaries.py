"""Runtime observation must distinguish absence, foreign objects and daemon loss."""

import json
from uuid import uuid4

import pytest

from miy_api.domains.independent_apps.data_store import DataStoreError
from miy_api.domains.independent_apps.delivery import RuntimeFailure, RuntimeSpec
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from miy_api.core.app_origins import exact_origin


def runtime(monkeypatch, inventory, inspection=None):
    selected = object.__new__(DockerRuntime)
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ("container", "ls", "--all"):
            return "\n".join(json.dumps(row) for row in inventory)
        if isinstance(inspection, Exception):
            raise inspection
        return json.dumps(inspection)

    monkeypatch.setattr(selected, "_run", run)
    return selected, calls


def test_successful_unfiltered_inventory_is_the_only_absence_proof(monkeypatch):
    selected, calls = runtime(monkeypatch, [{"Names": "another-container"}])
    assert selected._inspect("container", "candidate") is None
    assert len(calls) == 1 and "--filter" not in calls[0][0]


def test_disappearing_daemon_does_not_turn_a_known_object_into_absence(monkeypatch):
    selected, calls = runtime(
        monkeypatch, [{"Names": "candidate"}], RuntimeFailure("docker_unavailable")
    )
    with pytest.raises(RuntimeFailure, match="docker_unavailable"):
        selected._inspect("container", "candidate")
    assert calls[-1] == (("container", "inspect", "candidate"), {})


def test_foreign_deterministic_name_is_never_adopted_or_deleted(monkeypatch):
    selected, calls = runtime(monkeypatch, [{"Names": "candidate"}], [{"Config": {"Labels": None}}])
    with pytest.raises(RuntimeFailure, match="foreign_runtime_name"):
        selected._inspect("container", "candidate")
    assert all("rm" not in args for args, _ in calls)


@pytest.mark.parametrize(
    "failure", [None, "data_cluster_public_connect", "data_provision_unavailable"]
)
def test_data_profile_requires_core_migration_before_any_daemon_mutation(monkeypatch, failure):
    selected = object.__new__(DockerRuntime)
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "data-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile="web-api-postgres-v1",
    )
    calls = []

    class Store:
        def prepare(self, **kwargs):
            calls.append(kwargs)
            raise DataStoreError(failure)

    selected.data_store = Store() if failure else None

    def command(*args):
        calls.append(args)
        assert args == ("image", "inspect", spec.image_id, "--format", "{{.Id}}")
        return spec.image_id

    monkeypatch.setattr(selected, "_run", command)
    with pytest.raises(RuntimeFailure) as result:
        selected.prepare(spec)
    assert result.value.code == (failure or "data_configuration_required")
    assert result.value.uncertain == (failure == "data_provision_unavailable")
    if failure:
        assert calls[-1] == {
            "installation_id": spec.installation_id,
            "app_id": spec.app_id,
            "environment": "development",
            "artifact_digest": spec.image_id,
            "request_id": spec.request_id,
        }


def test_data_gateway_is_bound_to_its_profile_and_cannot_proxy_other_platform_apis():
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = "https://platform.example.test"
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "data-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
    )
    assert "/_data/" not in selected._configuration(spec)
    from dataclasses import replace

    configuration = selected._configuration(replace(spec, runtime_profile="web-api-postgres-v1"))
    assert "/api/v1/independent-apps/_data/" in configuration
    assert "client_max_body_size 20k;" in configuration
    assert "location / { return 404; }" in configuration
    assert "limit_except GET POST PUT DELETE { deny all; }" in configuration


@pytest.mark.parametrize("profile", ["web-api-v1", "web-api-postgres-v1"])
def test_selected_file_gateway_exposes_only_the_two_app_authorized_paths(profile):
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = "https://platform.example.test"
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "file-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile=profile,
    )
    configuration = selected._configuration(spec)
    assert configuration.count("location = /api/v1/independent-apps/_files/") == 2
    assert (
        "location = /api/v1/independent-apps/_files/selection-request {\n   if ($request_method != POST) { return 405; }"
        in configuration
    )
    assert (
        "location = /api/v1/independent-apps/_files/content {\n   if ($request_method != GET) { return 405; }"
        in configuration
    )
    assert "/candidates" not in configuration and "/authorize-selection" not in configuration
    assert "proxy_buffering off;" in configuration and "proxy_read_timeout 12s;" in configuration
    assert (
        "proxy_read_timeout 5s;" in configuration and "location / { return 404; }" in configuration
    )


@pytest.mark.parametrize("profile", ["web-api-v1", "web-api-postgres-v1"])
@pytest.mark.parametrize(
    ("origin", "target"),
    [
        ("http://localhost", "http://host.docker.internal:80"),
        ("http://127.0.0.1", "http://host.docker.internal:80"),
        ("https://localhost", "https://host.docker.internal:443"),
        ("https://127.0.0.1", "https://host.docker.internal:443"),
        ("http://localhost:443", "http://host.docker.internal:443"),
        ("http://127.0.0.1:443", "http://host.docker.internal:443"),
        ("http://localhost:19391", "http://host.docker.internal:19391"),
        ("http://127.0.0.1:19391", "http://host.docker.internal:19391"),
        ("https://localhost:80", "https://host.docker.internal:80"),
        ("https://127.0.0.1:80", "https://host.docker.internal:80"),
        ("https://localhost:9443", "https://host.docker.internal:9443"),
        ("https://127.0.0.1:9443", "https://host.docker.internal:9443"),
        ("https://platform.example.test", "https://platform.example.test"),
        ("https://platform.example.test:9443", "https://platform.example.test:9443"),
    ],
)
def test_generated_gateway_preserves_upstream_scheme_and_selected_port(profile, origin, target):
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = exact_origin(origin)
    spec = RuntimeSpec(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "port-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile=profile,
    )
    configuration = selected._configuration(spec)
    assert configuration.count(f"proxy_pass {target};") == (
        5 if profile == "web-api-postgres-v1" else 4
    )
    assert (
        f"location = /api/v1/independent-apps/exchange {{ limit_except POST {{ deny all; }} "
        f"proxy_pass {target}; }}" in configuration
    )
    assert (
        f"location = /api/v1/independent-apps/session {{ limit_except GET {{ deny all; }} "
        f"proxy_pass {target}; }}" in configuration
    )
    assert "proxy_ssl_verify on;" in configuration
    assert "proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;" in configuration
    assert "proxy_ssl_name " + origin.split("://", 1)[1].split(":", 1)[0] + ";" in configuration
    assert f"proxy_set_header Host {origin.split('://', 1)[1]};" in configuration
    assert "location / { return 404; }" in configuration
