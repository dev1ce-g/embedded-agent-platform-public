from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = load_module("trellis_embedded_init", "trellis_embedded_init.py")
fallback = load_module("embedded_spec_installer", "embedded_spec_installer.py")


class BootstrapCommandTests(unittest.TestCase):
    def test_registry_and_workflow_are_in_one_official_init_command(self):
        args = bootstrap.parse_args(
            [
                "/tmp/project",
                "--registry",
                "gh:example/embedded-agent-platform/marketplace#v1",
                "--template",
                "embedded-dual-machine-v1",
                "--workflow",
                "native",
                "--user",
                "tester",
                "--claude",
            ]
        )

        command = bootstrap.build_init_command(args)

        self.assertEqual(command[:2], ["trellis", "init"])
        self.assertIn("--codex", command)
        self.assertIn("--claude", command)
        self.assertEqual(command[command.index("--registry") + 1], args.registry)
        self.assertEqual(command[command.index("--template") + 1], args.template)
        self.assertEqual(command[command.index("--workflow") + 1], "native")
        self.assertIn("--append", command)

    def test_dry_run_registry_mode_does_not_create_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "not-created"
            output = StringIO()
            with redirect_stdout(output):
                code = bootstrap.main(
                    [
                        str(target),
                        "--registry",
                        "gh:example/embedded-agent-platform/marketplace#v1",
                        "--discovery",
                        "skip",
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(target.exists())
            rendered = output.getvalue()
            self.assertIn("trellis init", rendered)
            self.assertIn("--registry", rendered)
            self.assertNotIn("embedded_spec_installer.py", rendered)

    def test_windows_discovery_requires_complete_identity(self):
        args = bootstrap.parse_args(
            ["/tmp/project", "--discovery", "windows", "--project-id", "demo"]
        )
        with self.assertRaisesRegex(ValueError, "provided together"):
            bootstrap.discovery_mode(args)

    def test_git_mode_accepts_separate_human_and_agent_workspaces(self):
        args = bootstrap.parse_args(
            [
                "/tmp/project",
                "--project-id",
                "demo",
                "--windows-human-workspace",
                r"C:\Workspaces\human\demo",
                "--windows-agent-workspace",
                r"C:\Workspaces\agent\demo",
                "--sync-mode",
                "git",
            ]
        )
        self.assertEqual(args.windows_workspace, r"C:\Workspaces\agent\demo")
        self.assertEqual(bootstrap.discovery_mode(args), "windows")

    def test_workspace_manifest_records_git_commit_and_remote(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "project"
            target.mkdir()
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Test"], check=True)
            (target / "README.md").write_text("demo\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
            subprocess.run(["git", "-C", str(target), "remote", "add", "origin", "https://example.invalid/demo.git"], check=True)
            args = bootstrap.parse_args([
                str(target), "--project-id", "demo",
                "--windows-human-workspace", r"D:\human",
                "--windows-agent-workspace", r"D:\agent",
            ])
            step = bootstrap.write_workspace_manifest(target, args, False)
            self.assertTrue(step["ok"])
            self.assertEqual(step["manifest"]["sync_mode"], "git")
            self.assertEqual(step["manifest"]["repositories"][0]["remote"], "https://example.invalid/demo.git")
            self.assertTrue((target / bootstrap.WORKSPACE_MANIFEST_PATH).is_file())

    def test_windows_discovery_surface_has_no_hardware_or_build_action(self):
        args = bootstrap.parse_args(
            [
                "/tmp/project",
                "--discovery",
                "windows",
                "--project-id",
                "demo",
                "--windows-workspace",
                r"D:\work\demo",
                "--embedded-agent-command",
                "/opt/bin/embedded-agent",
                "--build-knowledge",
            ]
        )

        commands = bootstrap.windows_commands(args)
        flattened = "\n".join(" ".join(command) for _, command in commands)
        top_level_actions = {command[1] for _, command in commands}

        self.assertIn("project discover", flattened)
        self.assertIn("knowledge build", flattened)
        self.assertTrue(top_level_actions.isdisjoint({"build", "flash", "rtt", "log"}))

    def test_windows_discovery_forwards_explicit_keil_selection(self):
        args = bootstrap.parse_args(
            [
                "/tmp/project",
                "--discovery",
                "windows",
                "--project-id",
                "demo",
                "--windows-workspace",
                r"D:\work\demo",
                "--embedded-agent-command",
                "/opt/bin/embedded-agent",
                "--keil-project",
                "firmware/product.uvprojx",
            ]
        )

        discovery = dict(bootstrap.windows_commands(args))["windows-project-discovery"]

        self.assertIn("--keil-project", discovery)
        self.assertEqual(discovery[discovery.index("--keil-project") + 1], "firmware/product.uvprojx")

    def test_version_parser_uses_final_semver(self):
        output = "update available: 0.6.5 -> 0.6.6\n0.6.6\n"
        self.assertEqual(bootstrap.extract_version(output), (0, 6, 6))

    def test_zero_exit_with_error_text_is_rejected(self):
        step = {
            "exit_code": 0,
            "ok": True,
            "stdout": "setup output\nError: Registry has no index.json.",
            "stderr": "",
        }
        self.assertEqual(
            bootstrap.command_reported_error(step),
            "Error: Registry has no index.json.",
        )

    def test_local_projection_is_added_to_git_info_exclude(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "project"
            target.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(target)],
                check=True,
                stdout=subprocess.DEVNULL,
            )

            result = bootstrap.configure_local_git_exclude(target, dry_run=False)
            repeated = bootstrap.configure_local_git_exclude(target, dry_run=False)
            exclude = Path(result["exclude_path"]).read_text(encoding="utf-8")

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertFalse(repeated["changed"])
            for entry in bootstrap.LOCAL_PROJECTION_PATHS:
                self.assertIn(entry, exclude)

    def test_project_agents_block_preserves_trellis_and_project_content(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            original = (
                "<!-- TRELLIS:START -->\n"
                "managed by Trellis\n"
                "<!-- TRELLIS:END -->\n\n"
                "## Project Rules\n\nKeep this text.\n"
            )
            (target / "AGENTS.md").write_text(original, encoding="utf-8")

            first = bootstrap.install_project_agents(target, dry_run=False)
            second = bootstrap.install_project_agents(target, dry_run=False)
            rendered = (target / "AGENTS.md").read_text(encoding="utf-8")

            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertIn("<!-- TRELLIS:START -->", rendered)
            self.assertIn("Keep this text.", rendered)
            self.assertEqual(rendered.count(bootstrap.PROJECT_AGENTS_START), 1)
            self.assertEqual(rendered.count(bootstrap.PROJECT_AGENTS_END), 1)

    def test_project_agents_block_is_replaced_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            old = (
                "Project preface.\n\n"
                f"{bootstrap.PROJECT_AGENTS_START}\nold platform rules\n"
                f"{bootstrap.PROJECT_AGENTS_END}\n\nProject suffix.\n"
            )
            (target / "AGENTS.md").write_text(old, encoding="utf-8")

            result = bootstrap.install_project_agents(target, dry_run=False)
            rendered = (target / "AGENTS.md").read_text(encoding="utf-8")

            self.assertTrue(result["ok"])
            self.assertNotIn("old platform rules", rendered)
            self.assertIn("Project preface.", rendered)
            self.assertIn("Project suffix.", rendered)
            self.assertEqual(rendered.count(bootstrap.PROJECT_AGENTS_START), 1)

    def test_legacy_project_agents_block_is_migrated_without_duplication(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            old = (
                "Project preface.\n\n"
                f"{bootstrap.LEGACY_PROJECT_AGENTS_START}\nlegacy rules\n"
                f"{bootstrap.LEGACY_PROJECT_AGENTS_END}\n\nProject suffix.\n"
            )
            (target / "AGENTS.md").write_text(old, encoding="utf-8")

            result = bootstrap.install_project_agents(target, dry_run=False)
            rendered = (target / "AGENTS.md").read_text(encoding="utf-8")

            self.assertTrue(result["ok"])
            self.assertNotIn("legacy rules", rendered)
            self.assertNotIn(bootstrap.LEGACY_PROJECT_AGENTS_START, rendered)
            self.assertIn("Project preface.", rendered)
            self.assertIn("Project suffix.", rendered)
            self.assertEqual(rendered.count(bootstrap.PROJECT_AGENTS_START), 1)

    def test_project_agents_rejects_malformed_existing_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            original = f"{bootstrap.PROJECT_AGENTS_START}\nunfinished\n"
            (target / "AGENTS.md").write_text(original, encoding="utf-8")

            result = bootstrap.install_project_agents(target, dry_run=False)

            self.assertFalse(result["ok"])
            self.assertEqual((target / "AGENTS.md").read_text(encoding="utf-8"), original)

    def test_project_agents_rejects_reversed_existing_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            original = (
                f"{bootstrap.PROJECT_AGENTS_END}\nbody\n"
                f"{bootstrap.PROJECT_AGENTS_START}\n"
            )
            (target / "AGENTS.md").write_text(original, encoding="utf-8")

            result = bootstrap.install_project_agents(target, dry_run=False)

            self.assertFalse(result["ok"])
            self.assertEqual((target / "AGENTS.md").read_text(encoding="utf-8"), original)


class SpecFallbackTests(unittest.TestCase):
    def test_conflicts_become_candidates_and_runtime_state_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / "template"
            target = root / "target"
            (template / "nested").mkdir(parents=True)
            (template / "index.md").write_text("new index\n", encoding="utf-8")
            (template / "nested" / "rule.md").write_text("rule\n", encoding="utf-8")

            spec = target / ".trellis" / "spec"
            knowledge = target / ".trellis" / "knowledge"
            agents = target / ".trellis" / "agents"
            spec.mkdir(parents=True)
            knowledge.mkdir(parents=True)
            agents.mkdir(parents=True)
            (spec / "index.md").write_text("project index\n", encoding="utf-8")
            (knowledge / "keep.md").write_text("knowledge\n", encoding="utf-8")
            (agents / "keep.py").write_text("runtime\n", encoding="utf-8")
            workflow = target / ".trellis" / "workflow.md"
            workflow.write_text("native plus local changes\n", encoding="utf-8")

            result = fallback.install_spec(
                template,
                target,
                fallback.PRESET_NAME,
                overwrite=False,
                dry_run=False,
            )

            candidate = spec / "index.md.embedded-dual-machine.new"
            self.assertTrue(candidate.is_file())
            self.assertEqual((spec / "index.md").read_text(), "project index\n")
            self.assertTrue((spec / "nested" / "rule.md").is_file())
            self.assertEqual((knowledge / "keep.md").read_text(), "knowledge\n")
            self.assertEqual((agents / "keep.py").read_text(), "runtime\n")
            self.assertEqual(workflow.read_text(), "native plus local changes\n")
            self.assertEqual(len(result.candidates), 1)
            self.assertEqual(len(result.created), 1)

    def test_marketplace_index_resolves_to_spec_only(self):
        repo = SCRIPTS.parent
        index_path = repo / "marketplace" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = index["templates"][0]
        template = repo / entry["path"]

        self.assertEqual(entry["type"], "spec")
        self.assertEqual(entry["id"], bootstrap.DEFAULT_TEMPLATE)
        self.assertTrue((template / "index.md").is_file())
        self.assertFalse((template / ".trellis" / "agents").exists())
        self.assertFalse((template / ".trellis" / "knowledge").exists())


if __name__ == "__main__":
    unittest.main()
