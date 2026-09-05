from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BOOTSTRAP = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOOTSTRAP / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# embedded_project imports the installer by its public module name.
load_module("rule_bundle_installer", "rule_bundle_installer.py")
project = load_module("embedded_project", "embedded_project.py")


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def init_args(target: Path, *extra: str):
    return project.parse_args(
        [
            "init",
            str(target),
            "--discovery",
            "skip",
            "--no-git-exclude",
            *extra,
        ]
    )


class EmbeddedProjectInitTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        target = root / "project"
        target.mkdir()
        (target / "README.md").write_bytes(b"# Demo\n")
        return target

    def test_version_matches_repository_version_file(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BOOTSTRAP / "embedded-project"), "--version"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        expected = (BOOTSTRAP.parent / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(f"embedded-project {expected}", completed.stdout.strip())

    def test_fresh_init_creates_model_independent_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))

            code, report = project.command_init(init_args(target))

            self.assertEqual(0, code, report)
            self.assertTrue(report["ok"])
            self.assertEqual("project-init", report["operation"])
            self.assertTrue((target / ".embedded-agent" / "manifest.json").is_file())
            self.assertTrue(
                (target / ".embedded-agent" / "rules" / "platform" / "index.md").is_file()
            )
            self.assertTrue((target / ".embedded-agent" / "knowledge").is_dir())
            self.assertTrue((target / ".embedded-agent" / "context" / "knowledge-index.json").is_file())
            self.assertFalse((target / ".trellis").exists())
            self.assertNotIn("workflow", report)
            self.assertNotIn("trellis_version", report)

    def test_fresh_init_never_probes_or_invokes_external_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))

            with mock.patch.object(
                project.subprocess,
                "run",
                side_effect=AssertionError("init unexpectedly invoked an external command"),
            ):
                code, report = project.command_init(init_args(target))

            self.assertEqual(0, code, report)
            commands = [step.get("command", []) for step in report["steps"]]
            rendered = "\n".join(" ".join(command) for command in commands).lower()
            self.assertNotIn("trellis", rendered)

    def test_explicit_project_id_rejects_path_and_windows_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for project_id in ("..", ".", "CON", "NUL.txt", "bad/name", "项目"):
                with self.subTest(project_id=project_id):
                    case_root = Path(directory) / project_id.encode("utf-8").hex()
                    case_root.mkdir()
                    target = self.make_project(case_root)
                    before = snapshot_tree(target)
                    code, report = project.command_init(
                        init_args(target, "--project-id", project_id)
                    )
                    self.assertEqual(2, code)
                    self.assertFalse(report["ok"])
                    self.assertEqual(before, snapshot_tree(target))

    def test_non_ascii_directory_name_gets_stable_derived_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case_root = Path(directory) / "嵌入式项目"
            case_root.mkdir()
            target = self.make_project(case_root)
            target = target.rename(case_root / "固件")
            code, report = project.command_init(init_args(target))
            self.assertEqual(0, code, report)
            project_id = report["manifest"]["project_id"]
            self.assertRegex(project_id, r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def test_repeated_init_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))

            first_code, first_report = project.command_init(init_args(target))
            first = snapshot_tree(target)
            second_code, second_report = project.command_init(init_args(target))
            second = snapshot_tree(target)

            self.assertEqual(0, first_code, first_report)
            self.assertEqual(0, second_code, second_report)
            self.assertEqual(first, second)

    def test_init_dry_run_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            (target / "AGENTS.md").write_bytes(b"# Project Rules\r\n\r\nKeep this.  \r\n")
            before = snapshot_tree(target)

            code, report = project.command_init(init_args(target, "--dry-run"))

            self.assertEqual(0, code, report)
            self.assertEqual(before, snapshot_tree(target))
            self.assertFalse((target / ".embedded-agent").exists())

    def test_git_exclude_keeps_project_rules_and_knowledge_trackable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            args = project.parse_args(
                ["init", str(target), "--discovery", "skip"]
            )

            code, report = project.command_init(args)

            self.assertEqual(0, code, report)
            exclude_path = Path(
                next(
                    step["exclude_path"]
                    for step in report["steps"]
                    if step["name"] == "local-git-exclude"
                )
            )
            excluded = exclude_path.read_text(encoding="utf-8")
            for expected in project.LOCAL_PROJECTION_PATHS:
                self.assertIn(expected, excluded)
            self.assertNotIn(".embedded-agent/rules/project/", excluded)
            self.assertNotIn(".embedded-agent/knowledge/", excluded)

    def test_existing_crlf_agents_content_is_preserved_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            original = (
                b"<!-- TRELLIS:START -->\r\n"
                b"legacy instructions\r\n"
                b"<!-- TRELLIS:END -->\r\n\r\n"
                b"# Project Rules\r\n\r\nKeep this.  \r\n"
            )
            (target / "AGENTS.md").write_bytes(original)

            code, report = project.command_init(init_args(target))

            self.assertEqual(0, code, report)
            rendered = (target / "AGENTS.md").read_bytes()
            self.assertTrue(rendered.startswith(original))
            self.assertIn(project.PROJECT_AGENTS_START.encode(), rendered)
            self.assertEqual(1, rendered.count(project.PROJECT_AGENTS_START.encode()))
            self.assertEqual(1, rendered.count(project.PROJECT_AGENTS_END.encode()))

    def test_managed_agents_replacement_preserves_prefix_and_suffix_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            prefix = b"# Project Prefix\r\n\r\n"
            suffix = b"\r\n\r\nProject suffix.  \r\n"
            old = (
                prefix
                + project.PROJECT_AGENTS_START.encode()
                + b"\r\nold platform rules\r\n"
                + project.PROJECT_AGENTS_END.encode()
                + suffix
            )
            (target / "AGENTS.md").write_bytes(old)

            code, report = project.command_init(init_args(target))

            self.assertEqual(0, code, report)
            rendered = (target / "AGENTS.md").read_bytes()
            self.assertTrue(rendered.startswith(prefix))
            self.assertTrue(rendered.endswith(suffix))
            self.assertNotIn(b"old platform rules", rendered)

    def test_malformed_agents_fails_before_projection_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            malformed = project.PROJECT_AGENTS_START.encode() + b"\nunfinished\n"
            (target / "AGENTS.md").write_bytes(malformed)
            before = snapshot_tree(target)

            code, report = project.command_init(init_args(target))

            self.assertEqual(2, code)
            self.assertFalse(report["ok"])
            self.assertEqual(before, snapshot_tree(target))
            self.assertFalse((target / ".embedded-agent").exists())

    def test_atomic_file_failure_preserves_existing_bytes_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "manifest.json"
            destination.write_bytes(b"old\n")

            with mock.patch.object(project.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError, "injected"):
                    project.atomic_write_bytes(destination, b"new\n")

            self.assertEqual(b"old\n", destination.read_bytes())
            self.assertEqual([], list(destination.parent.glob(".manifest.json.*")))

    def test_windows_init_uses_discovery_only_runtime_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            args = project.parse_args(
                [
                    "init",
                    str(target),
                    "--discovery",
                    "windows",
                    "--project-id",
                    "demo",
                    "--windows-agent-workspace",
                    r"D:\work\demo",
                    "--build-knowledge",
                    "--dry-run",
                    "--no-git-exclude",
                ]
            )
            commands: list[list[str]] = []

            def fake_step(name, command, cwd, dry_run, quiet):
                commands.append(command)
                return {
                    "name": name,
                    "command": command,
                    "cwd": str(cwd),
                    "dry_run": dry_run,
                    "ok": True,
                    "exit_code": 0,
                }

            with mock.patch.object(project, "run_step", side_effect=fake_step):
                code, report = project.command_init(args)

            self.assertEqual(0, code, report)
            self.assertEqual(
                ["status", "project", "knowledge"],
                [command[1] for command in commands],
            )
            self.assertIn("discover", commands[1])
            self.assertIn("build", commands[2])
            rendered = "\n".join(" ".join(command) for command in commands).lower()
            for forbidden in (" flash ", " reset ", " rtt ", " device ", " can ", " adb "):
                self.assertNotIn(forbidden, f" {rendered} ")
            self.assertNotIn("trellis", rendered)

    def test_windows_json_step_requires_complete_matching_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            cases = (
                ("", "empty stdout"),
                ("[]", "did not return an object"),
                ("{}", "incomplete Capability Contract"),
            )
            for output, expected in cases:
                with self.subTest(output=output):
                    script = f"print({output!r})" if output else "pass"
                    step = project.run_step(
                        "windows-agent-status",
                        [sys.executable, "-c", script, "--json"],
                        cwd,
                        False,
                        True,
                    )
                    self.assertFalse(step["ok"])
                    self.assertIn(expected, step["first_failure"])

    def test_doctor_validates_initialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            code, init_report = project.command_init(init_args(target))
            self.assertEqual(0, code, init_report)

            doctor_args = project.parse_args(["doctor", str(target)])
            doctor_code, report = project.command_doctor(doctor_args)

            self.assertEqual(0, doctor_code, report)
            self.assertTrue(report["ok"])
            self.assertTrue(all(check["ok"] for check in report["checks"]))

    def test_doctor_detects_modified_platform_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            code, init_report = project.command_init(init_args(target))
            self.assertEqual(0, code, init_report)
            rule = target / ".embedded-agent" / "rules" / "platform" / "index.md"
            rule.write_text("# Modified outside the bundle\n", encoding="utf-8")

            doctor_code, report = project.command_doctor(
                project.parse_args(["doctor", str(target)])
            )

            self.assertEqual(2, doctor_code)
            self.assertFalse(report["ok"])
            integrity = next(
                check for check in report["checks"]
                if check["name"] == "rule-bundle-integrity"
            )
            self.assertFalse(integrity["ok"])
            self.assertTrue(integrity["drift"])

    def test_refresh_is_byte_identical_after_first_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_project(Path(directory))
            code, init_report = project.command_init(init_args(target))
            self.assertEqual(0, code, init_report)
            args = project.parse_args(
                [
                    "refresh",
                    str(target),
                    "--discovery",
                    "skip",
                    "--no-git-exclude",
                ]
            )

            with mock.patch.object(project, "git_command", return_value=""):
                first_code, first_report = project.command_refresh(args)
                first = snapshot_tree(target)
                second_code, second_report = project.command_refresh(args)
                second = snapshot_tree(target)

            self.assertEqual(0, first_code, first_report)
            self.assertEqual(0, second_code, second_report)
            self.assertEqual(first, second)

    def test_cli_exposes_project_lifecycle_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory))
            cases = {
                "init": project.command_init,
                "refresh": project.command_refresh,
                "doctor": project.command_doctor,
                "migrate-trellis": project.command_migrate_trellis,
            }
            for name, function in cases.items():
                with self.subTest(command=name):
                    args = project.parse_args([name, target])
                    self.assertIs(function, args.func)

    def test_executable_shim_targets_embedded_project_module(self) -> None:
        source = (BOOTSTRAP / "embedded-project").read_text(encoding="utf-8")

        self.assertIn("embedded_project.py", source)
        self.assertNotIn("trellis_embedded_init.py", source)


