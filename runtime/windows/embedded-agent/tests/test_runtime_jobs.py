from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent
import embedded_runtime_jenkins as runtime_jenkins
import job_runner


class RuntimeJobRunnerTests(unittest.TestCase):
    def build_request(self, job_id: str, **overrides):
        request = {
            "schema_version": job_runner.REQUEST_SCHEMA_VERSION,
            "job_id": job_id,
            "project_id": "demo",
            "background_id": "demo:bg-1",
            "kind": "build",
            "operation_key": "demo:build:mpu",
            "parameters": {"target": "mpu", "sdk_path": None},
        }
        request.update(overrides)
        return request

    def jenkins_request(self, job_id: str):
        return {
            "schema_version": job_runner.REQUEST_SCHEMA_VERSION,
            "job_id": job_id,
            "project_id": "demo",
            "background_id": "demo:bg-1",
            "kind": "jenkins-wait",
            "operation_key": "demo:jenkins-wait:firmware-ci:firmware:42",
            "parameters": {
                "connection_id": "firmware-ci",
                "timeout": 20,
                "job": "firmware",
                "build": 42,
                "wait_timeout": 2700,
                "poll_interval": 10,
                "max_chars": 12000,
            },
        }

    def write_job(self, root: Path, request: dict) -> Path:
        directory = root / "jobs" / request["job_id"]
        directory.mkdir(parents=True)
        project_id = request.get("project_id")
        background_id = request.get("background_id")
        if isinstance(project_id, str) and isinstance(background_id, str):
            background_dir = root / "projects" / project_id
            background_dir.mkdir(parents=True, exist_ok=True)
            (background_dir / "background.json").write_text(
                json.dumps({"project_id": project_id, "background_id": background_id}),
                encoding="utf-8",
            )
        (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (directory / "status.json").write_text(
            json.dumps(
                {
                    "schema_version": job_runner.SCHEMA_VERSION,
                    "request_schema_version": request.get("schema_version"),
                    "job_id": directory.name,
                    "state": "queued",
                }
            ),
            encoding="utf-8",
        )
        return directory

    def test_build_request_rebuilds_fixed_runtime_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.build_request("job-build")
            command = job_runner.build_controlled_command(
                request,
                root=root,
            )
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, "embedded_agent.py")
        self.assertEqual(command[-6:], ["build", "--project", "demo", "--target", "mpu", "--json"])
        self.assertNotIn("embedded_runtime_jenkins.py", command)

    def test_jenkins_request_rebuilds_fixed_runtime_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.jenkins_request("job-jenkins")
            command = job_runner.build_controlled_command(
                request,
                root=root,
            )
        self.assertEqual(Path(command[1]).name, "embedded_agent.py")
        self.assertEqual(
            command[command.index("jenkins") :],
            [
                "jenkins",
                "--connection-id",
                "firmware-ci",
                "--timeout",
                "20",
                "build-wait",
                "--job",
                "firmware",
                "--build",
                "42",
                "--wait-timeout",
                "2700",
                "--poll-interval",
                "10",
                "--max-chars",
                "12000",
                "--json",
            ],
        )

    def test_jenkins_request_rejects_caller_selected_server_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            request = self.jenkins_request("job-tampered-connection")
            request["parameters"]["server"] = "https://attacker.example"
            request["parameters"]["config"] = str(Path(temp).resolve() / "stolen.json")
            with self.assertRaises(ValueError) as raised:
                job_runner.build_controlled_command(request, root=Path(temp).resolve())
        self.assertIn("unsupported fields: config, server", str(raised.exception))

    def test_runner_rejects_command_only_legacy_request_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = self.write_job(
                root,
                {
                    "schema_version": "embedded-runtime-job-request/v1",
                    "job_id": "job-legacy",
                    "command": [sys.executable, "-c", "raise SystemExit(0)"],
                },
            )
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 2)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertIn("must not contain a command field", status["first_failure"])

    def test_runner_rejects_injected_command_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.build_request("job-tampered")
            request["command"] = ["powershell", "-Command", "Write-Output compromised"]
            job_dir = self.write_job(root, request)
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 2)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertIn("must not contain a command field", status["first_failure"])

    def test_runner_rejects_unknown_kind_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.build_request(
                "job-unknown",
                kind="shell",
                operation_key="demo:shell",
                parameters={},
            )
            job_dir = self.write_job(root, request)
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 2)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["first_failure"], "Unsupported job kind: shell")

    def test_runner_rejects_background_replaced_after_job_was_queued(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.build_request("job-background-replaced")
            job_dir = self.write_job(root, request)
            background_path = root / "projects" / "demo" / "background.json"
            background_path.write_text(
                json.dumps({"project_id": "demo", "background_id": "demo:bg-2"}),
                encoding="utf-8",
            )
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 2)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertIn("background changed", status["first_failure"].lower())

    def test_runner_rejects_missing_background_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            request = self.build_request("job-background-missing")
            job_dir = self.write_job(root, request)
            (root / "projects" / "demo" / "background.json").unlink()
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 2)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertIn("background is missing", status["first_failure"].lower())

    def test_runner_persists_structured_success(self):
        class CompletedProcess:
            pid = 1234

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = self.write_job(root, self.build_request("job-success"))
            child = {"ok": True, "operation": "build", "exit_code": 0}

            def launch(*_args, **kwargs):
                kwargs["stdout"].write((json.dumps(child) + "\n").encode("utf-8"))
                kwargs["stdout"].flush()
                return CompletedProcess()

            with mock.patch.object(job_runner.subprocess, "Popen", side_effect=launch):
                self.assertEqual(job_runner.run_job(job_dir), 0)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "succeeded")
            self.assertEqual(result["operation"], "build")
            self.assertIn('"operation": "build"', (job_dir / "stdout.log").read_text(encoding="utf-8"))

    def test_runner_fails_closed_when_child_returns_no_structured_result(self):
        class EmptySuccessfulProcess:
            pid = 1234

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = self.write_job(root, self.build_request("job-empty-result"))
            with mock.patch.object(job_runner.subprocess, "Popen", return_value=EmptySuccessfulProcess()):
                self.assertEqual(job_runner.run_job(job_dir), 1)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["exit_code"], 1)
            self.assertFalse(result["ok"])
            self.assertIn("valid structured JSON", result["first_failure"])

    def test_cancel_marker_before_start_prevents_child_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = self.write_job(root, self.build_request("job-canceled"))
            (job_dir / "cancel.requested").write_text("{}", encoding="utf-8")
            with mock.patch.object(job_runner.subprocess, "Popen") as popen:
                self.assertEqual(job_runner.run_job(job_dir), 130)
            popen.assert_not_called()
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "canceled")


