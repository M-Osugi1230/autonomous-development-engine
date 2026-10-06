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
PROJECTS = (
    ("jquants", "J-Quants", "ade-jquants"),
    ("chu-kei", "Chu-kei Insight", "ade-chu-kei"),
    ("jichi", "Jichi Insight", "ade-jichi-insight"),
)
MAX_REMOTE_BYTES = 512_000


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

    return {
        "key": key,
        "label": label,
        "control_ref": ref,
        "lifecycle": lifecycle,
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
