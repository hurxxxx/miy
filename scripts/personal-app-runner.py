"""Fixed GitLab custom executor: job scripts are never opened or executed."""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

WRAPPER = "/usr/local/bin/miy-personal-app-ci"
MAX_OUTPUT = 65536
SHA = re.compile(r"[a-f0-9]{40}")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
APP = re.compile(r"[a-z][a-z0-9-]{1,63}")
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
PUBLIC_REASONS = {
    "artifact_ownership_required",
    "exact_source_required",
    "fixed_executor_arguments_required",
    "job_auth_required",
    "job_metadata_required",
    "job_ownership_required",
    "job_stage_order_required",
    "mr_diff_required",
    "mr_identity_required",
    "mr_pipeline_event_required",
    "mr_pipeline_identity_required",
    "mr_pipeline_missing",
    "native_job_metadata_required",
    "personal_app_validation_required",
    "private_job_root_required",
    "protected_config_required",
    "same_project_exact_mr_required",
    "trusted_command_failed",
    "unsupported_executor_phase",
    "unsupported_job_stage",
}
PUBLIC_STAGES = {
    "arguments",
    "protected_config",
    "job_context",
    "config",
    "prepare",
    "cleanup",
    "ownership_read",
    "ownership_write",
    "source_metadata",
    "validation_metadata",
    "native_job_http",
    "native_job_assertion",
    "mr_http",
    "mr_assertion",
    "fetch_auth",
    "git_init",
    "git_remote",
    "git_fetch",
    "git_revision",
    "git_checkout",
    "validation",
}
PUBLIC_EXCEPTION_TYPES = {
    "Rejected",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "FileExistsError",
    "TimeoutError",
    "SSLError",
    "SSLCertVerificationError",
    "HTTPException",
    "RemoteDisconnected",
    "BadStatusLine",
    "IncompleteRead",
    "JSONDecodeError",
    "ValueError",
    "TypeError",
    "KeyError",
    "AttributeError",
    "IndexError",
    "SubprocessError",
    "TimeoutExpired",
    "CalledProcessError",
    "KeyboardInterrupt",
}


class Rejected(RuntimeError):
    """Public failure code only; never include job input or subprocess output."""

    def __init__(self, reason, *, stage=None, http_status=None):
        super().__init__(reason)
        self.stage, self.http_status = stage, http_status


def failure_details(error, stage):
    # Even injected exception messages, subclasses and attributes are untrusted.
    reason = (
        error.args[0] if isinstance(error, Rejected) and len(error.args) == 1 else None
    )
    error_stage = error.stage if isinstance(error, Rejected) else None
    cause = (
        error.__cause__ if isinstance(error, Rejected) and error.__cause__ else error
    )
    name = type(cause).__name__
    safe_stage = "unknown"
    if isinstance(error_stage, str) and error_stage in PUBLIC_STAGES:
        safe_stage = error_stage
    elif isinstance(stage, str) and stage in PUBLIC_STAGES:
        safe_stage = stage
    details = {
        "stage": safe_stage,
        "reason": reason
        if isinstance(reason, str) and reason in PUBLIC_REASONS
        else "unclassified_failure",
        "exception_type": name
        if name in PUBLIC_EXCEPTION_TYPES
        else "UnclassifiedError",
    }
    status = error.http_status if isinstance(error, Rejected) else None
    if type(status) is int and 100 <= status <= 599:
        details["http_status"] = status
    return details


@dataclass(frozen=True)
class Config:
    project_id: int
    repository: str
    toolchain_image: str
    work_root: Path

    @property
    def source_root(self):
        return self.work_root.parent / "jobs"


@dataclass(frozen=True)
class Job:
    job_id: str
    head: str
    base: str
    target: str
    source_branch: str

    def identity(self):
        return {
            "job_id": self.job_id,
            "head": self.head,
            "base": self.base,
            "target": self.target,
            "source_branch": self.source_branch,
        }


