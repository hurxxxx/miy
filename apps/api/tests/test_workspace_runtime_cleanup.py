from uuid import uuid4

import pytest

from miy_api.domains.independent_apps.delivery import RuntimeFailure, RuntimeSpec
from miy_api.domains.independent_apps.local_runtime import DockerRuntime


def fixture(tmp_path):
    runtime = object.__new__(DockerRuntime)
    runtime.root = tmp_path / "state"
    runtime.root.mkdir(mode=0o700)
    runtime.platform_origin = runtime.platform_api_origin = "https://platform.test"
    spec = RuntimeSpec(str(uuid4()), str(uuid4()), "cleanup-fixture", "sha256:" + "a" * 64,
                       "http://127.0.0.1:19439", "/healthz")
    name, network, proxy = runtime.names(spec)
    containers = {name: {"State": {"Running": True}}, proxy: {"State": {"Running": True}}}
    networks = {network: {"Internal": True, "Labels": {"miy.independent-installation": spec.installation_id}}}
    calls = []
    runtime._objects = lambda kind: [dict(Names=n, Labels="miy.independent-installation=" + spec.installation_id) for n in containers]
    runtime._container = lambda selected: containers.get(runtime.names(selected)[0])
    runtime._proxy = lambda selected: containers.get(proxy)
    runtime._inspect = lambda kind, n: (containers if kind == "container" else networks).get(n)
    def run(*args):
        calls.append(args)
        if args[0] == "stop":
            containers[args[-1]]["State"]["Running"] = False
        elif args[0] == "rm":
            containers.pop(args[1])
        elif args[:2] == ("network", "rm"):
            networks.pop(args[-1])
        return ""
    runtime._run = run
    return runtime, spec, containers, calls


def test_workspace_stop_proves_absence_and_stops_ingress_before_app(tmp_path):
    runtime, spec, containers, calls = fixture(tmp_path)
    runtime.stop_workspace([spec], installation_id=spec.installation_id)
    assert not containers
    assert calls[0] == ("stop", "--time", "5", runtime.names(spec)[2])
    assert all("--force" not in command for command in calls)
    previous = list(calls)
    runtime.stop_workspace([spec], installation_id=spec.installation_id)
    assert calls == previous


def test_unrecognized_owned_container_holds_before_any_stop(tmp_path):
    runtime, spec, containers, calls = fixture(tmp_path)
    containers["another-owned-process"] = {"State": {"Running": True}}
    with pytest.raises(RuntimeFailure, match="unrecognized"):
        runtime.stop_workspace([spec], installation_id=spec.installation_id)
    assert not calls


def test_state_cleanup_retains_unknown_files_and_only_removes_verified_config(tmp_path):
    runtime, spec, _, _ = fixture(tmp_path)
    config = runtime.root / spec.installation_id
    config.mkdir()
    (runtime.root / "docker-config").mkdir()
    (config / "nginx.conf").write_text(runtime._configuration(spec))
    extra = config / "keep-user-file"
    extra.write_text("synthetic unrelated data")
    with pytest.raises(RuntimeFailure, match="cleanup_held"):
        runtime.clean_workspace_files([spec], installation_id=spec.installation_id)
    assert (config / "nginx.conf").exists() and extra.exists()
    extra.unlink()
    runtime.clean_workspace_files([spec], installation_id=spec.installation_id)
    assert not runtime.root.exists()
