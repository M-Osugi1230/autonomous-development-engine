from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from api.control import (
    COMMANDS,
    MAX_BODY_BYTES,
    _dispatch,
    _github_token,
    _goal_preview,
    _validate_request,
)
from api.status import build_status


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "index.html"
GUIDE_PATH = ROOT / "guide.html"
_DASHBOARD_ACTIONS_MARKER = (
    '<div class="top-actions"><button type="button" class="button primary" '
    'id="refreshButton">最新状態を取得</button></div>'
)
_DASHBOARD_ACTIONS_WITH_GUIDE = (
    '<div class="top-actions">'
    '<a class="button" href="/guide" '
    'style="text-decoration:none;display:inline-flex;align-items:center">使い方</a>'
    '<button type="button" class="button primary" '
    'id="refreshButton">最新状態を取得</button></div>'
)


def _response(
    start_response: Callable[[str, list[tuple[str, str]]], Any],
    status: str,
    body: bytes,
    *,
    content_type: str,
) -> Iterable[bytes]:
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ]
    start_response(status, headers)
    return [body]


def _json_response(
    start_response: Callable[[str, list[tuple[str, str]]], Any],
    status: str,
    payload: dict[str, Any],
) -> Iterable[bytes]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _response(
        start_response,
        status,
        body,
        content_type="application/json; charset=utf-8",
    )


def _dashboard_body() -> bytes:
    html = INDEX_PATH.read_text(encoding="utf-8")
    if _DASHBOARD_ACTIONS_MARKER not in html:
        raise RuntimeError("dashboard action marker is missing")
    return html.replace(
        _DASHBOARD_ACTIONS_MARKER,
        _DASHBOARD_ACTIONS_WITH_GUIDE,
        1,
    ).encode("utf-8")


def _read_json_body(environ: dict[str, Any]) -> Any:
    raw_length = environ.get("CONTENT_LENGTH", "0")
    try:
        length = int(raw_length or "0")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > MAX_BODY_BYTES:
        raise ValueError("invalid body size")
    stream = environ.get("wsgi.input")
    if stream is None or not hasattr(stream, "read"):
        raise ValueError("missing request body")
    raw = stream.read(length)
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("invalid request body")
    try:
        return json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid UTF-8 JSON") from exc


def application(
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], Any],
) -> Iterable[bytes]:
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = str(environ.get("PATH_INFO", "/"))

    if method == "GET" and path in {"/", "/index.html"}:
        try:
            body = _dashboard_body()
        except (OSError, RuntimeError):
            return _json_response(
                start_response,
                "500 Internal Server Error",
                {"error": "dashboard_unavailable"},
            )
        return _response(
            start_response,
            "200 OK",
            body,
            content_type="text/html; charset=utf-8",
        )

    if method == "GET" and path in {"/guide", "/guide.html"}:
        try:
            body = GUIDE_PATH.read_bytes()
        except OSError:
            return _json_response(
                start_response,
                "500 Internal Server Error",
                {"error": "guide_unavailable"},
            )
        return _response(
            start_response,
            "200 OK",
            body,
            content_type="text/html; charset=utf-8",
        )

    if method == "GET" and path == "/api/status":
        try:
            payload = build_status()
        except Exception as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            return _json_response(
                start_response,
                "502 Bad Gateway",
                {"error": "status_unavailable", "message": message[:240]},
            )
        return _json_response(start_response, "200 OK", payload)

    if method == "GET" and path == "/api/control":
        return _json_response(
            start_response,
            "200 OK",
            {
                "schema_version": 1,
                "configured": bool(_github_token()),
                "projects": ["all", "chu-kei", "jichi", "jquants"],
                "commands": sorted(COMMANDS),
            },
        )

    if method == "POST" and path == "/api/control":
        if not _github_token():
            return _json_response(
                start_response,
                "503 Service Unavailable",
                {
                    "error": "setup_required",
                    "message": "Control Plane server credential is not configured.",
                },
            )
        try:
            request_payload = _read_json_body(environ)
            project, command, command_payload = _validate_request(request_payload)
            if command == "preview_goal":
                return _json_response(
                    start_response,
                    "200 OK",
                    _goal_preview(project, command_payload),
                )
            _dispatch(project, command, command_payload)
        except ValueError as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "invalid_request", "message": message[:240]},
            )
        except RuntimeError as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            return _json_response(
                start_response,
                "502 Bad Gateway",
                {"error": "dispatch_failed", "message": message[:240]},
            )
        return _json_response(
            start_response,
            "202 Accepted",
            {
                "accepted": True,
                "project": project,
                "command": command,
                "message": "Command accepted by the trusted Control Plane.",
            },
        )

    return _json_response(start_response, "404 Not Found", {"error": "not_found"})
