from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "runtime" / "wsl" / "bin" / "embedded-agent"


class WslEmbeddedAgentWrapperTests(unittest.TestCase):
    def test_transport_does_not_forward_launcher_owned_paths(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")

        self.assertIn('{"args": sys.argv[1:]}', source)
        self.assertNotIn("WSL_EMBEDDED_AGENT_ROOT", source)
        self.assertNotIn("WSL_EMBEDDED_AGENTCTL", source)

    def test_missing_configuration_returns_capability_contract_failure(self) -> None:
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith("WSL_EMBEDDED_AGENT") or name == "WSL_WINDOWS_CMD":
                environment.pop(name)

        completed = subprocess.run(
            [str(WRAPPER), "status", "--json"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
            timeout=5,
        )

        self.assertEqual(127, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("embedded-capability-result/v1", payload["schema_version"])
        self.assertEqual("1.0.0", payload["contract_version"])
        self.assertEqual("agent.transport", payload["capability_id"])
        self.assertEqual("execute", payload["phase"])
        self.assertEqual("failed", payload["state"])
        self.assertFalse(payload["ok"])
        self.assertEqual(127, payload["exit_code"])
        self.assertEqual([], payload["evidence"])
        self.assertEqual("WSL_WINDOWS_INTEROP_UNAVAILABLE", payload["error"]["code"])
        self.assertEqual("WSL_WINDOWS_INTEROP_UNAVAILABLE", payload["error_code"])


if __name__ == "__main__":
    unittest.main()
