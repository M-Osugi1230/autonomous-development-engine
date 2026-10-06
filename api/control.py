from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any


OWNER = "M-Osugi1230"
REPOSITORY = "autonomous-development-engine"
WORKFLOW = "control-command.yml"
PROJECTS = frozenset({"all", "jquants", "chu-kei", "jichi"})
COMMANDS = frozenset({"refresh", "resume", "replan", "submit_goal", "resolve_decision"})
MAX_BODY_BYTES = 20_000


def _github_token() -> str:
    return os.environ.get("ADE_GITHUB_TOKEN", "").strip()


def _validate_request(payload: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - {"project", "command", "payload"}
    if unknown:
        raise ValueError(f"unsupported request fields: {sorted(unknown)}")
    project = payload.get("project")
    command = payload.get("command")
    command_payload = payload.get("payload", {})
    if project not in PROJECTS:
        raise ValueError("unknown project")
    if command not in COMMANDS:
        raise ValueError("unknown command")
    if not isinstance(command_payload, dict):
        raise ValueError("payload must be a JSON object")
    if project == "all" and command != "refresh":
        raise ValueError("all is only valid for refresh")
    serialized = json.dumps(command_payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > 16_384:
        raise ValueError("command payload is too large")
    return project, command, command_payload


def _dispatch(project: str, command: str, payload: dict[str, Any]) -> None:
    token = _github_token()
    if not token:
        raise RuntimeError("ADE_GITHUB_TOKEN is not configured")
    workflow = urllib.parse.quote(WORKFLOW, safe="")
    url = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/actions/workflows/{workflow}/dispatches"
    body = json.dumps(
        {
            "ref": "main",
            "inputs": {
                "project": project,
                "command": command,
                "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ade-control-center",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read(1024)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(error_payload, dict) and isinstance(error_payload.get("message"), str):
                detail = f": {error_payload['message'][:160]}"
        except Exception:
            pass
        raise RuntimeError(f"GitHub workflow dispatch failed with HTTP {exc.code}{detail}") from exc


class handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/api/control":
            self._json(404, {"error": "not_found"})
            return
        self._json(
            200,
            {
                "schema_version": 1,
                "configured": bool(_github_token()),
                "projects": sorted(PROJECTS),
                "commands": sorted(COMMANDS),
            },
        )

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/control":
            self._json(404, {"error": "not_found"})
            return
        if not _github_token():
            self._json(
                503,
                {
                    "error": "setup_required",
                    "message": "Control Plane server credential is not configured.",
                },
            )
            return

        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._json(400, {"error": "invalid_content_length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(413, {"error": "invalid_body_size"})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
            project, command, command_payload = _validate_request(body)
            _dispatch(project, command, command_payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            self._json(400, {"error": "invalid_request", "message": message[:240]})
            return
        except RuntimeError as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            self._json(502, {"error": "dispatch_failed", "message": message[:240]})
            return

        self._json(
            202,
            {
                "accepted": True,
                "project": project,
                "command": command,
                "message": "Command accepted by the trusted Control Plane.",
            },
        )
