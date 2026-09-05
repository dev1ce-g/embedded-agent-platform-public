from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
BIN = RUNTIME.parent / "bin"
REPOSITORY = Path(__file__).resolve().parents[4]
SCHEMAS = REPOSITORY / "contracts" / "capability" / "v1" / "schemas"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(BIN))

from agent_backend_common import result as backend_result  # noqa: E402
from embedded_runtime_common import (  # noqa: E402
    CAPABILITY_RESULT_SCHEMA_VERSION,
    IGNORE_DIRS,
    RUNTIME_CONTRACT_VERSION,
    agent_paths,
    append_run,
    discover_background,
    safe_project_id,
    result as runtime_result,
)
import embedded_runtime_common  # noqa: E402
from embedded_runtime_cli import build_parser  # noqa: E402
from embedded_runtime_knowledge import build_knowledge  # noqa: E402


REQUIRED_RESULT_FIELDS = {
    "schema_version",
    "contract_version",
    "capability_id",
    "phase",
    "state",
    "ok",
    "operation",
    "exit_code",
    "timestamp",
    "evidence",
    "error",
}


class CapabilityContractTests(unittest.TestCase):
    def test_model_facing_knowledge_commands_do_not_export_to_host_paths(self) -> None:
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                ["knowledge", "export", "--project", "sample", "--to", "outside"]
            )

    def test_project_ids_are_canonical_and_cannot_escape_state(self) -> None:
        self.assertEqual("demo.project-1", safe_project_id("demo.project-1"))
        for value in (".", "..", "CON", "NUL.txt", "bad/name", "项目", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safe_project_id(value)

    def test_contract_schemas_are_json_and_local_refs_exist(self) -> None:
        expected = {
            "common.schema.json",
            "result.schema.json",
            "catalog.schema.json",
            "preflight.schema.json",
            "execution.schema.json",
            "status.schema.json",
            "receipt.schema.json",
            "job-request.schema.json",
        }
        self.assertEqual({path.name for path in SCHEMAS.glob("*.json")}, expected)
        for path in SCHEMAS.glob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
            pending = [document]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    reference = value.get("$ref")
                    if isinstance(reference, str) and not reference.startswith(("#", "http://", "https://")):
                        reference_path = reference.split("#", 1)[0]
                        self.assertTrue((path.parent / reference_path).is_file(), reference)
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)

    def test_result_schema_allows_optional_platform_version(self) -> None:
        document = json.loads((SCHEMAS / "result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(document["properties"]["platform_version"]["type"], "string")
        self.assertNotIn("platform_version", document["required"])

    def test_missing_platform_version_is_reported_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            embedded_runtime_common,
            "RUNTIME_SOURCE_HOME",
            Path(directory),
        ):
            self.assertEqual(embedded_runtime_common.platform_version(), "unknown")

    def test_runtime_and_backend_results_share_v1_envelope(self) -> None:
        runtime = runtime_result(True, "build", artifact={"path": "firmware.axf"})
        backend = backend_result(True, "build-mcu", artifact={"path": "firmware.axf"})
        for value in (runtime, backend):
            self.assertTrue(REQUIRED_RESULT_FIELDS.issubset(value))
            self.assertEqual(value["schema_version"], "embedded-capability-result/v1")
            self.assertEqual(value["contract_version"], "1.0.0")
            self.assertEqual(value["phase"], "execute")
            self.assertEqual(value["state"], "succeeded")
            self.assertIsNone(value["error"])
            self.assertEqual(value["evidence"], [])
            self.assertIn("artifact", value)
        self.assertEqual(runtime["capability_id"], "build")
        self.assertEqual(backend["capability_id"], "build.mcu")
        self.assertEqual(RUNTIME_CONTRACT_VERSION, "1.0.0")
        self.assertEqual(CAPABILITY_RESULT_SCHEMA_VERSION, "embedded-capability-result/v1")

    def test_jenkins_job_contract_uses_only_connection_id_binding(self) -> None:
        document = json.loads((SCHEMAS / "job-request.schema.json").read_text(encoding="utf-8"))
        parameters = document["$defs"]["jenkins_wait_parameters"]
        self.assertIn("connection_id", parameters["required"])
        self.assertNotIn("server", parameters["properties"])
        self.assertNotIn("config", parameters["properties"])

    def test_failure_keeps_legacy_fields_and_adds_machine_error(self) -> None:
        value = runtime_result(
            False,
            "flash",
            3,
            first_failure="Flash gate is closed",
            requires_human_confirm=True,
            blocked=True,
        )
        self.assertEqual(value["first_failure"], "Flash gate is closed")
        self.assertTrue(value["requires_human_confirm"])
        self.assertTrue(value["blocked"])
        self.assertEqual(value["state"], "approval_required")
        self.assertEqual(value["error"]["code"], "APPROVAL_REQUIRED")
        self.assertEqual(value["error"]["category"], "authorization")

    def test_explicit_async_state_is_preserved(self) -> None:
        value = runtime_result(True, "job-start", state="queued", job_id="job-1")
        self.assertEqual(value["state"], "queued")
        self.assertEqual(value["job_id"], "job-1")

    def test_gate_exit_code_is_machine_readable_without_legacy_hint(self) -> None:
        value = runtime_result(
            False,
            "jenkins-build-start",
            3,
            gate={"level": "CI_BUILD", "confirmed": False},
            first_failure="Build trigger requires --confirm",
        )
        self.assertEqual(value["state"], "approval_required")
        self.assertEqual(value["error"]["code"], "APPROVAL_REQUIRED")

    def test_runtime_discovery_ignores_platform_projection(self) -> None:
        self.assertIn(".embedded-agent", IGNORE_DIRS)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            generated = workspace / ".embedded-agent" / "context"
            generated.mkdir(parents=True)
            (generated / "generated.uvprojx").write_text("<Project/>", encoding="utf-8")
            background = discover_background("sample", workspace)
        self.assertEqual(background["toolchains"]["keil_projects"], [])

    def test_runtime_discovery_ignores_linked_projects_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            manifests = workspace / "manifests"
            manifests.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            outside_project = outside / "external.uvprojx"
            outside_project.write_text("<Project/>", encoding="utf-8")
            outside_manifest = outside / "external.xml"
            outside_manifest.write_text(
                '<manifest><project name="external" path="external"/></manifest>',
                encoding="utf-8",
            )
            try:
                (workspace / "linked.uvprojx").symlink_to(outside_project)
                (manifests / "linked.xml").symlink_to(outside_manifest)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")

            background = discover_background("sample", workspace)

        self.assertEqual(background["toolchains"]["keil_projects"], [])
        self.assertEqual(background["manifests"], [])
        self.assertEqual(background["fingerprints"], [])

    def test_runtime_discovery_does_not_enter_reparse_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            junction = workspace / "simulated-junction"
            junction.mkdir()
            (junction / "external.uvprojx").write_text("<Project/>", encoding="utf-8")
            manifest_dir = junction / "manifests"
            manifest_dir.mkdir()
            (manifest_dir / "external.xml").write_text("<manifest/>", encoding="utf-8")
            real_is_reparse_point = embedded_runtime_common.is_reparse_point

            def simulated_reparse(path: Path) -> bool:
                return path.name == junction.name or real_is_reparse_point(path)

            with mock.patch.object(
                embedded_runtime_common,
                "is_reparse_point",
                side_effect=simulated_reparse,
            ):
                background = discover_background("sample", workspace)

        self.assertEqual(background["toolchains"]["keil_projects"], [])
        self.assertEqual(background["manifests"], [])
        self.assertEqual(background["fingerprints"], [])

    def test_latest_evidence_never_mixes_an_older_success_with_a_new_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = agent_paths(root)
            background = {
                "project_id": "sample",
                "background_id": "bg-1",
                "workspace": str(root / "workspace"),
                "architecture": "mcu-only",
                "repos": [],
                "targets": {"mcu": {"build": {"method": "keil", "project": "mcu/app.uvprojx"}}},
                "toolchains": {"chips": [], "keil_projects": []},
            }
            append_run(
                paths,
                "sample",
                runtime_result(
                    True,
                    "build",
                    backend={
                        "ok": True,
                        "log": "success.log",
                        "artifact": {"path": "old.axf", "sha256": "a" * 64},
                    },
                ),
            )
            append_run(
                paths,
                "sample",
                runtime_result(
                    False,
                    "build",
                    1,
                    first_failure="new failure",
                    backend={"ok": False, "log": "failure.log", "first_failure": "new failure"},
                ),
            )
            latest = build_knowledge(paths, background)["profiles"]["evidence-index.json"]["latest_build"]
        self.assertFalse(latest["ok"])
        self.assertEqual(latest["log"], "failure.log")
        self.assertIsNone(latest["artifact"])
        self.assertEqual(latest["first_failure"], "new failure")


if __name__ == "__main__":
    unittest.main()
