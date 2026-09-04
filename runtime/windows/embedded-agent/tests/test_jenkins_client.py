import base64
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jenkins_client import JenkinsClient, JenkinsError, load_sdk_credentials
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


class JenkinsHttpTests(unittest.TestCase):
    def test_authorization_is_sent_but_not_returned(self):
        credentials = mock.Mock(username="builder", password="secret", source="test", config_format="ini")
        client = JenkinsClient("http://jenkins", credentials)
        response = mock.MagicMock()
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
            "server": None,
            "config": Path("unused.cfg"),
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
        with mock.patch.object(embedded_runtime_jenkins, "jenkins_client") as client, contextlib.redirect_stdout(output):
            exit_code = embedded_agent.command_artifact(args)
        self.assertEqual(exit_code, 3)
        self.assertEqual(json.loads(output.getvalue())["gate"]["confirmed"], False)
        self.assertEqual(args.server, "http://jenkins")
        client.assert_not_called()

    def test_destination_must_remain_inside_registered_workspace(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        workspace = base / "workspace"
        workspace.mkdir()
        args = self.args(base / "agent", workspace, to="../escape.zip", confirm=True)
        output = io.StringIO()
        with mock.patch.object(embedded_runtime_jenkins, "jenkins_client") as client, contextlib.redirect_stdout(output):
            exit_code = embedded_agent.command_artifact(args)
        self.assertEqual(exit_code, 5)
        self.assertFalse(json.loads(output.getvalue())["inside_workspace"])
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
