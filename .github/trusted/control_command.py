from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ade.checkpoint import SECRET_PATTERNS
from ade.decision_store import DecisionStore
from ade.decisions import DecisionResponse, DecisionStatus
from ade.planning_activation import PlanningGoal


@dataclass(frozen=True, slots=True)
class ProjectPolicy:
    key: str
    control_ref: str
    target_repository: str
    allowed_path_prefixes: tuple[str, ...]
    repository_intelligence_prefixes: tuple[str, ...]
    min_tasks: int
    max_tasks: int


PROJECTS: dict[str, ProjectPolicy] = {
    "jquants": ProjectPolicy(
        key="jquants",
        control_ref="ade-jquants",
        target_repository="M-Osugi1230/jquants-research-studio",
        allowed_path_prefixes=("apps", "engine", "providers", "scripts", "supabase", "tests"),
        repository_intelligence_prefixes=("apps", "engine", "providers", "scripts", "supabase", "tests", "docs"),
        min_tasks=2,
        max_tasks=8,
    ),
    "chu-kei": ProjectPolicy(
        key="chu-kei",
        control_ref="ade-chu-kei",
        target_repository="M-Osugi1230/chu-kei",
        allowed_path_prefixes=("operations/plan-detection/candidates",),
        repository_intelligence_prefixes=(
            "operations/plan-detection",
            "operations/research-priority",
            "operations/quality-rebase/phase2/reviews",
            "operations/patches",
            "operations/source-research",
            "scripts",
            "docs",
        ),
        min_tasks=1,
        max_tasks=6,
    ),
    "jichi": ProjectPolicy(
        key="jichi",
        control_ref="ade-jichi-insight",
        target_repository="M-Osugi1230/jichi-insight",
        allowed_path_prefixes=("data/candidates", "tests"),
        repository_intelligence_prefixes=("docs", "data/catalog", "data/indexed", "data/candidates", "data/reviewed", "schemas", "tests"),
        min_tasks=1,
        max_tasks=4,
    ),
}

ALLOWED_COMMANDS = frozenset({"refresh", "resume", "replan", "submit_goal", "resolve_decision"})
MAX_PAYLOAD_BYTES = 16_384
MAX_GOAL_CHARS = 8_000


def _require_nonempty(value: Any, field: str, *, max_chars: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise ValueError(f"{field} is too long")
    if any(character in normalized for character in "\x00\r"):
        raise ValueError(f"{field} contains invalid control characters")
    return normalized


def _assert_safe_text(value: str, field: str) -> None:
    if "Traceback (most recent call last)" in value:
        raise ValueError(f"{field} must not contain a traceback")
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field} contains a forbidden secret pattern")


def _load_payload() -> dict[str, Any]:
    raw = os.environ.get("ADE_CONTROL_PAYLOAD", "{}")
    if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("control payload is too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("control payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("control payload must be a JSON object")
    return payload


def _repo_name() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "M-Osugi1230/autonomous-development-engine")
    if value != "M-Osugi1230/autonomous-development-engine":
        raise ValueError("trusted control command may only operate on the ADE controller repository")
    return value


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("GITHUB_TOKEN is required")
    return token


def _api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"https://api.github.com/repos/{_repo_name()}{path}"
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "User-Agent": "ade-control-center",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            decoded = json.loads(exc.read().decode("utf-8"))
            if isinstance(decoded, dict) and isinstance(decoded.get("message"), str):
                detail = f": {decoded['message'][:160]}"
        except Exception:
            pass
        raise RuntimeError(f"GitHub API {method} {path} failed with HTTP {exc.code}{detail}") from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _content_path(path: str, ref: str) -> str:
    quoted_path = urllib.parse.quote(path, safe="/")
    quoted_ref = urllib.parse.quote(ref, safe="")
    return f"/contents/{quoted_path}?ref={quoted_ref}"


def _read_text(path: str, ref: str) -> tuple[str, str]:
    payload = _api_request("GET", _content_path(path, ref))
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected content response for {path}")
    encoded = payload.get("content")
    sha = payload.get("sha")
    if not isinstance(encoded, str) or not isinstance(sha, str):
        raise ValueError(f"content response for {path} is missing content or sha")
    try:
        text = base64.b64decode(encoded, validate=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"content response for {path} is not valid UTF-8") from exc
    return text, sha


def _read_json(path: str, ref: str) -> tuple[dict[str, Any], str]:
    text, sha = _read_text(path, ref)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload, sha


def _write_text(path: str, ref: str, text: str, *, sha: str, message: str) -> None:
    quoted_path = urllib.parse.quote(path, safe="/")
    _api_request(
        "PUT",
        f"/contents/{quoted_path}",
        {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": ref,
            "sha": sha,
        },
    )


def _dispatch_repository_event(event_type: str, policy: ProjectPolicy) -> None:
    _api_request(
        "POST",
        "/dispatches",
        {
            "event_type": event_type,
            "client_payload": {
                "project_key": policy.key,
                "control_ref": policy.control_ref,
            },
        },
    )


def _dispatch_workflow(workflow_file: str) -> None:
    quoted = urllib.parse.quote(workflow_file, safe="")
    _api_request("POST", f"/actions/workflows/{quoted}/dispatches", {"ref": "main"})


