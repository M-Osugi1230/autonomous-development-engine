from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import autonomous_planner_cycle as planner_cycle
from ade.planning_activation import PlanningGoalRequest
from github_client import GitHubClient, GitHubError

COMPLETION_GOAL_PATH = Path(".autodev/completion-goal.json")
PLANNING_GOAL_PATH = Path(".autodev/planning-goal.json")
PLANNING_STATUS_PATH = Path(".autodev/runtime/planning-status.json")
STATE_PATH = Path(".autodev/state.json")
RESULT_PATH = Path(".autodev/runtime/autonomous-planner-result.json")
REMOTE_COMPLETION_STATUS_PATH = ".autodev/runtime/completion-status.json"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load(path)


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _safe_prefix(raw: object) -> str:
    value = "".join(ch for ch in str(raw).casefold() if ch.isalnum())[:12]
    if not value:
        raise ValueError("completion request_prefix must contain an alphanumeric character")
    return value


def _validate_completion_goal(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise ValueError("completion goal schema_version must be 1")

    required_strings = (
        "project_key",
        "request_prefix",
        "goal",
        "target_repository",
        "base_branch",
        "completion_marker_path",
    )
    for key in required_strings:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"completion goal {key} must be a non-empty string")

    if "/" not in payload["target_repository"]:
        raise ValueError("completion goal target_repository must be owner/name")

    for key in ("allowed_path_prefixes", "graduation_criteria"):
        value = payload.get(key)
        if not isinstance(value, list) or not value:
            raise ValueError(f"completion goal {key} must be a non-empty list")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"completion goal {key} entries must be non-empty strings")

    intelligence = payload.get("repository_intelligence_prefixes", [])
    if not isinstance(intelligence, list) or not all(
        isinstance(item, str) and item.strip() for item in intelligence
    ):
        raise ValueError(
            "completion goal repository_intelligence_prefixes must be a list of strings"
        )

    min_tasks = payload.get("min_tasks", 1)
    max_tasks = payload.get("max_tasks", 8)
    if type(min_tasks) is not int or type(max_tasks) is not int:
        raise ValueError("completion goal task bounds must be integers")
    if min_tasks < 1 or max_tasks < min_tasks or max_tasks > 8:
        raise ValueError("completion goal task bounds are invalid")

    marker = payload["completion_marker_path"].strip()
    if marker.startswith("/") or "\\" in marker or ".." in marker.split("/"):
        raise ValueError("completion marker path is unsafe")
    roots = tuple(item.strip().rstrip("/") for item in payload["allowed_path_prefixes"])
    if not any(marker == root or marker.startswith(root + "/") for root in roots):
        raise ValueError("completion marker must be inside an allowed path prefix")

    return {
        **payload,
        "project_key": payload["project_key"].strip(),
        "request_prefix": _safe_prefix(payload["request_prefix"]),
        "goal": " ".join(payload["goal"].split()),
        "target_repository": payload["target_repository"].strip(),
        "base_branch": payload["base_branch"].strip(),
        "completion_marker_path": marker,
        "allowed_path_prefixes": list(roots),
        "repository_intelligence_prefixes": [
            item.strip().rstrip("/") for item in intelligence
        ],
        "graduation_criteria": [" ".join(item.split()) for item in payload["graduation_criteria"]],
        "min_tasks": min_tasks,
        "max_tasks": max_tasks,
    }


def _completion_goal_fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _target_reader(spec: dict[str, Any]) -> GitHubClient:
    token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "").strip()
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
    return GitHubClient(repository=spec["target_repository"], token=token)


def _marker_is_complete(
    reader: GitHubClient,
    spec: dict[str, Any],
    *,
    target_head_sha: str,
) -> bool:
    try:
        text, _ = reader.get_text_file(
            spec["target_repository"],
            path=spec["completion_marker_path"],
            ref=target_head_sha,
            max_bytes=32768,
        )
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return False
        raise

    try:
        marker = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("completion marker must be valid JSON") from exc
    if not isinstance(marker, dict):
        raise ValueError("completion marker must contain a JSON object")
    return marker.get("schema_version") == 1 and marker.get("status") == "COMPLETE"


def _eligible_for_successor(
    request: PlanningGoalRequest,
    state: dict[str, Any],
    status: dict[str, Any] | None,
) -> bool:
    if status is None:
        return False
    if status.get("request_fingerprint") != request.fingerprint():
        return False
    if status.get("state") != "ACCEPTED":
        return False
    if state.get("current_task_id") is not None:
        return False
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return metadata.get("queue_exhausted") is True


