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
COMMANDS = frozenset(
    {"refresh", "resume", "replan", "submit_goal", "resolve_decision", "preview_goal"}
)
MAX_BODY_BYTES = 20_000
MAX_GOAL_CHARS = 4_000
MIN_PREVIEW_GOAL_CHARS = 20

# Read-only presentation metadata. The trusted GitHub controller remains authoritative.
# Tests pin these values to .github/trusted/control_command.py so a scope change cannot
# silently drift away from what the dashboard previews.
PREVIEW_POLICIES: dict[str, dict[str, Any]] = {
    "jquants": {
        "label": "J-Quants",
        "target_repository": "M-Osugi1230/jquants-research-studio",
        "allowed_path_prefixes": ["apps", "engine", "providers", "scripts", "supabase", "tests"],
        "repository_intelligence_prefixes": [
            "apps",
            "engine",
            "providers",
            "scripts",
            "supabase",
            "tests",
            "docs",
        ],
        "min_tasks": 2,
        "max_tasks": 8,
        "boundary": "既存のデータ取得上限・安全制約・Human Decision境界を維持したまま、機能・分析・DB・API・UI・テストを横断できます。",
    },
    "chu-kei": {
        "label": "Chu-kei Insight",
        "target_repository": "M-Osugi1230/chu-kei",
        "allowed_path_prefixes": ["operations/plan-detection/candidates"],
        "repository_intelligence_prefixes": [
            "operations/plan-detection",
            "operations/research-priority",
            "operations/quality-rebase/phase2/reviews",
            "operations/patches",
            "operations/source-research",
            "scripts",
            "docs",
        ],
        "min_tasks": 1,
        "max_tasks": 6,
        "boundary": "中期経営計画の候補データ領域だけを書き換えます。公開データやレビュー済みデータへの自動昇格は行いません。",
    },
    "jichi": {
        "label": "Jichi Insight",
        "target_repository": "M-Osugi1230/jichi-insight",
        "allowed_path_prefixes": ["data/candidates", "tests"],
        "repository_intelligence_prefixes": [
            "docs",
            "data/catalog",
            "data/indexed",
            "data/candidates",
            "data/reviewed",
            "schemas",
            "tests",
        ],
        "min_tasks": 1,
        "max_tasks": 4,
        "boundary": "非公開候補データと検証テストだけを書き換えます。reviewed/public領域への自動昇格は行いません。",
    },
}


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


def _goal_preview(project: str, payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - {"goal"}
    if unknown:
        raise ValueError(f"preview_goal contains unsupported fields: {sorted(unknown)}")
    goal = payload.get("goal")
    if not isinstance(goal, str):
        raise ValueError("goal must be a string")
    goal = goal.strip()
    if len(goal) < MIN_PREVIEW_GOAL_CHARS:
        raise ValueError(f"goal must be at least {MIN_PREVIEW_GOAL_CHARS} characters")
    if len(goal) > MAX_GOAL_CHARS:
        raise ValueError(f"goal must be at most {MAX_GOAL_CHARS} characters")
    if any(character in goal for character in "\x00\r"):
        raise ValueError("goal contains invalid control characters")

    policy = PREVIEW_POLICIES.get(project)
    if policy is None:
        raise ValueError("preview_goal requires a trusted project")

    min_tasks = int(policy["min_tasks"])
    max_tasks = int(policy["max_tasks"])
    return {
        "schema_version": 1,
        "preview": True,
        "project": project,
        "label": policy["label"],
        "goal": goal,
        "interpretation": {
            "intent": goal,
            "target_repository": policy["target_repository"],
            "execution_mode": "autonomous-development",
            "task_range": {"min": min_tasks, "max": max_tasks},
        },
        "trusted_scope": {
            "write": list(policy["allowed_path_prefixes"]),
            "read_for_understanding": list(policy["repository_intelligence_prefixes"]),
        },
        "execution_flow": [
            "Repository understanding",
            "Bounded plan / Task DAG",
            "Implementation",
            "Tests and validation",
            "Pull request / CI",
            "Runtime verification where applicable",
            "Next task selection until the Goal is complete",
        ],
        "success_gates": [
            "GoalをTrusted Scope内の変更だけで達成する",
            f"Plannerが{min_tasks}〜{max_tasks}個のbounded taskへ分解する",
            "実装後のテスト・検証を通過する",
            "既存のHuman Decision・release・security境界を維持する",
            "完了条件を満たすまで次タスクを自動選択する",
        ],
        "safety_boundary": policy["boundary"],
        "start_gate": "現在のCampaignがidleであること。開始時にTrusted Controllerが再検証します。",
        "notice": "これは実行前プレビューです。まだGitHub ActionsやPlannerは起動していません。",
    }


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
            if command == "preview_goal":
                self._json(200, _goal_preview(project, command_payload))
                return
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