def _project_is_idle(policy: ProjectPolicy) -> bool:
    state, _ = _read_json(".autodev/state.json", policy.control_ref)
    current_task_id = state.get("current_task_id")
    return current_task_id is None


def _build_goal(policy: ProjectPolicy, payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - {"goal"}
    if unknown:
        raise ValueError(f"submit_goal contains unsupported fields: {sorted(unknown)}")
    goal = _require_nonempty(payload.get("goal"), "goal", max_chars=MAX_GOAL_CHARS)
    _assert_safe_text(goal, "goal")
    if not _project_is_idle(policy):
        raise ValueError("project has an active task; submit a new goal only after the current campaign is idle")

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d%H%M%S")
    digest = hashlib.sha256(f"{policy.key}\n{goal}\n{stamp}".encode("utf-8")).hexdigest()[:8]
    compact_project = policy.key.replace("-", "")
    request_id = f"cc-{compact_project}-{stamp}-{digest}-request"
    campaign_id = f"cc-{compact_project}-{stamp}-{digest}-campaign"
    id_prefix = f"cc{compact_project[:8]}{digest[:6]}"

    result: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "campaign_id": campaign_id,
        "id_prefix": id_prefix,
        "goal": goal,
        "target_repository": policy.target_repository,
        "base_branch": "main",
        "allowed_path_prefixes": list(policy.allowed_path_prefixes),
        "repository_intelligence_prefixes": list(policy.repository_intelligence_prefixes),
        "execution_phase": "autonomous-development",
        "min_tasks": policy.min_tasks,
        "max_tasks": policy.max_tasks,
    }
    PlanningGoal.from_dict(result)
    return result


def _submit_goal(policy: ProjectPolicy, payload: dict[str, Any]) -> dict[str, Any]:
    goal_payload = _build_goal(policy, payload)
    _, sha = _read_text(".autodev/planning-goal.json", policy.control_ref)
    serialized = json.dumps(goal_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_text(
        ".autodev/planning-goal.json",
        policy.control_ref,
        serialized,
        sha=sha,
        message=f"control-center: submit goal for {policy.key}",
    )
    _dispatch_repository_event("ade_planner_retry", policy)
    return {
        "status": "accepted",
        "command": "submit_goal",
        "project": policy.key,
        "request_id": goal_payload["request_id"],
        "campaign_id": goal_payload["campaign_id"],
    }


def _resolve_decision(policy: ProjectPolicy, payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - {"decision_id", "option"}
    if unknown:
        raise ValueError(f"resolve_decision contains unsupported fields: {sorted(unknown)}")
    decision_id = _require_nonempty(payload.get("decision_id"), "decision_id", max_chars=256)
    option = _require_nonempty(payload.get("option"), "option", max_chars=256)
    _assert_safe_text(decision_id, "decision_id")
    _assert_safe_text(option, "option")

    text, sha = _read_text(".autodev/decisions.json", policy.control_ref)
    with tempfile.TemporaryDirectory(prefix="ade-control-decision-") as temp_dir:
        path = Path(temp_dir) / "decisions.json"
        path.write_text(text, encoding="utf-8")
        store = DecisionStore(path)
        record = store.get(decision_id)
        if record is None:
            raise ValueError("decision_id does not exist")
        if record.status is not DecisionStatus.OPEN:
            raise ValueError(f"decision is already {record.status.value}")
        if option not in record.request.options:
            raise ValueError("option must exactly match one of the open decision options")
        store.resolve(
            decision_id,
            DecisionResponse(decision_id=decision_id, text=option, selected_option=option),
        )
        serialized = path.read_text(encoding="utf-8")

    _write_text(
        ".autodev/decisions.json",
        policy.control_ref,
        serialized,
        sha=sha,
        message=f"control-center: resolve decision for {policy.key}",
    )
    _dispatch_repository_event("ade_resume_watch", policy)
    return {
        "status": "accepted",
        "command": "resolve_decision",
        "project": policy.key,
        "decision_id": decision_id,
        "selected_option": option,
    }


def run_command(project: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"unsupported command: {command}")

    if command == "refresh":
        if project not in PROJECTS and project != "all":
            raise ValueError("refresh project must be one of the trusted projects or all")
        if payload:
            raise ValueError("refresh does not accept payload fields")
        _dispatch_workflow("control-center.yml")
        return {"status": "accepted", "command": "refresh", "project": project}

    try:
        policy = PROJECTS[project]
    except KeyError as exc:
        raise ValueError(f"unknown project: {project}") from exc

    if command in {"resume", "replan"} and payload:
        raise ValueError(f"{command} does not accept payload fields")

    if command == "resume":
        _dispatch_repository_event("ade_resume_watch", policy)
        return {"status": "accepted", "command": command, "project": policy.key}
    if command == "replan":
        _dispatch_repository_event("ade_planner_retry", policy)
        return {"status": "accepted", "command": command, "project": policy.key}
    if command == "submit_goal":
        return _submit_goal(policy, payload)
    if command == "resolve_decision":
        return _resolve_decision(policy, payload)
    raise AssertionError("unreachable command")


def main() -> int:
    try:
        project = _require_nonempty(os.environ.get("ADE_CONTROL_PROJECT"), "project", max_chars=64)
        command = _require_nonempty(os.environ.get("ADE_CONTROL_COMMAND"), "command", max_chars=64)
        payload = _load_payload()
        result = run_command(project, command, payload)
    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:300]}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