def _build_successor_request(
    spec: dict[str, Any],
    state: dict[str, Any],
    *,
    target_head_sha: str,
) -> PlanningGoalRequest:
    iteration = state.get("iteration", 0)
    if type(iteration) is not int or iteration < 0:
        iteration = 0
    generation = iteration + 1
    spec_fingerprint = _completion_goal_fingerprint(spec)
    digest = hashlib.sha256(
        f"{spec_fingerprint}:{target_head_sha}:{generation}".encode("utf-8")
    ).hexdigest()[:10]
    prefix = spec["request_prefix"]

    criteria = " ".join(
        f"[{index}] {criterion}"
        for index, criterion in enumerate(spec["graduation_criteria"], 1)
    )
    marker = spec["completion_marker_path"]
    goal = (
        f"{spec['goal']} Continue autonomously from the current repository state and do not stop "
        f"at an intermediate milestone while safe executable work remains. Graduation criteria: {criteria} "
        f"Keep CI, validation, provenance, quota limits, and existing human-only safety boundaries intact. "
        f"Only when every graduation criterion is demonstrably satisfied and final repository/runtime checks "
        f"are green, create or update {marker} as JSON with schema_version=1 and status=COMPLETE plus concise "
        f"evidence fields. If the marker does not yet qualify, choose the highest-value bounded work that moves "
        f"the project toward graduation. When creating a not-yet-existing file, declare its exact path in new_paths."
    )

    return PlanningGoalRequest(
        request_id=f"{prefix}-request-{generation}-{digest}",
        campaign_id=f"{prefix}-campaign-{generation}-{digest}",
        id_prefix=f"{prefix}{generation}",
        goal=goal,
        target_repository=spec["target_repository"],
        base_branch=spec["base_branch"],
        allowed_path_prefixes=tuple(spec["allowed_path_prefixes"]),
        repository_intelligence_prefixes=tuple(
            spec["repository_intelligence_prefixes"]
        ),
        execution_phase="completion-runner",
        min_tasks=spec["min_tasks"],
        max_tasks=spec["max_tasks"],
    )


def main() -> int:
    if not COMPLETION_GOAL_PATH.exists():
        return planner_cycle.main()

    spec = _validate_completion_goal(_load(COMPLETION_GOAL_PATH))
    request = PlanningGoalRequest.from_dict(_load(PLANNING_GOAL_PATH))
    state = _load(STATE_PATH)
    status = _optional(PLANNING_STATUS_PATH)

    reader = _target_reader(spec)
    target_head_sha = reader.get_branch_head_sha(
        spec["target_repository"],
        branch=spec["base_branch"],
    )

    if _marker_is_complete(reader, spec, target_head_sha=target_head_sha):
        payload = {
            "schema_version": 1,
            "state": "COMPLETE",
            "reason": "completion-marker-verified",
            "project_key": spec["project_key"],
            "target_repository": spec["target_repository"],
            "target_head_sha": target_head_sha,
            "completion_marker_path": spec["completion_marker_path"],
            "completion_goal_fingerprint": _completion_goal_fingerprint(spec),
        }
        _write_result(payload)
        GitHubClient().upsert_json_file(
            REMOTE_COMPLETION_STATUS_PATH,
            payload,
            message=f"completion: {spec['project_key']} graduated",
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if not _eligible_for_successor(request, state, status):
        return planner_cycle.main()

    successor = _build_successor_request(
        spec,
        state,
        target_head_sha=target_head_sha,
    )
    PLANNING_GOAL_PATH.write_text(
        json.dumps(successor.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    controller = GitHubClient()
    controller.upsert_json_file(
        ".autodev/planning-goal.json",
        successor.to_dict(),
        message=f"completion: continue {spec['project_key']} toward graduation",
    )
    controller.upsert_json_file(
        REMOTE_COMPLETION_STATUS_PATH,
        {
            "schema_version": 1,
            "state": "CONTINUING",
            "reason": "previous-campaign-exhausted-before-graduation",
            "project_key": spec["project_key"],
            "target_repository": spec["target_repository"],
            "target_head_sha": target_head_sha,
            "completion_marker_path": spec["completion_marker_path"],
            "completion_goal_fingerprint": _completion_goal_fingerprint(spec),
            "successor_request_id": successor.request_id,
            "successor_campaign_id": successor.campaign_id,
        },
        message=f"completion: arm successor for {spec['project_key']}",
    )
    return planner_cycle.main()


if __name__ == "__main__":
    raise SystemExit(main())
