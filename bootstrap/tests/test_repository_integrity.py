from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
INLINE_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))[^\n]*?\)"
)
REFERENCE_LINK_RE = re.compile(
    r'^\s{0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|([^\s]+))',
    re.MULTILINE,
)
CONFLICT_PREFIXES = (b"<<<<<<< ", b"||||||| ", b">>>>>>> ")
TRELLIS_REFERENCE_FILES = {
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "README.md",
    "README.zh-CN.md",
    "bootstrap/embedded_project.py",
    "bootstrap/project_discovery.py",
    "docs/architecture/project-projection-and-context.md",
    "install.sh",
    "runtime/windows/embedded-agent/embedded_runtime_common.py",
}
TRELLIS_REFERENCE_PREFIXES = (
    "bootstrap/tests/",
    "docs/migration/",
    "docs/refactoring/",
    "docs/releases/",
)


def repository_files() -> list[tuple[str, Path]]:
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8", errors="surrogateescape")
    files: list[tuple[str, Path]] = []
    for relative in listed.split("\0"):
        path = ROOT / relative
        if relative and path.is_file():
            files.append((relative, path))
    return files


def local_link_targets(markdown: str) -> list[str]:
    targets: list[str] = []
    for match in INLINE_LINK_RE.finditer(markdown):
        targets.append(match.group(1) or match.group(2))
    for match in REFERENCE_LINK_RE.finditer(markdown):
        targets.append(match.group(1) or match.group(2))
    return targets


def missing_local_link(source: Path, target: str) -> str | None:
    target = target.strip().replace(r"\ ", " ")
    if not target or target.startswith(("#", "/", "\\", "//")):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    relative = unquote(parsed.path)
    resolved = (source.parent / relative).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return target
    return None if resolved.exists() else target


def trellis_reference_is_allowed(relative: str) -> bool:
    return relative in TRELLIS_REFERENCE_FILES or relative.startswith(
        TRELLIS_REFERENCE_PREFIXES
    )


class RepositoryIntegrityTests(unittest.TestCase):
    def test_json_files_are_valid(self) -> None:
        failures: list[str] = []
        for relative, path in repository_files():
            if path.suffix.lower() != ".json":
                continue
            try:
                json.loads(
                    path.read_text(encoding="utf-8-sig"),
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"invalid JSON constant: {value}")
                    ),
                )
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                failures.append(f"{relative}: {exc}")
        self.assertEqual([], failures, "invalid JSON files:\n" + "\n".join(failures))

    def test_markdown_local_links_exist(self) -> None:
        failures: list[str] = []
        for relative, path in repository_files():
            if path.suffix.lower() != ".md":
                continue
            markdown = path.read_text(encoding="utf-8-sig")
            for target in local_link_targets(markdown):
                if missing := missing_local_link(path, target):
                    failures.append(f"{relative}: {missing}")
        self.assertEqual([], failures, "missing Markdown links:\n" + "\n".join(failures))

    def test_text_files_have_no_git_conflict_markers(self) -> None:
        failures: list[str] = []
        for relative, path in repository_files():
            content = path.read_bytes()
            if b"\0" in content:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if line == b"=======" or line.startswith(CONFLICT_PREFIXES):
                    failures.append(f"{relative}:{line_number}")
        self.assertEqual([], failures, "Git conflict markers found:\n" + "\n".join(failures))

    def test_trellis_references_are_migration_defense_or_tests_only(self) -> None:
        failures: list[str] = []
        for relative, path in repository_files():
            content = path.read_bytes()
            if b"\0" in content:
                continue
            if b"trellis" not in content.lower() and "trellis" not in relative.lower():
                continue
            if not trellis_reference_is_allowed(relative):
                failures.append(relative)
        self.assertEqual(
            [],
            failures,
            "Trellis references require an explicit migration, defensive, or test allowlist entry:\n"
            + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
