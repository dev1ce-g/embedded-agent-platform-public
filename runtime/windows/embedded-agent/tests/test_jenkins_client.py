import base64
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jenkins_client import (
    CONNECTION_REGISTRY_SCHEMA_VERSION,
    JenkinsClient,
    JenkinsConnection,
    JenkinsError,
    _SameOriginRedirectHandler,
    default_connection_registry_path,
    load_jenkins_connection,
    load_sdk_credentials,
)
import embedded_agent
import embedded_runtime_jenkins


class JenkinsCredentialTests(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "sdk.cfg"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_ini_credentials(self):
        path = self.write_config("[jenkins]\nusername=builder\npassword=do-not-print\n")
        credentials = load_sdk_credentials(path, "https://jenkins.example.test")
        self.assertEqual(credentials.username, "builder")
        self.assertEqual(credentials.password, "do-not-print")
        self.assertEqual(credentials.config_format, "ini")

    def test_loads_nested_json_credentials(self):
        path = self.write_config(json.dumps({"jenkins": {"user": "builder", "token": "secret"}}))
        credentials = load_sdk_credentials(path, "https://jenkins.example.test")
        self.assertEqual(credentials.username, "builder")
        self.assertEqual(credentials.password, "secret")

    def test_missing_field_error_never_contains_values(self):
        path = self.write_config("server=http://jenkins\npassword=top-secret\n")
        with self.assertRaises(JenkinsError) as raised:
            load_sdk_credentials(path, "https://jenkins.example.test")
        self.assertNotIn("top-secret", str(raised.exception))


class JenkinsConnectionRegistryTests(unittest.TestCase):
    def write_registry(self, connection: dict, **root_overrides) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        document = {
            "schema_version": CONNECTION_REGISTRY_SCHEMA_VERSION,
            "connections": {"firmware-ci": connection},
        }
        document.update(root_overrides)
        path = Path(directory.name) / "jenkins-connections.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_resolves_server_and_credential_path_as_one_binding(self):
        credential_path = Path(tempfile.gettempdir()).resolve() / "jenkins-credentials.json"
        registry = self.write_registry(
            {"server": "https://jenkins.example.test/ci/", "credential_config": str(credential_path)}
        )
        connection = load_jenkins_connection(registry, "firmware-ci")
        self.assertEqual(connection.connection_id, "firmware-ci")
        self.assertEqual(connection.server, "https://jenkins.example.test/ci")
        self.assertEqual(connection.credential_config, credential_path)

    def test_task_environment_cannot_redirect_registry(self):
        with mock.patch.dict(os.environ, {"EMBEDDED_JENKINS_CONNECTIONS": "/tmp/attacker.json"}):
            path = default_connection_registry_path()
        self.assertEqual(path, Path(__file__).resolve().parents[2] / "jenkins-connections.json")

    def test_rejects_unknown_connection_id(self):
        registry = self.write_registry(
            {"server": "https://jenkins.example.test", "credential_config": str(Path(tempfile.gettempdir()).resolve() / "credentials.json")}
        )
        with self.assertRaises(JenkinsError) as raised:
            load_jenkins_connection(registry, "attacker")
        self.assertEqual(raised.exception.code, "CONNECTION_NOT_FOUND")

    def test_rejects_relative_credential_config(self):
        registry = self.write_registry(
            {"server": "https://jenkins.example.test", "credential_config": "project-controlled.json"}
        )
        with self.assertRaises(JenkinsError) as raised:
            load_jenkins_connection(registry, "firmware-ci")
        self.assertEqual(raised.exception.code, "INVALID_CONNECTION")

    def test_rejects_server_with_embedded_credentials(self):
        registry = self.write_registry(
            {"server": "https://user:secret@jenkins.example.test", "credential_config": str(Path(tempfile.gettempdir()).resolve() / "credentials.json")}
        )
        with self.assertRaises(JenkinsError) as raised:
            load_jenkins_connection(registry, "firmware-ci")
        self.assertEqual(raised.exception.code, "INVALID_CONNECTION")
        self.assertNotIn("secret", str(raised.exception))


class JenkinsHttpTests(unittest.TestCase):
    def test_authorization_is_sent_but_not_returned(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        response = mock.MagicMock()
        response.__enter__.return_value.geturl.return_value = "http://jenkins/me/api/json"
        response.__enter__.return_value.read.return_value = b'{"id":"builder"}'
        response.__enter__.return_value.headers.items.return_value = [("Content-Type", "application/json")]
        with mock.patch.object(client.opener, "open", return_value=response) as urlopen:
            value = client.auth_check()
        request = urlopen.call_args.args[0]
        expected = "Basic " + base64.b64encode(b"builder:secret").decode("ascii")
        self.assertEqual(request.get_header("Authorization"), expected)
        self.assertNotIn("builder", json.dumps(value))
        self.assertNotIn("secret", json.dumps(value))

    def test_http_auth_failure_is_classified_without_body(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        error = __import__("urllib.error").error.HTTPError("http://jenkins", 401, "denied secret", {}, None)
        with mock.patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(JenkinsError) as raised:
                client.auth_check()
        self.assertEqual(raised.exception.code, "AUTH_FAILED")
        self.assertNotIn("secret", str(raised.exception))

    def test_absolute_cross_origin_request_is_rejected_before_authorization_is_sent(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        with mock.patch.object(client.opener, "open") as opened:
            with self.assertRaises(JenkinsError) as raised:
                client.request("http://attacker.example/queue/1/api/json")
        self.assertEqual(raised.exception.code, "REQUEST_ORIGIN_NOT_ALLOWED")
        opened.assert_not_called()

    def test_queue_polling_cannot_follow_cross_origin_location(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        with mock.patch.object(client.opener, "open") as opened:
            with self.assertRaises(JenkinsError) as raised:
                client.wait_for_build_number("http://attacker.example/queue/1", timeout=1)
        self.assertEqual(raised.exception.code, "REQUEST_ORIGIN_NOT_ALLOWED")
        opened.assert_not_called()

    def test_build_start_rejects_cross_origin_queue_location_before_returning_it(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        with mock.patch.object(
            client,
            "request",
            return_value=(None, {"location": "http://attacker.example/queue/1"}),
        ):
            with self.assertRaises(JenkinsError) as raised:
                client.start_build("firmware", {})
        self.assertEqual(raised.exception.code, "QUEUE_LOCATION_NOT_ALLOWED")

    def test_redirect_handler_rejects_cross_origin_before_following(self):
        handler = _SameOriginRedirectHandler("https://jenkins.example.test")
        with self.assertRaises(JenkinsError) as raised:
            handler.redirect_request(None, None, 302, "redirect", {}, "https://attacker.example/steal")
        self.assertEqual(raised.exception.code, "REDIRECT_NOT_ALLOWED")


class JenkinsCommandEnvelopeTests(unittest.TestCase):
    def args(self):
        return mock.Mock(
            jenkins_action="build-wait",
            connection_id="firmware-ci",
            job="firmware",
            build=42,
            wait_timeout=60,
            poll_interval=1,
            max_chars=1000,
            json=True,
        )

    def client(self, build_result: str):
        client = mock.Mock()
        client.connection_id = "firmware-ci"
        client.server = "https://jenkins.example.test"
        client.credentials = mock.Mock(source="sdk-config", config_format="json")
        client.wait_for_completion.return_value = {
            "number": 42,
            "result": build_result,
            "building": False,
        }
        client.console_tail.return_value = {"text": "failed", "truncated": False}
        return client

    def test_failed_wait_constructs_one_consistent_failure_envelope(self):
        client = self.client("FAILURE")
        output = io.StringIO()
        with (
            mock.patch.object(embedded_runtime_jenkins, "jenkins_client", return_value=client),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(embedded_agent.command_jenkins(self.args()), 1)
        value = json.loads(output.getvalue())
        self.assertFalse(value["ok"])
        self.assertEqual(value["exit_code"], 1)
        self.assertEqual(value["state"], "failed")
        self.assertEqual(value["error"]["code"], "OPERATION_FAILED")
        self.assertIn("FAILURE", value["first_failure"])

    def test_successful_wait_has_no_failure_error(self):
        client = self.client("SUCCESS")
        output = io.StringIO()
        with (
            mock.patch.object(embedded_runtime_jenkins, "jenkins_client", return_value=client),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(embedded_agent.command_jenkins(self.args()), 0)
        value = json.loads(output.getvalue())
        self.assertTrue(value["ok"])
        self.assertEqual(value["exit_code"], 0)
        self.assertEqual(value["state"], "succeeded")
        self.assertIsNone(value["error"])
        self.assertNotIn("first_failure", value)


class JenkinsArtifactTests(unittest.TestCase):
    def client(self) -> JenkinsClient:
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        return JenkinsClient("http://jenkins", credentials)

    def response(self, payload: bytes, url: str = "http://jenkins/job/test/artifact/file.zip"):
        response = mock.MagicMock()
        entered = response.__enter__.return_value
        entered.geturl.return_value = url
        entered.headers.get.return_value = str(len(payload))
        entered.read.side_effect = [payload, b""]
        return response

    def test_downloads_and_atomically_publishes_verified_artifact(self):
        payload = b"verified artifact"
        expected = hashlib.sha256(payload).hexdigest()
        client = self.client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "nested" / "file.zip"
        with mock.patch.object(client.opener, "open", return_value=self.response(payload)) as opened:
            value = client.download_artifact("http://jenkins/job/test/artifact/file.zip", target, expected, 1024)
        self.assertEqual(target.read_bytes(), payload)
        self.assertTrue(value["verified"])
        self.assertEqual(value["sha256"], expected)
        self.assertEqual(opened.call_args.args[0].get_header("Authorization"), client.authorization)
        self.assertEqual(list(target.parent.glob("*.part")), [])

    def test_hash_mismatch_removes_partial_file(self):
        client = self.client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "file.zip"
        with mock.patch.object(client.opener, "open", return_value=self.response(b"wrong")):
            with self.assertRaises(JenkinsError) as raised:
                client.download_artifact("http://jenkins/job/test/artifact/file.zip", target, "0" * 64, 1024)
        self.assertEqual(raised.exception.code, "ARTIFACT_HASH_MISMATCH")
        self.assertFalse(target.exists())
        self.assertEqual(list(Path(directory.name).glob("*.part")), [])

    def test_rejects_cross_origin_before_sending_credentials(self):
        client = self.client()
        with mock.patch.object(client.opener, "open") as opened:
            with self.assertRaises(JenkinsError) as raised:
                client.download_artifact("http://other/artifact.zip", Path("unused"), "0" * 64, 1024)
        self.assertEqual(raised.exception.code, "ARTIFACT_ORIGIN_NOT_ALLOWED")
        opened.assert_not_called()

    def test_rejects_cross_origin_artifact_redirect(self):
        client = self.client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "file.zip"
        response = self.response(b"artifact", "http://attacker.example/file.zip")
        with mock.patch.object(client.opener, "open", return_value=response):
            with self.assertRaises(JenkinsError) as raised:
                client.download_artifact(
                    "http://jenkins/job/test/artifact/file.zip",
                    target,
                    hashlib.sha256(b"artifact").hexdigest(),
                    1024,
                )
        self.assertEqual(raised.exception.code, "ARTIFACT_REDIRECT_NOT_ALLOWED")
        self.assertFalse(target.exists())

    def test_default_http_port_is_same_origin(self):
        payload = b"artifact"
        expected = hashlib.sha256(payload).hexdigest()
        client = self.client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "file.zip"
        response = self.response(payload, "http://jenkins:80/artifact.zip")
        with mock.patch.object(client.opener, "open", return_value=response):
            client.download_artifact("http://jenkins:80/artifact.zip", target, expected, 1024)
        self.assertEqual(target.read_bytes(), payload)


class ArtifactCommandTests(unittest.TestCase):
    def args(self, root: Path, workspace: Path, **overrides):
        workspace.mkdir(parents=True, exist_ok=True)
        project_dir = root / "projects" / "test-project"
        project_dir.mkdir(parents=True)
        (project_dir / "background.json").write_text(
            json.dumps({"project_id": "test-project", "background_id": "bg-1", "workspace": str(workspace)}),
            encoding="utf-8",
        )
        values = {
            "root": root,
            "project": "test-project",
            "to": "artifacts/build.zip",
            "sha256": "0" * 64,
            "confirm": False,
            "connection_id": "firmware-ci",
            "timeout": 20,
            "url": "http://jenkins/artifact.zip",
            "max_bytes": 1024,
            "json": True,
        }
        values.update(overrides)
        return mock.Mock(**values)

    def test_confirmation_gate_precedes_credentials_and_network(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        args = self.args(base / "agent", base / "workspace")
        output = io.StringIO()
        connection = JenkinsConnection("firmware-ci", "http://jenkins", Path("/machine/credentials.json"))
        with (
            mock.patch.object(embedded_runtime_jenkins, "jenkins_connection", return_value=connection) as resolve_connection,
            mock.patch.object(embedded_runtime_jenkins, "jenkins_client") as client,
            contextlib.redirect_stdout(output),
        ):
            exit_code = embedded_agent.command_artifact(args)
        self.assertEqual(exit_code, 3)
        self.assertEqual(json.loads(output.getvalue())["gate"]["confirmed"], False)
        resolve_connection.assert_called_once_with(args)
        client.assert_not_called()

    def test_destination_must_remain_inside_registered_workspace(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        workspace = base / "workspace"
        workspace.mkdir()
        args = self.args(base / "agent", workspace, to="../escape.zip", confirm=True)
        output = io.StringIO()
        connection = JenkinsConnection("firmware-ci", "http://jenkins", Path("/machine/credentials.json"))
        with (
            mock.patch.object(embedded_runtime_jenkins, "jenkins_connection", return_value=connection),
            mock.patch.object(embedded_runtime_jenkins, "jenkins_client") as client,
            contextlib.redirect_stdout(output),
        ):
            exit_code = embedded_agent.command_artifact(args)
        self.assertEqual(exit_code, 5)
        self.assertFalse(json.loads(output.getvalue())["inside_workspace"])
        client.assert_not_called()

    def test_artifact_origin_must_match_selected_connection_before_credentials(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        args = self.args(base / "agent", base / "workspace", url="http://attacker.example/artifact.zip", confirm=True)
        connection = JenkinsConnection("firmware-ci", "http://jenkins", Path("/machine/credentials.json"))
        output = io.StringIO()
        with (
            mock.patch.object(embedded_runtime_jenkins, "jenkins_connection", return_value=connection),
            mock.patch.object(embedded_runtime_jenkins, "jenkins_client") as client,
            contextlib.redirect_stdout(output),
        ):
            exit_code = embedded_agent.command_artifact(args)
        self.assertEqual(exit_code, 2)
        self.assertIn("configured connection origin", json.loads(output.getvalue())["first_failure"])
        client.assert_not_called()


class JenkinsCliTests(unittest.TestCase):
    def test_connection_id_replaces_server_and_config_options(self):
        parser = embedded_agent.build_parser()
        args = parser.parse_args(["jenkins", "--connection-id", "firmware-ci", "auth-check"])
        self.assertEqual(args.connection_id, "firmware-ci")
        artifact = parser.parse_args(
            [
                "artifact",
                "download",
                "--connection-id",
                "artifact-store",
                "--project",
                "demo",
                "--url",
                "https://artifacts.example/file.zip",
                "--to",
                "artifacts/file.zip",
                "--sha256",
                "0" * 64,
            ]
        )
        self.assertEqual(artifact.connection_id, "artifact-store")
        legacy_options = (
            ["jenkins", "--server", "https://attacker.example", "auth-check"],
            ["jenkins", "--config", "project-secret.json", "auth-check"],
            ["artifact", "download", "--config", "project-secret.json"],
        )
        for command in legacy_options:
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(command)

    def test_workspace_remove_is_not_a_public_runtime_command(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            embedded_agent.build_parser().parse_args(
                ["workspace", "remove", "--project", "demo", "--confirm"]
            )


if __name__ == "__main__":
    unittest.main()
