from __future__ import annotations

import importlib.util
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


installer = load_module("rule_bundle_installer", "rule_bundle_installer.py")


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class RuleBundleInstallerTests(unittest.TestCase):
    def make_template(self, root: Path, index: bytes = b"# Rules\n") -> Path:
        template = root / "template"
        (template / "nested").mkdir(parents=True)
        (template / "index.md").write_bytes(index)
        (template / "nested" / "safety.md").write_bytes(b"safe\n")
        return template

    def test_fresh_install_uses_platform_rule_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            template = self.make_template(root)

            result, lock = installer.install_rules(template, target)

            destination = target / ".embedded-agent" / "rules" / "platform"
            self.assertEqual(b"# Rules\n", (destination / "index.md").read_bytes())
            self.assertEqual(b"safe\n", (destination / "nested" / "safety.md").read_bytes())
            self.assertTrue((destination / installer.LOCK_NAME).is_file())
            self.assertEqual(installer.BUNDLE_ID, lock["bundle_id"])
            self.assertEqual(2, len(result.created))
            self.assertFalse((target / ".trellis").exists())

    def test_repeated_install_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            template = self.make_template(root)

            installer.install_rules(template, target)
            first = snapshot_tree(target)
            result, _ = installer.install_rules(template, target)
            second = snapshot_tree(target)

            self.assertEqual(first, second)
            self.assertEqual(2, len(result.skipped))
            self.assertEqual([], result.created)
            self.assertEqual([], result.updated)
            self.assertEqual([], result.candidates)

    def test_dry_run_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            (target / "keep.txt").write_bytes(b"keep\r\n")
            template = self.make_template(root)
            before = snapshot_tree(target)

            result, _ = installer.install_rules(template, target, dry_run=True)

            self.assertEqual(before, snapshot_tree(target))
            self.assertEqual(2, len(result.created))
            self.assertFalse((target / ".embedded-agent").exists())

    def test_user_modified_rule_becomes_candidate_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            template = self.make_template(root)
            destination = target / installer.RULE_DESTINATION / "index.md"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"project-owned\n")

            result, _ = installer.install_rules(template, target)

            candidate = installer.candidate_path(destination)
            self.assertEqual(b"project-owned\n", destination.read_bytes())
            self.assertEqual(b"# Rules\n", candidate.read_bytes())
            self.assertEqual([candidate.relative_to(target).as_posix()], result.candidates)

    def test_existing_different_candidate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            template = self.make_template(root)
            destination = target / installer.RULE_DESTINATION / "index.md"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"project-owned\n")
            candidate = installer.candidate_path(destination)
            candidate.write_bytes(b"reviewed-candidate\n")
            before = snapshot_tree(target)

            with self.assertRaisesRegex(ValueError, "candidate already contains different"):
                installer.install_rules(template, target)

            self.assertEqual(before, snapshot_tree(target))

    def test_platform_owned_rule_is_safely_updated_from_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            target.mkdir()
            template = self.make_template(root, b"v1\n")
            installer.install_rules(template, target)
            (template / "index.md").write_bytes(b"v2\n")

            result, _ = installer.install_rules(template, target)

            destination = target / installer.RULE_DESTINATION / "index.md"
            self.assertEqual(b"v2\n", destination.read_bytes())
            self.assertIn(destination.relative_to(target).as_posix(), result.updated)
            self.assertFalse(installer.candidate_path(destination).exists())

    def test_legacy_trellis_tree_is_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            legacy = target / ".trellis"
            (legacy / "spec").mkdir(parents=True)
            (legacy / "spec" / "index.md").write_bytes(b"legacy rule\n")
            (legacy / "workflow.md").write_bytes(b"legacy workflow\n")
            before = snapshot_tree(legacy)
            template = self.make_template(root)

            installer.install_rules(template, target)

            self.assertEqual(before, snapshot_tree(legacy))

    def test_nested_symlink_cannot_escape_rule_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            outside = root / "outside"
            target.mkdir()
            outside.mkdir()
            template = self.make_template(root)
            destination = target / installer.RULE_DESTINATION
            destination.mkdir(parents=True)
            try:
                (destination / "nested").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "symlink"):
                installer.install_rules(template, target)

            self.assertEqual({}, snapshot_tree(outside))
            self.assertFalse((destination / "index.md").exists())

    def test_atomic_write_failure_preserves_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "index.md"
            destination.write_bytes(b"old\n")

            with mock.patch.object(installer.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError, "injected"):
                    installer.atomic_write_bytes(destination, b"new\n", dry_run=False)

            self.assertEqual(b"old\n", destination.read_bytes())
            self.assertEqual([], list(destination.parent.glob(".index.md.*")))


if __name__ == "__main__":
    unittest.main()
