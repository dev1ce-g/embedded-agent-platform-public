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
import job_runner


class RuntimeJobRunnerTests(unittest.TestCase):
    def write_job(self, directory: Path, command: list[str]) -> None:
        directory.mkdir()
        (directory / "request.json").write_text(
            json.dumps({"job_id": directory.name, "command": command}),
            encoding="utf-8",
        )
        (directory / "status.json").write_text(
            json.dumps({"schema_version": job_runner.SCHEMA_VERSION, "job_id": directory.name, "state": "queued"}),
            encoding="utf-8",
        )

    def test_runner_persists_structured_success(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp) / "job-success"
            child = {"ok": True, "operation": "test-child", "exit_code": 0}
            self.write_job(job_dir, [sys.executable, "-c", f"import json; print(json.dumps({child!r}))"])
            self.assertEqual(job_runner.run_job(job_dir), 0)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "succeeded")
            self.assertEqual(result["operation"], "test-child")
            self.assertIn("test-child", (job_dir / "stdout.log").read_text(encoding="utf-8"))

    def test_cancel_marker_before_start_prevents_child_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_dir = root / "job-canceled"
            sentinel = root / "must-not-exist"
            self.write_job(job_dir, [sys.executable, "-c", f"from pathlib import Path; Path({str(sentinel)!r}).write_text('bad')"])
            (job_dir / "cancel.requested").write_text("{}", encoding="utf-8")
            self.assertEqual(job_runner.run_job(job_dir), 130)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "canceled")
            self.assertFalse(sentinel.exists())


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
            "server": "http://jenkins",
            "config": Path("sdk.cfg"),
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
        self.assertIn("build", command)
        self.assertNotIn("powershell -Command", command)

    def test_jenkins_wait_requires_job_and_build(self):
        command, key, failure = embedded_agent.runtime_job_command(
            self.start_args(kind="jenkins-wait", target=None)
        )
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertIn("--job and --build", failure)

    def test_jenkins_wait_rejects_server_with_embedded_credentials(self):
        command, key, failure = embedded_agent.runtime_job_command(
            self.start_args(
                kind="jenkins-wait",
                target=None,
                jenkins_job="demo-job",
                build=42,
                server="http://user:secret@jenkins.example",
            )
        )
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertIn("without embedded credentials", failure)

    def test_unknown_kind_has_no_command_fallback(self):
        command, key, failure = embedded_agent.runtime_job_command(self.start_args(kind="shell"))
        self.assertIsNone(command)
        self.assertIsNone(key)
        self.assertEqual(failure, "Unsupported job kind")

    def test_output_is_incremental_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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

    def test_startup_failure_becomes_terminal_with_runner_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp)
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
            root = Path(temp)
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
