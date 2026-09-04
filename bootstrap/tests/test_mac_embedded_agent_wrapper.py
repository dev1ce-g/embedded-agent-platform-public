from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "runtime" / "mac" / "bin" / "embedded-agent"


class MacEmbeddedAgentWrapperTests(unittest.TestCase):
    def test_relocated_runtime_configuration_is_forwarded(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")

        self.assertIn("EMBEDDED_AGENT_REMOTE_PREFIX", source)
        self.assertIn('"root": sys.argv[2]', source)
        self.assertIn('"agentctl": sys.argv[3]', source)
        self.assertIn('py -3 "$remote_script" --payload-b64 "$encoded"', source)
        self.assertNotIn("powershell -NoProfile", source)
        self.assertIn("embedded-agent git switch --project <id>", source)

    def run_wrapper(self, mode: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fake_ssh = Path(directory) / "ssh"
            fake_ssh.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${FAKE_SSH_MODE:-transport}\" == \"remote-error\" ]]; then\n"
                "  printf '%s\\n' '{\"ok\":false,\"operation\":\"status\",\"exit_code\":4}'\n"
                "  exit 4\n"
                "fi\n"
                "printf '%s\\n' 'ssh: connect to host test port 22: Operation timed out' >&2\n"
                "exit 255\n",
                encoding="utf-8",
            )
            fake_ssh.chmod(fake_ssh.stat().st_mode | stat.S_IXUSR)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{directory}{os.pathsep}{environment['PATH']}",
                    "EMBEDDED_AGENT_HOST": "test-agent",
                    "EMBEDDED_AGENT_REMOTE_PREFIX": r"C:\Users\test\AppData\Local\EmbeddedAgentPlatform",
                    "EMBEDDED_AGENT_CONNECT_TIMEOUT": "8",
                    "FAKE_SSH_MODE": mode,
                }
            )
            return subprocess.run(
                [str(WRAPPER), "status", "--json"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
                timeout=5,
            )

    def test_transport_failure_returns_structured_json(self) -> None:
        completed = self.run_wrapper("transport")

        self.assertEqual(255, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual("agent-transport", payload["operation"])
        self.assertEqual("SSH_TRANSPORT_UNAVAILABLE", payload["error_code"])
        self.assertEqual("test-agent", payload["host"])
        self.assertEqual(8, payload["connect_timeout_seconds"])
        self.assertIn("Operation timed out", completed.stderr)

    def test_remote_json_failure_is_not_reclassified_as_transport(self) -> None:
        completed = self.run_wrapper("remote-error")

        self.assertEqual(4, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("status", payload["operation"])
        self.assertNotIn("error_code", payload)

    def test_missing_configuration_returns_structured_json(self) -> None:
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith("EMBEDDED_AGENT_"):
                environment.pop(name)
        completed = subprocess.run(
            [str(WRAPPER), "status", "--json"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
            timeout=5,
        )

        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("SSH_TRANSPORT_CONFIGURATION_MISSING", payload["error_code"])


if __name__ == "__main__":
    unittest.main()
