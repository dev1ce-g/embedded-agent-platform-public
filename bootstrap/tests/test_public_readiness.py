from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MARKERS = (
    "t-" + "box",
    "/mnt/d/" + "t-" + "box",
    "ai-" + "workspaces",
    "172.16." + "1.84",
    "hq" + "-",
    "hq" + "_",
    "deyi" + ".guan",
    "alex" + ".chen",
)
TEXT_SUFFIXES = {".bash", ".json", ".md", ".ps1", ".py", ".sh", ".toml", ".txt", ".yml", ".yaml"}


class PublicReadinessTests(unittest.TestCase):
    def test_tracked_source_has_no_known_machine_or_owner_markers(self) -> None:
        failures: list[str] = []
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        for relative in listed:
            path = ROOT / relative
            if not relative or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace").lower().replace("\\", "/")
            while "//" in content:
                content = content.replace("//", "/")
            for marker in FORBIDDEN_MARKERS:
                if marker in content:
                    failures.append(f"{relative}: {marker}")
        self.assertEqual([], failures, "private deployment markers found:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
