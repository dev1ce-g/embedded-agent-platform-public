from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"


def snapshot_project(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


@unittest.skipIf(os.name == "nt", "the POSIX installer requires a POSIX host")
class PlatformGoldenPathTests(unittest.TestCase):
    def run_project_command(
        self,
        command: Path,
        project: Path,
        *arguments: str,
        environment: dict[str, str],
    ) -> dict[str, object]:
        completed = subprocess.run(
            [str(command), *arguments, str(project), "--json"],
            cwd=project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"], payload)
        return payload

    def assert_git_ignored(self, project: Path, relative: str, expected: bool) -> None:
        completed = subprocess.run(
            ["git", "-C", str(project), "check-ignore", "-q", "--", relative],
            check=False,
        )
        self.assertEqual(0 if expected else 1, completed.returncode, relative)

    def test_installed_cli_completes_deterministic_trellis_free_golden_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            bin_dir = workspace / "bin"
            skill_dir = workspace / "skills"
            project = workspace / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)

            (project / "README.md").write_text("# Demo firmware\n", encoding="utf-8")
            (project / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(demo_firmware C)\n",
                encoding="utf-8",
            )
            source = project / "src"
            source.mkdir()
            (source / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")

            project_rule = project / ".embedded-agent" / "rules" / "project" / "project.md"
            knowledge = project / ".embedded-agent" / "knowledge" / "notes.md"
            evidence = project / ".embedded-agent" / "evidence" / "probe.json"
            project_rule.parent.mkdir(parents=True)
            knowledge.parent.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            project_rule.write_text("# Project rule\n", encoding="utf-8")
            knowledge.write_text("# Project knowledge\n", encoding="utf-8")
            evidence.write_text("{}\n", encoding="utf-8")

            environment = os.environ.copy()
            environment.update(
                EMBEDDED_PLATFORM_BIN_DIR=str(bin_dir),
                EMBEDDED_PLATFORM_SKILL_DIR=str(skill_dir),
                PATH=f"{bin_dir}{os.pathsep}{environment.get('PATH', '')}",
            )

            for _ in range(2):
                installed = subprocess.run(
                    [str(INSTALLER)],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, installed.returncode, installed.stderr)

            embedded_project = bin_dir / "embedded-project"
            self.assertTrue(embedded_project.is_symlink())
            self.assertEqual((ROOT / "bootstrap" / "embedded-project").resolve(), embedded_project.resolve())

            self.run_project_command(
                embedded_project,
                project,
                "init",
                "--discovery",
                "local",
                environment=environment,
            )
            self.run_project_command(
                embedded_project,
                project,
                "doctor",
                environment=environment,
            )
            first = snapshot_project(project)

            self.run_project_command(
                embedded_project,
                project,
                "refresh",
                "--discovery",
                "local",
                environment=environment,
            )
            self.run_project_command(
                embedded_project,
                project,
                "doctor",
                environment=environment,
            )
            second = snapshot_project(project)

            self.assertEqual(first, second)
            self.assertFalse((project / ".trellis").exists())
            active_parts = {
                part.lower()
                for path in project.rglob("*")
                if ".git" not in path.relative_to(project).parts
                for part in path.relative_to(project).parts
            }
            self.assertTrue({"workflow", "workflows", "tasks"}.isdisjoint(active_parts))

            self.assert_git_ignored(project, ".embedded-agent/manifest.json", True)
            self.assert_git_ignored(project, ".embedded-agent/rules/platform/index.md", True)
            self.assert_git_ignored(project, ".embedded-agent/context/project-profile.json", True)
            self.assert_git_ignored(project, ".embedded-agent/evidence/probe.json", True)
            self.assert_git_ignored(project, ".embedded-agent/rules/project/project.md", False)
            self.assert_git_ignored(project, ".embedded-agent/knowledge/notes.md", False)
            self.assert_git_ignored(project, "AGENTS.md", False)


if __name__ == "__main__":
    unittest.main()