def load_config(path):
    if not path.is_absolute() or path.resolve() != path:
        raise Rejected("protected_config_required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Rejected("protected_config_required")
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise Rejected("protected_config_required")
    value = json.loads(raw)
    if set(value) != {"project_id", "repository", "toolchain_image", "work_root"}:
        raise Rejected("protected_config_required")
    parsed = urlsplit(value["repository"])
    if (
        type(value["project_id"]) is not int
        or value["project_id"] <= 0
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.strip("/")
        or any(ord(char) < 33 for char in value["repository"])
        or not IMAGE.fullmatch(value["toolchain_image"])
    ):
        raise Rejected("protected_config_required")
    root = Path(value["work_root"])
    private_directory(root)
    return Config(
        value["project_id"], value["repository"], value["toolchain_image"], root
    )


def private_directory(path):
    info = path.lstat()
    if (
        not path.is_absolute()
        or path.resolve() != path
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise Rejected("private_job_root_required")


def job_from_environment(config, environment):
    def value(name):
        return environment.get("CUSTOM_ENV_" + name, "")

    job = Job(
        value("CI_JOB_ID"),
        value("CI_COMMIT_SHA"),
        value("CI_MERGE_REQUEST_DIFF_BASE_SHA"),
        value("CI_MERGE_REQUEST_TARGET_BRANCH_NAME"),
        value("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"),
    )
    if (
        not re.fullmatch(r"[1-9][0-9]{0,19}", job.job_id)
        or not SHA.fullmatch(job.head)
        or not SHA.fullmatch(job.base)
        or value("CI_PIPELINE_SOURCE") != "merge_request_event"
        or value("CI_PROJECT_ID") != str(config.project_id)
        or value("CI_MERGE_REQUEST_SOURCE_PROJECT_ID") != str(config.project_id)
        or job.target not in {"dev", "main"}
        or not 1 <= len(job.source_branch.encode()) <= 256
        or any(ord(char) < 32 or ord(char) == 127 for char in job.source_branch)
        or (job.target == "main" and job.source_branch != "dev")
    ):
        raise Rejected("same_project_exact_mr_required")
    return job


def job_token(environment):
    token = environment.get("CUSTOM_ENV_CI_JOB_TOKEN")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 4096
        or any(ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise Rejected("job_auth_required")
    return token


def gitlab_json(config, path, token, deadline):
    # The protected repository selects the HTTPS origin. CI API/proxy/CA
    # variables never select an endpoint or change native certificate checking.
    origin = urlsplit(config.repository)
    stage = "native_job_http" if path == "/job" else "mr_http"
    connection, status = None, None
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(
            cafile=ssl.get_default_verify_paths().openssl_cafile
        )
        connection = http.client.HTTPSConnection(
            origin.hostname,
            origin.port or 443,
            timeout=max(0.1, min(10, deadline - time.monotonic())),
            context=context,
        )
        if time.monotonic() >= deadline:
            raise Rejected("job_metadata_required", stage=stage)
        connection.request(
            "GET",
            "/api/v4" + path,
            headers={"JOB-TOKEN": token, "Accept": "application/json"},
        )
        response = connection.getresponse()
        status = response.status
        # No redirect handling, retries, ambient proxy or credentials in URLs.
        if response.status != 200:
            raise Rejected("job_metadata_required", stage=stage, http_status=status)
        raw = bytearray()
        while len(raw) <= MAX_OUTPUT and time.monotonic() < deadline:
            if connection.sock is not None:
                connection.sock.settimeout(
                    max(0.1, min(10, deadline - time.monotonic()))
                )
            chunk = response.read1(min(4096, MAX_OUTPUT + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > MAX_OUTPUT or time.monotonic() >= deadline:
            raise Rejected("job_metadata_required", stage=stage, http_status=status)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise Rejected("job_metadata_required", stage=stage, http_status=status)
        return value
    except (http.client.HTTPException, OSError, ValueError) as error:
        raise Rejected(
            "job_metadata_required", stage=stage, http_status=status
        ) from error
    finally:
        if connection is not None:
            connection.close()


def verified_job_metadata(config, job, environment):
    # The IID is only a bounded selector; the authenticated job's pipeline must
    # be the selected MR's current head pipeline, with the exact native diff.
    iid = environment.get("CUSTOM_ENV_CI_MERGE_REQUEST_IID", "")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", iid):
        raise Rejected("job_metadata_required", stage="native_job_assertion")
    token, deadline = job_token(environment), time.monotonic() + 30
    native = gitlab_json(config, "/job", token, deadline)
    pipeline, commit = native.get("pipeline"), native.get("commit")
    if (
        not isinstance(pipeline, dict)
        or not isinstance(commit, dict)
        or type(native.get("id")) is not int
        or str(native["id"]) != job.job_id
        or native.get("name") != "personal_app_validation"
        or native.get("allow_failure") is not False
        or type(pipeline.get("project_id")) is not int
        or pipeline["project_id"] != config.project_id
        or type(pipeline.get("id")) is not int
        or pipeline["id"] <= 0
        or pipeline.get("sha") != job.head
        or commit.get("id") != job.head
    ):
        raise Rejected("native_job_metadata_required", stage="native_job_assertion")
    mr = gitlab_json(
        config, f"/projects/{config.project_id}/merge_requests/{iid}", token, deadline
    )
    current, diff = mr.get("head_pipeline"), mr.get("diff_refs")
    if (
        any(
            type(mr.get(key)) is not int or mr[key] != config.project_id
            for key in ("project_id", "source_project_id", "target_project_id")
        )
        or type(mr.get("iid")) is not int
        or mr["iid"] != int(iid)
        or mr.get("state") != "opened"
        or mr.get("source_branch") != job.source_branch
        or mr.get("target_branch") != job.target
        or mr.get("sha") != job.head
    ):
        raise Rejected("mr_identity_required", stage="mr_assertion")
    if (
        not isinstance(diff, dict)
        or diff.get("head_sha") != job.head
        or diff.get("base_sha") != job.base
    ):
        raise Rejected("mr_diff_required", stage="mr_assertion")
    if not isinstance(current, dict):
        raise Rejected("mr_pipeline_missing", stage="mr_assertion")
    if (
        type(current.get("id")) is not int
        or current["id"] != pipeline["id"]
        or type(current.get("project_id")) is not int
        or current["project_id"] != config.project_id
        or current.get("sha") != job.head
    ):
        raise Rejected("mr_pipeline_identity_required", stage="mr_assertion")
    if (
        current.get("source") != "merge_request_event"
        or current.get("ref") != pipeline.get("ref")
        or current.get("ref")
        not in {job.source_branch, f"refs/merge-requests/{iid}/head"}
    ):
        raise Rejected("mr_pipeline_event_required", stage="mr_assertion")
    return {
        "project_id": config.project_id,
        "pipeline_id": pipeline["id"],
        "merge_request_iid": int(iid),
    }


def command(argv, *, cwd=None, env=None, timeout=120):
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if result.returncode or len(result.stdout) > MAX_OUTPUT:
        raise Rejected("trusted_command_failed")
    return result.stdout


def git(config, source, *args, token=None):
    environment = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "https",
    }
    if token is not None:
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise Rejected("job_auth_required")
        header = base64.b64encode(("gitlab-ci-token:" + token).encode()).decode("ascii")
        environment.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http." + config.repository + ".extraHeader",
            GIT_CONFIG_VALUE_0="Authorization: Basic " + header,
        )
    return command(
        [
            "/usr/bin/git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "credential.helper=",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.proxy=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-C",
            str(source),
            *args,
        ],
        env=environment,
    )


class Executor:
    def __init__(self, config, job):
        self.config, self.job = config, job
        self.stage = "ownership_read"
        self.root = config.source_root / job.job_id
        self.source = self.root / "source"
        self.marker = self.root / "ownership.json"

    def write(self, receipt):
        temporary = self.root / "ownership.json.tmp"
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.marker)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def checked_artifacts(self, results):
        if not isinstance(results, list) or len(results) > 16:
            raise Rejected("personal_app_validation_required")
        for result in results:
            if (
                not isinstance(result, dict)
                or set(result) != {"app_id", "source_revision", "artifact", "state"}
                or not isinstance(result["app_id"], str)
                or not APP.fullmatch(result["app_id"])
                or result["source_revision"] != self.job.head
                or result["state"] != "passed"
                or not isinstance(result["artifact"], str)
                or not IMAGE.fullmatch(result["artifact"])
                or result["artifact"] == self.config.toolchain_image
            ):
                raise Rejected("personal_app_validation_required")
        if len({result["app_id"] for result in results}) != len(results) or len(
            {result["artifact"] for result in results}
        ) != len(results):
            raise Rejected("personal_app_validation_required")
        return results

    def read(self):
        private_directory(self.config.source_root)
        private_directory(self.root)
        pending = self.root / "ownership.json.tmp"
        if pending.exists() or pending.is_symlink():
            # An interrupted append must not be treated as evidence of no image.
            raise Rejected("job_ownership_required")
        with os.fdopen(
            os.open(self.marker, os.O_RDONLY | os.O_NOFOLLOW), "rb"
        ) as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise Rejected("job_ownership_required")
            raw = stream.read(MAX_OUTPUT + 1)
        if len(raw) > MAX_OUTPUT:
            raise Rejected("job_ownership_required")
        receipt = json.loads(raw)
        if (
            receipt.get("identity") != self.job.identity()
            or receipt.get("repository") != self.config.repository
        ):
            raise Rejected("job_ownership_required")
        verification = receipt.get("verification")
        if verification is not None and (
            not isinstance(verification, dict)
            or set(verification) != {"project_id", "pipeline_id", "merge_request_iid"}
            or any(
                type(value) is not int or value <= 0 for value in verification.values()
            )
            or verification["project_id"] != self.config.project_id
        ):
            raise Rejected("job_ownership_required")
        artifacts = self.checked_artifacts(receipt.get("artifacts"))
        removed = receipt.get("removed")
        if (
            not isinstance(removed, list)
            or any(not isinstance(item, str) for item in removed)
            or len(set(removed)) != len(removed)
            or not set(removed).issubset({result["artifact"] for result in artifacts})
        ):
            raise Rejected("job_ownership_required")
        return receipt

    def record_artifact(self, result):
        receipt = self.read()
        if receipt["state"] != "validating" or receipt.get("verification") is None:
            raise Rejected("job_stage_order_required")
        receipt["artifacts"] = self.checked_artifacts([*receipt["artifacts"], result])
        self.write(receipt)

    def configure(self):
        private_directory(self.config.source_root)
        return {
            "builds_dir": str(self.config.source_root),
            "cache_dir": str(self.config.work_root.parent / "unused-cache"),
            "builds_dir_is_shared": False,
            "driver": {"name": "miy-personal-app-fixed", "version": "1"},
        }

    def prepare(self):
        private_directory(self.config.source_root)
        self.root.mkdir(mode=0o700)
        self.source.mkdir(mode=0o700)
        self.write(
            {
                "identity": self.job.identity(),
                "repository": self.config.repository,
                "verification": None,
                "state": "prepared",
                "artifacts": [],
                "removed": [],
            }
        )

    def run(self, stage, environment):
        # The script pathname supplied by Runner is intentionally not consumed.
        self.stage = "ownership_read"
        receipt = self.read()
        if stage in {"prepare_script", "cleanup_file_variables"}:
            return
        if stage == "get_sources":
            if receipt["state"] != "prepared" or any(self.source.iterdir()):
                raise Rejected("job_stage_order_required")
            self.stage = "source_metadata"
            receipt["verification"] = verified_job_metadata(
                self.config, self.job, environment
            )
            self.stage = "ownership_write"
            self.write(receipt)
            self.stage = "fetch_auth"
            token = job_token(environment)
            self.stage = "git_init"
            git(self.config, self.source, "init", "--initial-branch=ci-validation")
            self.stage = "git_remote"
            git(
                self.config,
                self.source,
                "remote",
                "add",
                "origin",
                self.config.repository,
            )
            self.stage = "git_fetch"
            git(
                self.config,
                self.source,
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "--depth=1",
                "origin",
                self.job.head,
                self.job.base,
                token=token,
            )
            self.stage = "git_revision"
            for revision in {self.job.head, self.job.base}:
                if (
                    git(
                        self.config,
                        self.source,
                        "rev-parse",
                        "--verify",
                        revision + "^{commit}",
                    )
                    .decode()
                    .strip()
                    != revision
                ):
                    raise Rejected("exact_source_required")
            self.stage = "git_checkout"
            git(self.config, self.source, "checkout", "--detach", self.job.head)
            receipt["state"] = "sources_ready"
            self.stage = "ownership_write"
            self.write(receipt)
            return
        # Runner 19.4.1 (3c39fceb) translates its main step to build_script
        # for custom executors. Both exact names use only our fixed wrapper.
        if stage not in {"step_script", "build_script"}:
            raise Rejected("unsupported_job_stage")
        if receipt["state"] != "sources_ready":
            raise Rejected("job_stage_order_required")
        self.stage = "validation_metadata"
        if receipt.get("verification") != verified_job_metadata(
            self.config, self.job, environment
        ):
            raise Rejected("job_metadata_required")
        environment = {
            "PATH": os.defpath,
            "CI_JOB_ID": self.job.job_id,
            "CI_PIPELINE_SOURCE": "merge_request_event",
            "CI_PROJECT_ID": str(self.config.project_id),
            "CI_MERGE_REQUEST_SOURCE_PROJECT_ID": str(self.config.project_id),
            "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": self.job.target,
            "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": self.job.source_branch,
            "CI_COMMIT_SHA": self.job.head,
            "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.job.base,
        }
        # No job token, arbitrary CI variable, shell, before_script or after_script.
        receipt["state"] = "validating"
        self.stage = "ownership_write"
        self.write(receipt)
        self.stage = "validation"
        output = json.loads(
            command([WRAPPER], cwd=self.source, env=environment, timeout=3600)
        )
        results = output.get("apps", [])
        if output.get("state") != "passed":
            raise Rejected("personal_app_validation_required")
        self.checked_artifacts(results)
        # Re-read progress saved by the trusted wrapper; never replace it with a
        # stale pre-build receipt, including after failed or timed-out batches.
        receipt = self.read()
        if receipt["state"] != "validating" or results != receipt["artifacts"]:
            raise Rejected("personal_app_validation_required")
        receipt["state"] = "validated"
        self.stage = "ownership_write"
        self.write(receipt)
        print(json.dumps({"state": "passed", "apps": results}, sort_keys=True))

    def cleanup(self):
        if not self.root.exists() and not self.root.is_symlink():
            return
        receipt = self.read()
        receipt["state"] = "cleanup_pending"
        self.write(receipt)
        with tempfile.TemporaryDirectory(prefix="cleanup-", dir=self.root) as temporary:
            environment = {"PATH": os.defpath, "DOCKER_CONFIG": temporary}
            for result in receipt["artifacts"]:
                artifact = result["artifact"]
                if artifact in receipt["removed"]:
                    continue
                if (
                    command(
                        [
                            "/usr/bin/docker",
                            "image",
                            "inspect",
                            artifact,
                            "--format",
                            "{{.Id}}",
                        ],
                        env=environment,
                    )
                    .decode()
                    .strip()
                    != artifact
                ):
                    raise Rejected("artifact_ownership_required")
                labels = json.loads(
                    command(
                        [
                            "/usr/bin/docker",
                            "image",
                            "inspect",
                            artifact,
                            "--format",
                            "{{json .Config.Labels}}",
                        ],
                        env=environment,
                    )
                )
                if (
                    labels.get("miy.independent-app") != "1"
                    or labels.get("miy.app-id") != result["app_id"]
                    or labels.get("miy.source-revision") != self.job.head
                    or not UUID.fullmatch(labels.get("miy.independent-build", ""))
                    or not IMAGE.fullmatch(labels.get("miy.definition-digest", ""))
                    or not IMAGE.fullmatch(labels.get("miy.builder-profile", ""))
                ):
                    raise Rejected("artifact_ownership_required")
                command(["/usr/bin/docker", "image", "rm", artifact], env=environment)
                receipt["removed"].append(artifact)
                self.write(receipt)
        # App-controlled files are data; no symlink traversal or hooks are executed.
        self.read()
        shutil.rmtree(self.root)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    stage, executor = "arguments", None
    try:
        if len(argv) < 3 or argv[0] != "--config":
            raise Rejected("fixed_executor_arguments_required")
        phase = argv[2]
        if (phase == "run" and len(argv) != 5) or (phase != "run" and len(argv) != 3):
            raise Rejected("fixed_executor_arguments_required")
        if phase not in {"config", "prepare", "run", "cleanup"}:
            raise Rejected("unsupported_executor_phase")
        stage = "protected_config"
        config = load_config(Path(argv[1]))
        stage = "job_context"
        executor = Executor(config, job_from_environment(config, os.environ))
        executor.stage = phase if phase != "run" else "ownership_read"
        if phase == "config":
            print(json.dumps(executor.configure(), sort_keys=True))
        elif phase == "prepare":
            executor.prepare()
        elif phase == "run":
            executor.run(argv[4], os.environ)
        else:
            executor.cleanup()
        return 0
    except (
        Rejected,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        print(
            json.dumps(
                {
                    "state": "failed",
                    "code": "personal_app_runner_required",
                    **failure_details(
                        error, executor.stage if executor is not None else stage
                    ),
                }
            )
        )
        value = os.environ.get("BUILD_FAILURE_EXIT_CODE", "1")
        return (
            int(value)
            if re.fullmatch(r"[1-9][0-9]{0,2}", value) and int(value) <= 255
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