class RuntimeJobCommandTests(unittest.TestCase):
    def start_args(self, **overrides):
        values = {
            "root": Path("agent-root"),
            "agentctl": Path("agentctl.py"),
            "sdk_manager": Path("sdk_manager.py"),
            "kind": "build",
            "project": "demo",
            "target": "mpu",
            "sdk_path": None,
            "jenkins_job": None,
            "build": None,
            "connection_id": "firmware-ci",
            "timeout": 20,
            "wait_timeout": 2700,
            "poll_interval": 10,
            "max_chars": 12000,
        }
        values.update(overrides)
        return mock.Mock(**values)

    def test_build_job_is_a_structured_agent_command(self):
        command, key, failure = embedded_agent.runtime_job_command(self.start_args())
        self.assertIsNone(failure)
        self.assertEqual(key, "demo:build:mpu")
        self.assertEqual(Path(command[1]).name, "embedded_agent.py")
        self.assertIn("build", command)
        self.assertNotIn("powershell -Command", command)

    def test_mcu_alias_is_normalized_before_persistence(self):
        parameters, key, failure = embedded_agent.runtime_job_spec(self.start_args(target="mcu"))
        self.assertIsNone(failure)
        self.assertEqual(parameters, {"target": "keil", "sdk_path": None})
        self.assertEqual(key, "demo:build:keil")

    def test_global_executable_options_are_not_forwarded_to_job_child(self):
        malicious_agentctl = Path("attacker-agentctl.py").resolve()
        malicious_sdk_manager = Path("attacker-sdk-manager.py").resolve()
        command, _, failure = embedded_agent.runtime_job_command(
            self.start_args(
                agentctl=malicious_agentctl,
                sdk_manager=malicious_sdk_manager,
            )
        )
        self.assertIsNone(failure)
        self.assertNotIn(str(malicious_agentctl), command)
        self.assertNotIn(str(malicious_sdk_manager), command)
        agentctl = Path(command[command.index("--agentctl") + 1])
        self.assertEqual(agentctl, RUNTIME.parent / "bin" / "agentctl.py")

    def test_jenkins_wait_requires_job_and_build(self):
        command, key, failure = embedded_agent.runtime_job_command(
            self.start_args(kind="jenkins-wait", target=None)
        )
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertIn("--job and --build", failure)

    def test_jenkins_wait_rejects_invalid_connection_id(self):
        command, key, failure = embedded_agent.runtime_job_command(
            self.start_args(
                kind="jenkins-wait",
                target=None,
                jenkins_job="demo-job",
                build=42,
                connection_id="../../machine-config",
            )
        )
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertIn("valid --connection-id", failure)

    def test_unknown_kind_has_no_command_fallback(self):
        command, key, failure = embedded_agent.runtime_job_command(self.start_args(kind="shell"))
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertEqual(failure, "Unsupported job kind")

    def test_start_persists_v2_parameters_without_a_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args = self.start_args(root=root)
            args.job_action = "start"
            args.json = True
            background = {
                "project_id": "demo",
                "background_id": "demo:bg-1",
                "workspace": str(root / "workspace"),
                "targets": {"mpu": {"build": {"method": "docker"}}},
            }
            launcher = mock.Mock(pid=4321)
            output = io.StringIO()
            with (
                mock.patch.object(runtime_jenkins, "read_background", return_value=background),
                mock.patch.object(runtime_jenkins, "compare_background_fingerprints", return_value={"stale": False}),
                mock.patch.object(runtime_jenkins, "launch_runtime_job_runner", return_value=launcher) as launch,
                mock.patch.object(runtime_jenkins, "wait_for_runtime_job_start", return_value={"state": "running"}),
                mock.patch.object(runtime_jenkins, "append_run"),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(embedded_agent.start_runtime_job(args), 0)
            job_dir = next((root / "jobs").iterdir())
            request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(request["schema_version"], job_runner.REQUEST_SCHEMA_VERSION)
            self.assertEqual(request["parameters"], {"target": "mpu", "sdk_path": None})
            self.assertNotIn("command", request)
            self.assertEqual(status["schema_version"], job_runner.SCHEMA_VERSION)
            self.assertEqual(status["request_schema_version"], job_runner.REQUEST_SCHEMA_VERSION)
            launch.assert_called_once_with(job_dir)
            self.assertEqual(json.loads(output.getvalue())["request_schema_version"], job_runner.REQUEST_SCHEMA_VERSION)

    def test_jenkins_start_persists_only_connection_id_not_origin_or_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args = self.start_args(
                root=root,
                kind="jenkins-wait",
                target=None,
                jenkins_job="firmware",
                build=42,
            )
            args.job_action = "start"
            args.json = True
            background = {
                "project_id": "demo",
                "background_id": "demo:bg-1",
                "workspace": str(root / "workspace"),
                "targets": {},
            }
            launcher = mock.Mock(pid=4321)
            with (
                mock.patch.object(runtime_jenkins, "read_background", return_value=background),
                mock.patch.object(runtime_jenkins, "jenkins_connection", return_value=mock.Mock()) as resolve_connection,
                mock.patch.object(runtime_jenkins, "launch_runtime_job_runner", return_value=launcher),
                mock.patch.object(runtime_jenkins, "wait_for_runtime_job_start", return_value={"state": "running"}),
                mock.patch.object(runtime_jenkins, "append_run"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(embedded_agent.start_runtime_job(args), 0)
            request = json.loads(next((root / "jobs").iterdir()).joinpath("request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["parameters"]["connection_id"], "firmware-ci")
            self.assertNotIn("server", request["parameters"])
            self.assertNotIn("config", request["parameters"])
            resolve_connection.assert_called_once_with(args)

    def test_output_is_incremental_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = root / "jobs" / "job-output"
            job_dir.mkdir(parents=True)
            (job_dir / "status.json").write_text(json.dumps({"job_id": "job-output", "state": "running"}), encoding="utf-8")
            (job_dir / "stdout.log").write_bytes(b"0123456789")
            args = mock.Mock(root=root, job_id="job-output", stream="stdout", offset=2, max_bytes=4, json=True, job_action="output")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(embedded_agent.output_runtime_job(args), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["content"], "2345")
            self.assertEqual(value["next_offset"], 6)
            self.assertTrue(value["truncated"])
            self.assertFalse(value["eof"])
            self.assertEqual(value["phase"], "status")

    def test_terminal_v1_status_remains_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = root / "jobs" / "job-failed"
            job_dir.mkdir(parents=True)
            status = {
                "schema_version": job_runner.SCHEMA_VERSION,
                "job_id": "job-failed",
                "state": "failed",
                "exit_code": 1,
            }
            (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
            args = mock.Mock(root=root, job_id="job-failed", json=True, job_action="status")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(embedded_agent.show_runtime_job(args), 0)
            value = json.loads(output.getvalue())
            self.assertTrue(value["ok"])
            self.assertEqual(value["phase"], "status")
            self.assertEqual(value["state"], "failed")
            self.assertEqual(value["job"], status)

    def test_startup_failure_becomes_terminal_with_runner_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp).resolve()
            (job_dir / "status.json").write_text(json.dumps({"job_id": "failed", "state": "queued"}), encoding="utf-8")
            (job_dir / "runner.log").write_text("runner import failed\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.poll.return_value = 7
            status = embedded_agent.wait_for_runtime_job_start(job_dir, launcher, timeout=0.1)
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["exit_code"], 7)
            self.assertEqual(status["first_failure"], "runner import failed")

    def test_cancel_requires_confirmation_before_marker_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job_dir = root / "jobs" / "job-running"
            job_dir.mkdir(parents=True)
            (job_dir / "status.json").write_text(json.dumps({"job_id": "job-running", "state": "running"}), encoding="utf-8")
            args = mock.Mock(root=root, job_id="job-running", confirm=False, json=True, job_action="cancel")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(embedded_agent.cancel_runtime_job(args), 3)
            self.assertFalse((job_dir / "cancel.requested").exists())
            self.assertFalse(json.loads(output.getvalue())["gate"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