class TrellisMigrationTests(unittest.TestCase):
    def make_legacy_project(self, root: Path) -> Path:
        target = root / "project"
        (target / ".trellis" / "spec" / "project").mkdir(parents=True)
        (target / ".trellis" / "knowledge" / "project" / "runbooks").mkdir(parents=True)
        (target / ".trellis" / "tasks").mkdir(parents=True)
        (target / ".trellis" / "agents").mkdir(parents=True)
        (target / "README.md").write_bytes(b"# Legacy project\n")
        (target / ".trellis" / "spec" / "project" / "project-profile.json").write_bytes(
            b'{"architecture":"mcu-only"}\n'
        )
        (target / ".trellis" / "spec" / "project-rule.md").write_bytes(
            b"# Project-specific legacy rule\n"
        )
        (target / ".trellis" / "spec" / "index.md").write_bytes(
            b"# Legacy platform rule index\n"
        )
        (target / ".trellis" / "knowledge" / "project" / "runbooks" / "debug.md").write_bytes(
            b"# Debug knowledge\n"
        )
        (target / ".trellis" / "workflow.md").write_bytes(b"legacy workflow\n")
        (target / ".trellis" / "tasks" / "task.md").write_bytes(b"legacy task\n")
        (target / ".trellis" / "agents" / "agent.md").write_bytes(b"legacy agent\n")
        return target

    def migrate_args(self, target: Path, *extra: str):
        return project.parse_args(
            ["migrate-trellis", str(target), "--no-git-exclude", *extra]
        )

    def test_explicit_migration_maps_content_and_preserves_legacy_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_legacy_project(Path(directory))
            legacy_before = snapshot_tree(target / ".trellis")

            with mock.patch.object(
                project.subprocess,
                "run",
                side_effect=AssertionError("migration must not invoke Trellis"),
            ):
                code, report = project.command_migrate_trellis(self.migrate_args(target))

            self.assertEqual(0, code, report)
            self.assertTrue(report["ok"])
            self.assertEqual(legacy_before, snapshot_tree(target / ".trellis"))
            self.assertEqual(
                b'{"architecture":"mcu-only"}\n',
                (target / ".embedded-agent" / "context" / "project-profile.json").read_bytes(),
            )
            self.assertEqual(
                b"# Debug knowledge\n",
                (
                    target
                    / ".embedded-agent"
                    / "knowledge"
                    / "project"
                    / "runbooks"
                    / "debug.md"
                ).read_bytes(),
            )
            self.assertEqual(
                b"# Project-specific legacy rule\n",
                (
                    target
                    / ".embedded-agent"
                    / "rules"
                    / "project"
                    / "project-rule.md"
                ).read_bytes(),
            )
            self.assertEqual(
                b"# Legacy platform rule index\n",
                (
                    target
                    / ".embedded-agent"
                    / "knowledge"
                    / "legacy-trellis-spec"
                    / "index.md"
                ).read_bytes(),
            )
            self.assertFalse(
                (target / ".embedded-agent" / "rules" / "project" / "index.md").exists()
            )
            migration = json.loads(
                (target / ".embedded-agent" / "context" / "trellis-migration.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(migration["source_preserved"])
            self.assertTrue(migration["legacy_only"]["workflow"])
            self.assertTrue(migration["legacy_only"]["tasks"])
            self.assertTrue(migration["legacy_only"]["agents"])

    def test_migration_is_byte_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_legacy_project(Path(directory))

            first_code, first_report = project.command_migrate_trellis(self.migrate_args(target))
            first = snapshot_tree(target)
            second_code, second_report = project.command_migrate_trellis(self.migrate_args(target))
            second = snapshot_tree(target)

            self.assertEqual(0, first_code, first_report)
            self.assertEqual(0, second_code, second_report)
            self.assertEqual(first, second)

    def test_migration_dry_run_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_legacy_project(Path(directory))
            before = snapshot_tree(target)

            code, report = project.command_migrate_trellis(
                self.migrate_args(target, "--dry-run")
            )

            self.assertEqual(0, code, report)
            self.assertEqual(before, snapshot_tree(target))
            self.assertFalse((target / ".embedded-agent").exists())

    def test_migration_conflict_creates_candidate_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_legacy_project(Path(directory))
            destination = target / ".embedded-agent" / "context" / "project-profile.json"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"new platform profile\n")

            code, report = project.command_migrate_trellis(self.migrate_args(target))

            self.assertEqual(0, code, report)
            self.assertEqual(b"new platform profile\n", destination.read_bytes())
            self.assertEqual(
                b'{"architecture":"mcu-only"}\n',
                destination.with_name("project-profile.json.trellis.new").read_bytes(),
            )

    def test_different_existing_candidate_fails_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_legacy_project(Path(directory))
            destination = target / ".embedded-agent" / "context" / "project-profile.json"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"new platform profile\n")
            destination.with_name("project-profile.json.trellis.new").write_bytes(
                b"reviewed candidate\n"
            )
            before = snapshot_tree(target)

            code, report = project.command_migrate_trellis(self.migrate_args(target))

            self.assertEqual(2, code)
            self.assertFalse(report["ok"])
            self.assertEqual(before, snapshot_tree(target))

    def test_migration_rejects_nested_destination_symlink_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_legacy_project(root)
            outside = root / "outside"
            outside.mkdir()
            knowledge = target / ".embedded-agent" / "knowledge"
            knowledge.mkdir(parents=True)
            try:
                (knowledge / "project").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            code, report = project.command_migrate_trellis(self.migrate_args(target))

            self.assertEqual(2, code)
            self.assertFalse(report["ok"])
            self.assertEqual({}, snapshot_tree(outside))
            self.assertFalse((target / ".embedded-agent" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
