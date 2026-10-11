"""Custom executor rejects job scripts and gives only trusted Git the job token."""

from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location(
    "personal_app_runner",
    Path(__file__).resolve().parents[1] / "personal-app-runner.py",
)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
GITLAB_JSON = runner.gitlab_json
HEAD, BASE = "a" * 40, "b" * 40
ARTIFACT, TOOLCHAIN = "sha256:" + "c" * 64, "sha256:" + "d" * 64


class PersonalAppRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        scratch, jobs = self.root / "scratch", self.root / "jobs"
        scratch.mkdir(mode=0o700)
        jobs.mkdir(mode=0o700)
        self.config = runner.Config(
            1, "https://example.test/team/project", TOOLCHAIN, scratch
        )
        self.environment = {
            "CUSTOM_ENV_CI_JOB_ID": "123",
            "CUSTOM_ENV_CI_MERGE_REQUEST_IID": "7",
            "CUSTOM_ENV_CI_PROJECT_ID": "1",
            "CUSTOM_ENV_CI_MERGE_REQUEST_SOURCE_PROJECT_ID": "1",
            "CUSTOM_ENV_CI_PIPELINE_SOURCE": "merge_request_event",
            "CUSTOM_ENV_CI_COMMIT_SHA": HEAD,
            "CUSTOM_ENV_CI_MERGE_REQUEST_DIFF_BASE_SHA": BASE,
            "CUSTOM_ENV_CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "dev",
            "CUSTOM_ENV_CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "feat/장비-app",
            "CUSTOM_ENV_CI_JOB_TOKEN": "synthetic-unit-token",
            "CUSTOM_ENV_CI_REPOSITORY_URL": "https://foreign.test/untrusted",
            "CUSTOM_ENV_CI_API_V4_URL": "https://foreign.test/api/v4",
            "CUSTOM_ENV_GIT_CLONE_PATH": "/outside/jobs",
            "CUSTOM_ENV_PATH": "/untrusted/bin",
            "CUSTOM_ENV_BEFORE_SCRIPT": "touch /outside/pwned",
        }
        self.job = runner.job_from_environment(self.config, self.environment)
        self.job_metadata = {
            "id": 123,
            "name": "personal_app_validation",
            "allow_failure": False,
            "commit": {"id": HEAD},
            # Neither optional Job nor pipeline source fields are required.
            # The authenticated current MR pipeline proves the event source.
            "pipeline": {
                "id": 45,
                "project_id": 1,
                "sha": HEAD,
                "ref": "refs/merge-requests/7/head",
            },
        }
        self.mr_metadata = {
            "iid": 7,
            "project_id": 1,
            "source_project_id": 1,
            "target_project_id": 1,
            "state": "opened",
            "source_branch": "feat/장비-app",
            "target_branch": "dev",
            "sha": HEAD,
            "diff_refs": {"head_sha": HEAD, "base_sha": BASE},
            "head_pipeline": {
                **self.job_metadata["pipeline"],
                "source": "merge_request_event",
            },
        }
        self.metadata_calls = []

        def metadata(config, path, token, deadline):
            self.metadata_calls.append(path)
            if path == "/job":
                return copy.deepcopy(self.job_metadata)
            if path == "/projects/1/merge_requests/7":
                return copy.deepcopy(self.mr_metadata)
            raise runner.Rejected("job_metadata_required")

        mocked = patch.object(runner, "gitlab_json", side_effect=metadata)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.executor = runner.Executor(self.config, self.job)
        self.executor.prepare()

    def tearDown(self):
        self.temporary.cleanup()

    def ready(self):
        receipt = self.executor.read()
        receipt["state"] = "sources_ready"
        receipt["verification"] = runner.verified_job_metadata(
            self.config, self.job, self.environment
        )
        self.executor.write(receipt)

    def result(self):
        return {
            "state": "passed",
            "apps": [
                {
                    "app_id": "fixture-app",
                    "source_revision": HEAD,
                    "artifact": ARTIFACT,
                    "state": "passed",
                }
            ],
        }

    def test_same_project_exact_commit_and_release_context_fail_closed(self):
        for name, value in (
            ("CI_JOB_ID", "../123"),
            ("CI_COMMIT_SHA", "--config"),
            ("CI_MERGE_REQUEST_DIFF_BASE_SHA", ""),
            ("CI_PIPELINE_SOURCE", "push"),
            ("CI_PROJECT_ID", "2"),
            ("CI_MERGE_REQUEST_SOURCE_PROJECT_ID", "2"),
            ("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main"),
        ):
            with self.subTest(name=name), self.assertRaises(runner.Rejected):
                runner.job_from_environment(
                    self.config, {**self.environment, "CUSTOM_ENV_" + name: value}
                )
        valid = {
            **self.environment,
            "CUSTOM_ENV_CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
            "CUSTOM_ENV_CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "dev",
        }
        self.assertEqual(runner.job_from_environment(self.config, valid).target, "main")

    def test_fetch_is_fixed_remote_exact_commits_with_auth_in_child_environment_only(
        self,
    ):
        calls = []

        def command(argv, **kwargs):
            calls.append((argv, kwargs))
            if "rev-parse" in argv:
                return (argv[-1].removesuffix("^{commit}") + "\n").encode()
            return b""

        with patch.object(runner, "command", side_effect=command):
            self.executor.run("get_sources", self.environment)
        fetch = next((argv, kwargs) for argv, kwargs in calls if "fetch" in argv)
        self.assertEqual(fetch[0][-3:], ["origin", HEAD, BASE])
        remote = next(argv for argv, _ in calls if "remote" in argv)
        self.assertEqual(remote[-1], self.config.repository)
        header = base64.b64encode(b"gitlab-ci-token:synthetic-unit-token").decode()
        self.assertEqual(
            fetch[1]["env"]["GIT_CONFIG_VALUE_0"], "Authorization: Basic " + header
        )
        self.assertEqual(
            fetch[1]["env"]["GIT_CONFIG_KEY_0"],
            "http." + self.config.repository + ".extraHeader",
        )
        for argv, kwargs in calls:
            self.assertNotIn("synthetic-unit-token", " ".join(argv))
            self.assertNotIn("CUSTOM_ENV_CI_REPOSITORY_URL", kwargs["env"])
            self.assertIn("core.hooksPath=/dev/null", argv)
            self.assertIn("http.followRedirects=false", argv)
            self.assertEqual(kwargs["env"]["PATH"], os.defpath)
        self.assertNotIn("synthetic-unit-token", self.executor.marker.read_text())
        self.assertNotIn(header, self.executor.marker.read_text())
        self.assertEqual(self.metadata_calls, ["/job", "/projects/1/merge_requests/7"])
        self.assertEqual(
            self.executor.read()["verification"],
            {"project_id": 1, "pipeline_id": 45, "merge_request_iid": 7},
        )
        self.assertEqual(self.executor.read()["state"], "sources_ready")

    def test_forged_empty_diff_is_refused_before_any_git_or_build(self):
        forged = {**self.environment, "CUSTOM_ENV_CI_MERGE_REQUEST_DIFF_BASE_SHA": HEAD}
        job = runner.job_from_environment(self.config, forged)
        receipt = self.executor.read()
        receipt["identity"] = job.identity()
        self.executor.write(receipt)
        executor = runner.Executor(self.config, job)
        with (
            patch.object(runner, "command") as command,
            self.assertRaises(runner.Rejected),
        ):
            executor.run("get_sources", forged)
        command.assert_not_called()
        self.assertEqual(executor.read()["state"], "prepared")
        self.assertIsNone(executor.read()["verification"])
        self.assertEqual(list(executor.source.iterdir()), [])

    def test_authenticated_job_and_current_mr_reject_override_or_foreign_metadata(self):
        for key, value in (
            ("CI_JOB_ID", "124"),
            ("CI_COMMIT_SHA", "f" * 40),
            ("CI_MERGE_REQUEST_DIFF_BASE_SHA", HEAD),
            ("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME", "feat/other"),
            ("CI_MERGE_REQUEST_IID", "8"),
        ):
            environment = {**self.environment, "CUSTOM_ENV_" + key: value}
            with self.subTest(key=key), self.assertRaises(runner.Rejected):
                runner.verified_job_metadata(
                    self.config,
                    runner.job_from_environment(self.config, environment),
                    environment,
                )
        for object_name, key, value in (
            ("job", "name", "unrelated_job"),
            ("job", "allow_failure", True),
            ("pipeline", "project_id", 2),
            ("mr", "source_project_id", 2),
            ("mr", "target_project_id", 2),
            ("mr", "target_branch", "main"),
            ("mr", "state", "closed"),
            ("head_pipeline", "id", 46),
            ("head_pipeline", "source", "push"),
            ("head_pipeline", "ref", "refs/merge-requests/8/head"),
        ):
            original = copy.deepcopy((self.job_metadata, self.mr_metadata))
            target = {
                "job": self.job_metadata,
                "pipeline": self.job_metadata["pipeline"],
                "mr": self.mr_metadata,
                "head_pipeline": self.mr_metadata["head_pipeline"],
            }[object_name]
            target[key] = value
            with (
                self.subTest(object=object_name, key=key),
                self.assertRaises(runner.Rejected),
            ):
                runner.verified_job_metadata(self.config, self.job, self.environment)
            self.job_metadata, self.mr_metadata = original

    def test_step_rechecks_mr_and_never_builds_from_unverified_or_stale_receipt(self):
        self.ready()
        self.mr_metadata["diff_refs"]["base_sha"] = HEAD
        for stage in ("step_script", "build_script"):
            with (
                self.subTest(stage=stage, boundary="stale_mr"),
                patch.object(runner, "command") as command,
                self.assertRaises(runner.Rejected),
            ):
                self.executor.run(stage, self.environment)
            command.assert_not_called()
        self.assertEqual(self.executor.read()["state"], "sources_ready")
        self.mr_metadata["diff_refs"]["base_sha"] = BASE
        receipt = self.executor.read()
        receipt["verification"] = None
        self.executor.write(receipt)
        for stage in ("step_script", "build_script"):
            with (
                self.subTest(stage=stage, boundary="unverified_journal"),
                patch.object(runner, "command") as command,
                self.assertRaises(runner.Rejected),
            ):
                self.executor.run(stage, self.environment)
            command.assert_not_called()

    def test_empty_diff_requires_matching_authenticated_base_then_may_pass(self):
        self.environment["CUSTOM_ENV_CI_MERGE_REQUEST_DIFF_BASE_SHA"] = HEAD
        self.mr_metadata["diff_refs"]["base_sha"] = HEAD
        self.job = runner.job_from_environment(self.config, self.environment)
        receipt = self.executor.read()
        receipt["identity"] = self.job.identity()
        self.executor.write(receipt)
        self.executor = runner.Executor(self.config, self.job)
        self.ready()
        with (
            patch.object(
                runner, "command", return_value=b'{"state":"passed","apps":[]}'
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.executor.run("step_script", self.environment)
        self.assertEqual(json.loads(output.getvalue()), {"state": "passed", "apps": []})
        self.assertEqual(self.executor.read()["state"], "validated")

    def test_https_metadata_uses_fixed_origin_native_ca_and_bounded_no_redirect_requests(
        self,
    ):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read1.side_effect = [b'{"id":123}', b""]
        with (
            patch.object(
                runner.http.client, "HTTPSConnection", return_value=connection
            ) as native,
            patch.dict(
                os.environ,
                {
                    "HTTPS_PROXY": "http://foreign.invalid",
                    "SSL_CERT_FILE": "/nonexistent/attacker-ca",
                },
            ),
        ):
            self.assertEqual(
                GITLAB_JSON(
                    self.config,
                    "/job",
                    "synthetic-unit-token",
                    runner.time.monotonic() + 30,
                ),
                {"id": 123},
            )
        self.assertEqual(native.call_args.args, ("example.test", 443))
        context = native.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        connection.request.assert_called_once_with(
            "GET",
            "/api/v4/job",
            headers={"JOB-TOKEN": "synthetic-unit-token", "Accept": "application/json"},
        )
        connection.close.assert_called_once()
        for status, chunks in (
            (302, []),
            (401, []),
            (200, [b"x" * (runner.MAX_OUTPUT + 1)]),
            (200, [b"invalid-json", b""]),
        ):
            response.status, response.read1.side_effect = status, chunks
            connection.request.reset_mock()
            with (
                patch.object(
                    runner.http.client, "HTTPSConnection", return_value=connection
                ),
                self.subTest(status=status),
                self.assertRaises(runner.Rejected),
            ):
                GITLAB_JSON(
                    self.config,
                    "/job",
                    "synthetic-unit-token",
                    runner.time.monotonic() + 30,
                )
            self.assertEqual(connection.request.call_count, 1)
        with (
            patch.object(
                runner.http.client, "HTTPSConnection", return_value=connection
            ),
            self.assertRaises(runner.Rejected),
        ):
            GITLAB_JSON(
                self.config, "/job", "synthetic-unit-token", runner.time.monotonic() - 1
            )
        connection.request.reset_mock()
        connection.request.side_effect = TimeoutError("synthetic metadata deadline")
        with (
            patch.object(
                runner.http.client, "HTTPSConnection", return_value=connection
            ),
            self.assertRaises(runner.Rejected),
        ):
            GITLAB_JSON(
                self.config,
                "/job",
                "synthetic-unit-token",
                runner.time.monotonic() + 30,
            )
        self.assertEqual(connection.request.call_count, 1)

    def test_missing_fetch_auth_and_user_stages_execute_nothing(self):
        environment = dict(self.environment)
        environment.pop("CUSTOM_ENV_CI_JOB_TOKEN")
        with patch.object(runner, "command") as command:
            with self.assertRaises(runner.Rejected):
                self.executor.run("get_sources", environment)
            for stage in (
                "before_script",
                "after_script",
                "restore_cache",
                "download_artifacts",
                "upload_artifacts_on_success",
                "step_custom",
                "step_build_script",
            ):
                with self.subTest(stage=stage), self.assertRaises(runner.Rejected):
                    self.executor.run(stage, self.environment)
            self.executor.run("prepare_script", self.environment)
            self.executor.run("cleanup_file_variables", self.environment)
            command.assert_not_called()

    def test_script_path_is_not_opened_and_only_fixed_wrapper_receives_safe_environment(
        self,
    ):
        self.ready()
        malicious = self.root / "job-script"
        effect = self.root / "must-not-exist"
        malicious.write_text("#!/bin/sh\ntouch " + str(effect) + "\n")
        calls = []

        def command(argv, **kwargs):
            calls.append((argv, kwargs))
            self.executor.record_artifact(self.result()["apps"][0])
            return json.dumps(self.result()).encode()

        with (
            patch.object(runner, "load_config", return_value=self.config),
            patch.object(runner, "command", side_effect=command),
            patch.dict(os.environ, self.environment, clear=True),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                runner.main(
                    ["--config", "/fixed/config", "run", str(malicious), "step_script"]
                ),
                0,
            )
        self.assertFalse(effect.exists())
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(argv, [runner.WRAPPER])
        self.assertEqual(kwargs["cwd"], self.executor.source)
        self.assertEqual(
            set(kwargs["env"]),
            {
                "PATH",
                "CI_JOB_ID",
                "CI_PIPELINE_SOURCE",
                "CI_PROJECT_ID",
                "CI_MERGE_REQUEST_SOURCE_PROJECT_ID",
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME",
                "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME",
                "CI_COMMIT_SHA",
                "CI_MERGE_REQUEST_DIFF_BASE_SHA",
            },
        )
        self.assertNotIn("synthetic-unit-token", json.dumps(kwargs["env"]))
        self.assertEqual(json.loads(output.getvalue()), self.result())
        with patch.object(runner, "command") as command:
            with self.assertRaises(runner.Rejected):
                self.executor.run("step_script", self.environment)
            command.assert_not_called()

    def test_upstream_build_script_uses_fixed_wrapper_once_and_ignores_script_path(
        self,
    ):
        self.ready()
        nonexistent_script = self.root / "must-not-be-opened"

        def command(argv, **kwargs):
            self.assertEqual(argv, [runner.WRAPPER])
            self.assertEqual(kwargs["cwd"], self.executor.source)
            self.assertNotIn("CUSTOM_ENV_CI_JOB_TOKEN", kwargs["env"])
            self.assertNotIn("CUSTOM_ENV_BEFORE_SCRIPT", kwargs["env"])
            self.executor.record_artifact(self.result()["apps"][0])
            return json.dumps(self.result()).encode()

        with (
            patch.object(runner, "load_config", return_value=self.config),
            patch.object(runner, "command", side_effect=command) as fixed,
            patch.dict(os.environ, self.environment, clear=True),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                runner.main(
                    [
                        "--config",
                        "/fixed/config",
                        "run",
                        str(nonexistent_script),
                        "build_script",
                    ]
                ),
                0,
            )
        fixed.assert_called_once()
        self.assertFalse(nonexistent_script.exists())
        self.assertEqual(json.loads(output.getvalue()), self.result())
        self.assertEqual(self.executor.read()["state"], "validated")
        with patch.object(runner, "command") as fixed:
            for stage in ("step_script", "build_script"):
                with self.subTest(stage=stage), self.assertRaises(runner.Rejected):
                    self.executor.run(stage, self.environment)
            fixed.assert_not_called()

    def test_partial_success_survives_batch_failure_or_timeout_and_is_cleaned(self):
        for failure in (
            runner.Rejected("trusted_command_failed"),
            subprocess.TimeoutExpired([runner.WRAPPER], 3600),
        ):
            with self.subTest(failure=type(failure).__name__):
                if not self.executor.root.exists():
                    self.executor.prepare()
                self.ready()

                def fail_after_first_app(argv, failure=failure, **kwargs):
                    self.executor.record_artifact(self.result()["apps"][0])
                    raise failure

                with (
                    patch.object(runner, "command", side_effect=fail_after_first_app),
                    self.assertRaises(type(failure)),
                ):
                    self.executor.run("step_script", self.environment)
                self.assertEqual(
                    self.executor.read()["artifacts"], self.result()["apps"]
                )
                self.assertEqual(self.executor.read()["state"], "validating")
                labels = {
                    "miy.independent-app": "1",
                    "miy.app-id": "fixture-app",
                    "miy.source-revision": HEAD,
                    "miy.independent-build": "12345678-1234-1234-1234-123456789abc",
                    "miy.definition-digest": "sha256:" + "e" * 64,
                    "miy.builder-profile": "sha256:" + "f" * 64,
                }
                calls = []

                def cleanup_command(argv, calls=calls, labels=labels, **kwargs):
                    calls.append(argv)
                    if argv[-1] == "{{.Id}}":
                        return ARTIFACT.encode()
                    if argv[-1] == "{{json .Config.Labels}}":
                        return json.dumps(labels).encode()
                    return b""

                with patch.object(runner, "command", side_effect=cleanup_command):
                    self.executor.cleanup()
                self.assertEqual(
                    calls[-1], ["/usr/bin/docker", "image", "rm", ARTIFACT]
                )
                self.assertTrue(all(ARTIFACT in argv for argv in calls))
                self.assertFalse(self.executor.root.exists())

    def test_success_output_cannot_replace_durable_artifacts(self):
        self.ready()

        def altered_output(argv, **kwargs):
            self.executor.record_artifact(self.result()["apps"][0])
            return json.dumps({"state": "passed", "apps": []}).encode()

        with (
            patch.object(runner, "command", side_effect=altered_output),
            self.assertRaises(runner.Rejected),
        ):
            self.executor.run("step_script", self.environment)
        self.assertEqual(self.executor.read()["artifacts"], self.result()["apps"])
        with self.assertRaises(runner.Rejected):
            self.executor.record_artifact(self.result()["apps"][0])
        self.assertEqual(self.executor.read()["artifacts"], self.result()["apps"])

    def test_interrupted_journal_write_preserves_job_without_deleting_images(self):
        pending = self.executor.root / "ownership.json.tmp"
        pending.write_text("incomplete synthetic write")
        pending.chmod(0o600)
        with patch.object(runner, "command") as command:
            with self.assertRaises(runner.Rejected):
                self.executor.cleanup()
            command.assert_not_called()
        self.assertTrue(self.executor.root.exists())
        self.assertTrue(pending.exists())

    def test_cleanup_only_exact_owned_artifact_and_job_directory(self):
        receipt = self.executor.read()
        receipt.update(state="validated", artifacts=self.result()["apps"])
        self.executor.write(receipt)
        outside = self.root / "outside"
        outside.write_text("preserve unrelated data")
        (self.executor.source / "outside-link").symlink_to(outside)
        calls = []
        labels = {
            "miy.independent-app": "1",
            "miy.app-id": "fixture-app",
            "miy.source-revision": HEAD,
            "miy.independent-build": "12345678-1234-1234-1234-123456789abc",
            "miy.definition-digest": "sha256:" + "e" * 64,
            "miy.builder-profile": "sha256:" + "f" * 64,
        }

        def command(argv, **kwargs):
            calls.append(argv)
            if argv[-1] == "{{.Id}}":
                return ARTIFACT.encode()
            if argv[-1] == "{{json .Config.Labels}}":
                return json.dumps(labels).encode()
            return b""

        with patch.object(runner, "command", side_effect=command):
            self.executor.cleanup()
        self.assertEqual(calls[-1], ["/usr/bin/docker", "image", "rm", ARTIFACT])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(ARTIFACT in argv for argv in calls))
        self.assertFalse(self.executor.root.exists())
        self.assertEqual(outside.read_text(), "preserve unrelated data")
        self.executor.cleanup()  # Exact absent job is an idempotent no-op.

    def test_foreign_artifact_or_job_marker_never_deleted(self):
        receipt = self.executor.read()
        receipt.update(state="validated", artifacts=self.result()["apps"])
        self.executor.write(receipt)

        def command(argv, **kwargs):
            if argv[-1] == "{{.Id}}":
                return ARTIFACT.encode()
            self.assertNotIn("rm", argv)
            return json.dumps({"miy.app-id": "foreign-app"}).encode()

        with (
            patch.object(runner, "command", side_effect=command),
            self.assertRaises(runner.Rejected),
        ):
            self.executor.cleanup()
        self.assertTrue(self.executor.root.exists())
        self.assertEqual(self.executor.read()["state"], "cleanup_pending")
        receipt = self.executor.read()
        receipt["identity"]["head"] = "f" * 40
        self.executor.write(receipt)
        with patch.object(runner, "command") as command:
            with self.assertRaises(runner.Rejected):
                self.executor.cleanup()
            command.assert_not_called()
        self.assertTrue(self.executor.root.exists())

    def test_phase_override_is_rejected_without_echoing_input(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                runner.main(["--config", "/fixed/config", "shell", "synthetic-secret"]),
                1,
            )
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertEqual(
            json.loads(output.getvalue())["code"], "personal_app_runner_required"
        )

    def test_failure_diagnostics_redact_messages_unknown_reasons_and_attributes(self):
        secret = "synthetic-secret-never-printed"
        private_type = type(secret, (ValueError,), {})
        cases = (
            (PermissionError(secret), "unclassified_failure", "PermissionError", None),
            (
                runner.Rejected(secret, stage=[secret], http_status=secret),
                "unclassified_failure",
                "Rejected",
                None,
            ),
            (
                runner.Rejected("job_auth_required", stage=secret, http_status=True),
                "job_auth_required",
                "Rejected",
                None,
            ),
            (
                runner.Rejected(
                    "job_metadata_required", stage="mr_http", http_status=403
                ),
                "job_metadata_required",
                "Rejected",
                403,
            ),
            (
                subprocess.TimeoutExpired([secret], 1, output=secret, stderr=secret),
                "unclassified_failure",
                "TimeoutExpired",
                None,
            ),
            (private_type(secret), "unclassified_failure", "UnclassifiedError", None),
        )
        for error, reason, exception_type, status in cases:
            with (
                self.subTest(exception_type=exception_type, reason=reason),
                patch.object(runner, "load_config", side_effect=error),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(
                    runner.main(["--config", "/fixed/config", "prepare"]), 1
                )
            self.assertNotIn(secret, output.getvalue())
            expected = {
                "state": "failed",
                "code": "personal_app_runner_required",
                "stage": "mr_http" if status else "protected_config",
                "reason": reason,
                "exception_type": exception_type,
            }
            if status:
                expected["http_status"] = status
            self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertEqual(
            runner.failure_details(
                runner.Rejected([secret], stage={secret: secret}), [secret]
            ),
            {
                "stage": "unknown",
                "reason": "unclassified_failure",
                "exception_type": "Rejected",
            },
        )

    def test_metadata_assertion_diagnostics_distinguish_job_mr_and_missing_pipeline(
        self,
    ):
        cases = (
            ("job", "id", 124, "native_job_metadata_required", "native_job_assertion"),
            ("mr", "state", "closed", "mr_identity_required", "mr_assertion"),
            ("diff", "base_sha", HEAD, "mr_diff_required", "mr_assertion"),
            ("mr", "head_pipeline", None, "mr_pipeline_missing", "mr_assertion"),
            ("pipeline", "id", 46, "mr_pipeline_identity_required", "mr_assertion"),
            (
                "pipeline",
                "source",
                "synthetic-secret",
                "mr_pipeline_event_required",
                "mr_assertion",
            ),
        )
        original = copy.deepcopy((self.job_metadata, self.mr_metadata))
        for name, key, value, reason, stage in cases:
            self.job_metadata, self.mr_metadata = copy.deepcopy(original)
            target = {
                "job": self.job_metadata,
                "mr": self.mr_metadata,
                "diff": self.mr_metadata["diff_refs"],
                "pipeline": self.mr_metadata["head_pipeline"],
            }[name]
            target[key] = value
            with (
                self.subTest(reason=reason),
                patch.object(runner, "load_config", return_value=self.config),
                patch.object(runner, "command") as command,
                patch.dict(os.environ, self.environment, clear=True),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(
                    runner.main(
                        ["--config", "/fixed/config", "run", "/ignored", "get_sources"]
                    ),
                    1,
                )
            command.assert_not_called()
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "state": "failed",
                    "code": "personal_app_runner_required",
                    "stage": stage,
                    "reason": reason,
                    "exception_type": "Rejected",
                },
            )
            self.assertNotIn("synthetic-secret", output.getvalue())
            self.assertEqual(self.executor.read()["state"], "prepared")
            self.assertIsNone(self.executor.read()["verification"])
        self.job_metadata, self.mr_metadata = original

    def test_local_source_failures_report_stage_without_replaying_or_echoing_commands(
        self,
    ):
        for operation, stage in (
            ("init", "git_init"),
            ("remote", "git_remote"),
            ("fetch", "git_fetch"),
            ("rev-parse", "git_revision"),
            ("checkout", "git_checkout"),
        ):
            calls = []

            def fail_at_operation(argv, **kwargs):
                calls.append(argv)
                if operation in argv:
                    raise subprocess.TimeoutExpired(argv, 1, stderr="synthetic-secret")
                if "rev-parse" in argv:
                    return (argv[-1].removesuffix("^{commit}") + "\n").encode()
                return b""

            with (
                self.subTest(stage=stage),
                patch.object(runner, "load_config", return_value=self.config),
                patch.object(runner, "command", side_effect=fail_at_operation),
                patch.dict(os.environ, self.environment, clear=True),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(
                    runner.main(
                        ["--config", "/fixed/config", "run", "/ignored", "get_sources"]
                    ),
                    1,
                )
            self.assertEqual(sum(operation in argv for argv in calls), 1)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "state": "failed",
                    "code": "personal_app_runner_required",
                    "stage": stage,
                    "reason": "unclassified_failure",
                    "exception_type": "TimeoutExpired",
                },
            )
            self.assertNotIn("synthetic-secret", output.getvalue())
            self.assertNotIn(self.config.repository, output.getvalue())
            self.assertNotIn(str(self.executor.source), output.getvalue())
            self.assertEqual(self.executor.read()["state"], "prepared")
            self.assertIsNotNone(self.executor.read()["verification"])

    def test_http_diagnostics_include_only_native_stage_status_and_exception_type(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        for path, stage in (
            ("/job", "native_job_http"),
            ("/projects/1/merge_requests/7", "mr_http"),
        ):
            for status, failure in (
                (403, None),
                (200, TimeoutError("synthetic-secret")),
            ):
                response.status = status
                response.read1.side_effect = failure
                connection.request.reset_mock()
                with (
                    self.subTest(stage=stage, status=status),
                    patch.object(
                        runner.http.client, "HTTPSConnection", return_value=connection
                    ),
                    self.assertRaises(runner.Rejected) as caught,
                ):
                    GITLAB_JSON(
                        self.config,
                        path,
                        "synthetic-secret",
                        runner.time.monotonic() + 30,
                    )
                details = runner.failure_details(caught.exception, "source_metadata")
                self.assertEqual(
                    details,
                    {
                        "stage": stage,
                        "reason": "job_metadata_required",
                        "http_status": status,
                        "exception_type": "TimeoutError" if failure else "Rejected",
                    },
                )
                self.assertNotIn("synthetic-secret", json.dumps(details))
                connection.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
