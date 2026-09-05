from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"


class PosixInstallerTests(unittest.TestCase):
    def test_refuses_to_replace_unmanaged_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            skill_dir = root / "skills"
            bin_dir.mkdir()
            existing = bin_dir / "embedded-project"
            existing.write_text("user-owned\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                EMBEDDED_PLATFORM_BIN_DIR=str(bin_dir),
                EMBEDDED_PLATFORM_SKILL_DIR=str(skill_dir),
            )

            completed = subprocess.run(
                [str(INSTALLER)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(2, completed.returncode)
            self.assertEqual("user-owned\n", existing.read_text(encoding="utf-8"))
            self.assertIn("Refusing to replace existing path", completed.stderr)


if __name__ == "__main__":
    unittest.main()
