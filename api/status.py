from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any


OWNER = "M-Osugi1230"
REPOSITORY = "autonomous-development-engine"
PROJECTS = (
    ("jquants", "J-Quants", "ade-jquants"),
    ("chu-kei", "Chu-kei Insight", "ade-chu-kei"),
    ("jichi", "Jichi Insight", "ade-jichi-insight"),
)
MAX_REMOTE_BYTES = 512_000
STALE_AFTER_SECONDS = 6 * 60 * 60
ACTIVE_WORKFLOW_STATES = {"queued", "in_progress", "waiting", "requested", "pending"}


def _raw_json(ref: str, path: str, *, optional: bool = False) -> dict[str, Any]:
    quoted_ref = urllib.parse.quote(ref, safe="")
    quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    url = f"https://raw.githubusercontent.com/{OWNER}/{REPOSITORY}/{quoted_ref}/{quoted_path}"
    request = urllib.request.Request(url, headers={"User-Agent": "ade-control-center-status"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(MAX_REMOTE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return {}
        raise RuntimeError(f"status source {path} returned HTTP {exc.code}") from exc
    if len(data) > MAX_REMOTE_BYTES:
        raise RuntimeError(f"status source {path} exceeded the size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"status source {path} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"status source {path} must be a JSON object")
    return payload


def _github_api_json(path: str, params: dict[str, str] | None = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = f"https://api.github.com{path}"
    if query:
        url += f"?{query}"
    headers = {
        "User-Agent": "ade-control-center-status",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("ADE_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def fetch(request_headers: dict[str, str]) -> bytes:
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read(MAX_REMOTE_BYTES + 1)

    try:
        data = fetch(headers)
    except urllib.error.HTTPError as exc:
        if token and exc.code in {401, 403}:
            public_headers = {key: value for key, value in headers.items() if key != "Authorization"}
            try:
                data = fetch(public_headers)
            except urllib.error.HTTPError as public_exc:
                raise RuntimeError(f"GitHub API returned HTTP {public_exc.code}") from public_exc
        else:
            raise RuntimeError(f"GitHub API returned HTTP {exc.code}") from exc

    if len(data) > MAX_REMOTE_BYTES:
        raise RuntimeError("GitHub API response exceeded the size limit")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub API returned invalid JSON") from exc


def _latest_state_change(ref: str) -> str | None:
    payload = _github_api_json(
        f"/repos/{OWNER}/{REPOSITORY}/commits",
        {"sha": ref, "path": ".autodev/state.json", "per_page": "1"},
    )
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None
    commit = payload[0].get("commit")
    if not isinstance(commit, dict):
        return None
    for actor_key in ("committer", "author"):
        actor = commit.get(actor_key)
        if isinstance(actor, dict) and isinstance(actor.get("date"), str):
            return actor["date"]
    return None


def _workflow_snapshot(run_id: int | None) -> dict[str, Any]:
    if run_id is None:
        return {}
    payload = _github_api_json(f"/repos/{OWNER}/{REPOSITORY}/actions/runs/{run_id}")
    if not isinstance(payload, dict):
        return {}
    return {
        "run_id": run_id,
        "name": payload.get("name") if isinstance(payload.get("name"), str) else None,
        "status": payload.get("status") if isinstance(payload.get("status"), str) else None,
        "conclusion": payload.get("conclusion") if isinstance(payload.get("conclusion"), str) else None,
        "updated_at": payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
    }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _activity_state(
    lifecycle: str,
    *,
    last_state_change_at: str | None,
    workflow_status: str | None,
    next_system_action: str | None,
) -> str:
    if lifecycle == "COMPLETED":
        return "COMPLETED"
    if lifecycle == "FAILED":
        return "STOPPED"
    if lifecycle == "HUMAN_WAIT":
        return "BLOCKED"
    if lifecycle == "READY":
        return "IDLE"
    if lifecycle != "RUNNING":
        return "UNKNOWN"

    if workflow_status in ACTIVE_WORKFLOW_STATES:
        return "ACTIVE"

    changed_at = _parse_timestamp(last_state_change_at)
    age_seconds = None
    if changed_at is not None:
        age_seconds = max(0.0, (datetime.now(timezone.utc) - changed_at).total_seconds())

    if age_seconds is not None and age_seconds > STALE_AFTER_SECONDS:
        return "STALE"
    if next_system_action == "monitor-provider-session":
        return "MONITORING"
    return "ACTIVE"


def _open_decisions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    records = payload.get("decisions", [])
    if not isinstance(records, list):
        return result
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "OPEN":
            continue
        request = record.get("request")
        if not isinstance(request, dict):
            continue
        decision_id = request.get("decision_id")
        question = request.get("question")
        priority = request.get("priority")
        blocking_task_id = request.get("blocking_task_id")
        options = request.get("options")
        if not isinstance(decision_id, str) or not isinstance(question, str):
            continue
        if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
            continue
        result.append(
            {
                "decision_id": decision_id[:256],
                "question": question[:1000],
                "priority": priority if isinstance(priority, str) else None,
                "blocking_task_id": blocking_task_id if isinstance(blocking_task_id, str) else None,
                "options": [item[:256] for item in options[:8]],
            }
        )
    return result[:12]


def _project_snapshot(key: str, label: str, ref: str) -> dict[str, Any]:
    state = _raw_json(ref, ".autodev/state.json")
    campaign = _raw_json(ref, ".autodev/campaign.json", optional=True)
    decisions_payload = _raw_json(ref, ".autodev/decisions.json", optional=True)

    current_task_id = state.get("current_task_id")
    completed = state.get("completed_task_ids", [])
    failed = state.get("failed_task_ids", [])
    metadata = state.get("metadata", {})
    if not isinstance(completed, list):
        completed = []
    if not isinstance(failed, list):
        failed = []
    if not isinstance(metadata, dict):
        metadata = {}

    task_ids = campaign.get("task_ids", []) if isinstance(campaign, dict) else []
    if not isinstance(task_ids, list):
        task_ids = []
    campaign_completed = campaign.get("completed_task_ids", []) if isinstance(campaign, dict) else []
    if not isinstance(campaign_completed, list):
        campaign_completed = []
    completed_count = len(campaign_completed) if task_ids else len(completed)
    total_count = len(task_ids)
    open_decisions = _open_decisions(decisions_payload)

    if open_decisions:
        lifecycle = "HUMAN_WAIT"
    elif isinstance(current_task_id, str) and current_task_id:
        lifecycle = "RUNNING"
    elif failed:
        lifecycle = "FAILED"
    elif total_count > 0 and completed_count >= total_count:
        lifecycle = "COMPLETED"
    elif str(campaign.get("status", "")).upper() in {"COMPLETE", "COMPLETED"}:
        lifecycle = "COMPLETED"
    else:
        lifecycle = "READY"

    next_human = metadata.get("next_required_human_action")
    next_system = metadata.get("next_system_action")
    if not isinstance(next_human, str):
        next_human = None
    if not isinstance(next_system, str):
        next_system = None
    if open_decisions and next_human is None:
        next_human = "decision-required"

    goal = campaign.get("goal") if isinstance(campaign, dict) else None
    if not isinstance(goal, str):
        goal = None

    last_state_change_at = None
    try:
        last_state_change_at = _latest_state_change(ref)
    except Exception:
        pass

    implementation_run_id = metadata.get("implementation_workflow_run_id")
    if not isinstance(implementation_run_id, int):
        implementation_run_id = None
    workflow: dict[str, Any] = {}
    try:
        workflow = _workflow_snapshot(implementation_run_id)
    except Exception:
        workflow = {}

    activity = _activity_state(
        lifecycle,
        last_state_change_at=last_state_change_at,
        workflow_status=workflow.get("status") if isinstance(workflow.get("status"), str) else None,
        next_system_action=next_system,
    )

    return {
        "key": key,
        "label": label,
        "control_ref": ref,
        "lifecycle": lifecycle,
        "activity": activity,
        "last_state_change_at": last_state_change_at,
        "implementation_run": workflow,
        "campaign_id": campaign.get("campaign_id") if isinstance(campaign.get("campaign_id"), str) else None,
        "campaign_status": campaign.get("status") if isinstance(campaign.get("status"), str) else None,
        "goal": goal[:2000] if goal else None,
        "current_task_id": current_task_id if isinstance(current_task_id, str) else None,
        "completed_count": completed_count,
        "total_count": total_count,
        "failed_count": len(failed),
        "iteration": state.get("iteration") if isinstance(state.get("iteration"), int) else None,
        "next_human_action": next_human,
        "next_system_action": next_system,
        "open_decisions": open_decisions,
    }


def build_status() -> dict[str, Any]:
    projects: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for key, label, ref in PROJECTS:
        try:
            projects.append(_project_snapshot(key, label, ref))
        except Exception as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            errors.append({"project": key, "error": message[:240]})
            projects.append(
                {
                    "key": key,
                    "label": label,
                    "control_ref": ref,
                    "lifecycle": "UNKNOWN",
                    "activity": "UNKNOWN",
                    "last_state_change_at": None,
                    "implementation_run": {},
                    "campaign_id": None,
                    "campaign_status": None,
                    "goal": None,
                    "current_task_id": None,
                    "completed_count": 0,
                    "total_count": 0,
                    "failed_count": 0,
                    "iteration": None,
                    "next_human_action": None,
                    "next_system_action": None,
                    "open_decisions": [],
                }
            )
    return {
        "schema_version": 1,
        "controls_ready": bool(os.environ.get("ADE_GITHUB_TOKEN")),
        "projects": projects,
        "errors": errors,
    }


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
        if self.path.split("?", 1)[0] != "/api/status":
            self._json(404, {"error": "not_found"})
            return
        try:
            payload = build_status()
        except Exception as exc:
            message = str(exc).splitlines()[0].strip() or type(exc).__name__
            self._json(502, {"error": "status_unavailable", "message": message[:240]})
            return
        self._json(200, payload)
