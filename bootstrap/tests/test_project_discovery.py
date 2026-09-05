from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
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


discovery = load_module("project_discovery", "project_discovery.py")


def snapshot_tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ProjectDiscoveryProjectionTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "project"
        (project / "firmware" / "src").mkdir(parents=True)
        (project / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(demo)\n",
            encoding="utf-8",
        )
        (project / "firmware" / "src" / "main.c").write_text(
            "int main(void) { return 0; }\n",
            encoding="utf-8",
        )
        return project

    def run_discovery(self, project: Path, *extra: str) -> int:
        with redirect_stdout(StringIO()):
            return discovery.main(
                ["--root", str(project), "--json-summary", *extra]
            )

    def test_discovery_succeeds_without_trellis_and_writes_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))

            code = self.run_discovery(project)

            self.assertEqual(0, code)
            context = project / ".embedded-agent" / "context"
            self.assertTrue((context / "discovery-facts.json").is_file())
            self.assertTrue((context / "project-profile.json").is_file())
            self.assertTrue((context / "device-profile.json").is_file())
            self.assertTrue((context / "capability-profile.json").is_file())
            self.assertFalse((project / ".trellis").exists())

    def test_generated_projection_has_no_active_trellis_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))

            self.assertEqual(0, self.run_discovery(project))

            projection = snapshot_tree(project / ".embedded-agent")
            rendered = b"\n".join(projection.values()).lower()
            self.assertNotIn(b".trellis", rendered)
            self.assertNotIn(b"trellis task", rendered)

    def test_discovery_dry_run_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            before = snapshot_tree(project)

            code = self.run_discovery(project, "--dry-run")

            self.assertEqual(0, code)
            self.assertEqual(before, snapshot_tree(project))
            self.assertFalse((project / ".embedded-agent").exists())

    def test_unchanged_refresh_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            generated_times = [
                "2026-09-04T10:00:00+00:00",
                "2026-09-04T10:01:00+00:00",
            ]
            with mock.patch.object(discovery, "now_iso", side_effect=generated_times):
                self.assertEqual(0, self.run_discovery(project))
                first = snapshot_tree(project / ".embedded-agent")
                self.assertEqual(0, self.run_discovery(project))
                second = snapshot_tree(project / ".embedded-agent")

            self.assertEqual(first, second)

    def test_projection_is_not_scanned_as_project_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            projection = project / ".embedded-agent" / "context"
            projection.mkdir(parents=True)
            (projection / "build-generated.py").write_text(
                "raise RuntimeError('must never run')\n",
                encoding="utf-8",
            )

            state = discovery.ScanState(
                root=project,
                generated_at="2026-09-04T10:00:00+00:00",
            )
            files = discovery.walk_files(project)

            self.assertNotIn(projection / "build-generated.py", files)
            profiles = discovery.build_profiles(state, files)
            build_paths = {
                item["path"] for item in profiles["project_profile"]["build_systems"]
            }
            self.assertNotIn(
                ".embedded-agent/context/build-generated.py",
                build_paths,
            )

    def test_nested_symlink_cannot_escape_discovery_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            context = project / ".embedded-agent" / "context"
            outside = root / "outside"
            context.mkdir(parents=True)
            outside.mkdir()
            try:
                (context / "runbooks").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            self.assertEqual(2, self.run_discovery(project))
            self.assertEqual({}, snapshot_tree(outside))
            self.assertFalse((context / "discovery-facts.json").exists())

    def test_discovery_excludes_symlinked_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            outside = root / "outside"
            outside.mkdir()
            external_keil = outside / "external.uvprojx"
            external_keil.write_text(
                "<Project><TargetName>external-secret</TargetName></Project>\n",
                encoding="utf-8",
            )
            (outside / "CMakeLists.txt").write_text(
                "project(external-secret)\n",
                encoding="utf-8",
            )
            try:
                (project / "linked.uvprojx").symlink_to(external_keil)
                (project / "linked-tree").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            files = discovery.walk_files(project)
            self.assertNotIn(project / "linked.uvprojx", files)
            self.assertFalse(any("linked-tree" in path.parts for path in files))

            state = discovery.ScanState(
                root=project,
                generated_at="2026-09-04T10:00:00+00:00",
            )
            profiles = discovery.build_profiles(state, files)
            rendered = repr(profiles)
            self.assertNotIn("external-secret", rendered)
            self.assertNotIn("linked.uvprojx", rendered)
            self.assertNotIn("linked-tree", rendered)


if __name__ == "__main__":
    unittest.main()
