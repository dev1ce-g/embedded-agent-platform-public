"""Small, credential-safe Jenkins HTTP client for the Windows runtime."""

from __future__ import annotations

import configparser
import hashlib
import http.cookiejar
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT = 20
SECRET_KEY_RE = re.compile(r"pass(word|wd)?|token|secret|credential", re.IGNORECASE)
USER_KEY_RE = re.compile(r"user(name)?|account|login|name", re.IGNORECASE)


class JenkinsError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    return parsed.scheme.lower(), parsed.hostname.lower() if parsed.hostname else None, port


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, server: str):
        self.server_origin = _origin(server)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != self.server_origin:
            raise JenkinsError("REDIRECT_NOT_ALLOWED", "Authenticated request redirected to another origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    output: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}.{index}"))
    elif value is not None:
        output[prefix] = str(value)
    return output


def _parse_config(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    stripped = raw.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return "json", _flatten(json.loads(raw))
        except json.JSONDecodeError:
            pass
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(raw)
            values: dict[str, str] = {}
            for elem in root.iter():
                if elem.text and elem.text.strip() and len(elem) == 0:
                    values[elem.tag] = elem.text.strip()
                for key, value in elem.attrib.items():
                    values[f"{elem.tag}.{key}"] = value
            return "xml", values
        except ET.ParseError:
            pass
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw if re.search(r"(?m)^\s*\[", raw) else "[default]\n" + raw)
        values = {}
        for section in parser.sections():
            for key, value in parser.items(section):
                values[f"{section}.{key}"] = value.strip()
        if values:
            return "ini", values
    except configparser.Error:
        pass
    values = {}
    for line in raw.splitlines():
        match = re.match(r"\s*([^#;=:\s][^=:]*?)\s*[=:]\s*(.*?)\s*$", line)
        if match:
            values[match.group(1).strip()] = match.group(2).strip()
    return "key-value" if values else "unknown", values


def _score_key(key: str, server: str, pattern: re.Pattern[str]) -> int:
    lowered = key.lower()
    score = 10 if pattern.search(lowered) else -100
    host = urllib.parse.urlparse(server).hostname or ""
    if "jenkins" in lowered:
        score += 8
    if host and host.lower() in lowered:
        score += 6
    if "sdk" in lowered:
        score += 1
    return score


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    source: str
    config_format: str


def load_sdk_credentials(path: Path, server: str) -> Credentials:
    if not path.is_file():
        raise JenkinsError("CREDENTIAL_CONFIG_NOT_FOUND", f"Credential config not found: {path}")
    config_format, values = _parse_config(path)
    user_candidates = sorted(values, key=lambda key: _score_key(key, server, USER_KEY_RE), reverse=True)
    secret_candidates = sorted(values, key=lambda key: _score_key(key, server, SECRET_KEY_RE), reverse=True)
    user_key = next((key for key in user_candidates if _score_key(key, server, USER_KEY_RE) >= 10 and values[key]), None)
    secret_key = next((key for key in secret_candidates if _score_key(key, server, SECRET_KEY_RE) >= 10 and values[key]), None)
    if not user_key or not secret_key:
        safe_keys = sorted(key for key in values if not SECRET_KEY_RE.search(key))[:50]
        raise JenkinsError(
            "CREDENTIAL_FIELDS_NOT_FOUND",
            f"No Jenkins username/password pair found; format={config_format}; non_secret_keys={safe_keys}",
        )
    return Credentials(values[user_key], values[secret_key], "sdk-config", config_format)


class JenkinsClient:
    def __init__(self, server: str, credentials: Credentials, timeout: int = DEFAULT_TIMEOUT):
        self.server = server.rstrip("/")
        self.credentials = credentials
        self.timeout = timeout
        token = f"{credentials.username}:{credentials.password}".encode("utf-8")
        import base64
        self.authorization = "Basic " + base64.b64encode(token).decode("ascii")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            _SameOriginRedirectHandler(self.server),
        )

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None, crumb: bool = False) -> tuple[Any, dict[str, str]]:
        url = path if path.startswith("http") else self.server + "/" + path.lstrip("/")
        headers = {"Authorization": self.authorization, "Accept": "application/json"}
        if crumb:
            crumb_data, _ = self.request("/crumbIssuer/api/json")
            headers[str(crumb_data["crumbRequestField"])] = str(crumb_data["crumb"])
        body = urllib.parse.urlencode(data or {}, doseq=True).encode("utf-8") if data is not None else None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                code = "AUTH_FAILED"
            elif exc.code == 403 and method == "POST":
                code = "CSRF_REJECTED"
            elif exc.code == 403:
                code = "ACCESS_DENIED"
            else:
                code = "JENKINS_HTTP_ERROR"
            raise JenkinsError(code, f"Jenkins returned HTTP {exc.code}", exc.code) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JenkinsError("JENKINS_UNREACHABLE", str(exc)) from None
        if not raw:
            return None, response_headers
        content_type = response_headers.get("content-type", "")
        if "json" in content_type or raw[:1] in (b"{", b"["):
            try:
                return json.loads(raw.decode("utf-8")), response_headers
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise JenkinsError("INVALID_RESPONSE", "Jenkins returned invalid JSON") from None
        return raw.decode("utf-8", errors="replace"), response_headers

    def download_artifact(
        self,
        url: str,
        target: Path,
        expected_sha256: str,
        max_bytes: int,
    ) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username is not None:
            raise JenkinsError("INVALID_ARTIFACT_URL", "Artifact URL must be HTTP(S) without embedded credentials")
        if _origin(url) != _origin(self.server):
            raise JenkinsError("ARTIFACT_ORIGIN_NOT_ALLOWED", "Artifact URL must use the configured server origin")

        request = urllib.request.Request(
            url,
            headers={"Authorization": self.authorization, "Accept": "application/octet-stream"},
            method="GET",
        )
        temp_path: Path | None = None
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                final_url = urllib.parse.urlsplit(response.geturl())
                if _origin(final_url.geturl()) != _origin(self.server):
                    raise JenkinsError("ARTIFACT_REDIRECT_NOT_ALLOWED", "Artifact download redirected to another origin")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise JenkinsError("ARTIFACT_TOO_LARGE", f"Artifact exceeds the {max_bytes}-byte limit")

                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                downloaded = 0
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{target.name}.",
                    suffix=".part",
                    dir=target.parent,
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise JenkinsError("ARTIFACT_TOO_LARGE", f"Artifact exceeds the {max_bytes}-byte limit")
                        digest.update(chunk)
                        handle.write(chunk)
            actual_sha256 = digest.hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                raise JenkinsError("ARTIFACT_HASH_MISMATCH", "Downloaded artifact SHA-256 does not match the requested digest")
            os.replace(temp_path, target)
            temp_path = None
            return {"size": downloaded, "sha256": actual_sha256, "verified": True}
        except urllib.error.HTTPError as exc:
            code = "AUTH_FAILED" if exc.code == 401 else "ACCESS_DENIED" if exc.code == 403 else "ARTIFACT_HTTP_ERROR"
            raise JenkinsError(code, f"Artifact server returned HTTP {exc.code}", exc.code) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JenkinsError("ARTIFACT_UNREACHABLE", str(exc)) from None
        except (OSError, ValueError) as exc:
            raise JenkinsError("ARTIFACT_IO_ERROR", str(exc)) from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def auth_check(self) -> dict[str, Any]:
        data, _ = self.request("/me/api/json?tree=id,fullName,authenticated")
        return {"authenticated": True, "principal": "masked", "identity_present": bool(data.get("id")), "display_name_present": bool(data.get("fullName"))}

    def job(self, job: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(job, safe="")
        data, _ = self.request(f"/job/{encoded}/api/json?tree=name,url,buildable,inQueue,nextBuildNumber,lastBuild[number,url],lastCompletedBuild[number,result],property[parameterDefinitions[name,type,defaultParameterValue[value]]]")
        return data

    def build_parameters(self, job: str, build: int) -> dict[str, Any]:
        encoded = urllib.parse.quote(job, safe="")
        data, _ = self.request(f"/job/{encoded}/{build}/api/json?tree=number,result,building,actions[parameters[name,value]]")
        parameters = {}
        for action in data.get("actions", []):
            for item in action.get("parameters", []) if isinstance(action, dict) else []:
                parameters[str(item.get("name"))] = item.get("value")
        return {"number": data.get("number"), "result": data.get("result"), "building": data.get("building"), "parameters": parameters}

    def build_status(self, job: str, build: int) -> dict[str, Any]:
        encoded = urllib.parse.quote(job, safe="")
        data, _ = self.request(f"/job/{encoded}/{build}/api/json?tree=number,url,result,building,duration,estimatedDuration,timestamp")
        return {
            "number": data.get("number"),
            "url": data.get("url"),
            "result": data.get("result"),
            "building": bool(data.get("building")),
            "duration_ms": data.get("duration"),
            "estimated_duration_ms": data.get("estimatedDuration"),
            "started_at_ms": data.get("timestamp"),
        }

    def wait_for_completion(self, job: str, build: int, timeout: int = 2700, interval: int = 10) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.build_status(job, build)
            if not status["building"] and status["result"]:
                return status
            time.sleep(max(1, interval))
        raise JenkinsError("BUILD_TIMEOUT", f"Build {build} did not finish within {timeout}s")

    def console_tail(self, job: str, build: int, max_chars: int = 12000) -> dict[str, Any]:
        encoded = urllib.parse.quote(job, safe="")
        text, _ = self.request(f"/job/{encoded}/{build}/consoleText")
        text = str(text).replace("\r", "")
        truncated = len(text) > max_chars
        tail = text[-max_chars:] if truncated else text
        return {"text": tail, "total_chars": len(text), "truncated": truncated}

    def start_build(self, job: str, parameters: dict[str, Any]) -> dict[str, Any]:
        encoded = urllib.parse.quote(job, safe="")
        endpoint = f"/job/{encoded}/buildWithParameters" if parameters else f"/job/{encoded}/build"
        _, headers = self.request(endpoint, method="POST", data=parameters, crumb=True)
        location = headers.get("location")
        if not location:
            raise JenkinsError("QUEUE_LOCATION_MISSING", "Jenkins accepted the request without a queue location")
        return {"queue_url": location}

    def wait_for_build_number(self, queue_url: str, timeout: int = 120) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data, _ = self.request(queue_url.rstrip("/") + "/api/json?tree=cancelled,why,executable[number,url]")
            if data.get("cancelled"):
                raise JenkinsError("QUEUE_CANCELLED", "Jenkins queue item was cancelled")
            executable = data.get("executable")
            if executable and executable.get("number") is not None:
                return int(executable["number"])
            time.sleep(2)
        raise JenkinsError("QUEUE_TIMEOUT", f"No build number assigned within {timeout}s")
