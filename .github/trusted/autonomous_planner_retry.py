from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ade.planning_activation import PlanningGoalRequest
from github_client import GitHubClient, GitHubError

GOAL_PATH = ".autodev/planning-goal.json"
STATUS_PATH = ".autodev/runtime/planning-status.json"


def _event_payload() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow event must be a JSON object")
    client_payload = payload.get("client_payload")
    if not isinstance(client_payload, dict):
        raise ValueError("repository_dispatch client_payload is required")
    return client_payload


def retry_decision(
    *,
    event_payload: dict[str, Any],
    goal_payload: dict[str, Any],
    status_payload: dict[str, Any],
) -> tuple[bool, str]:
    if not isinstance(event_payload, dict):
        raise ValueError("event_payload must be an object")
    if not isinstance(goal_payload, dict):
        raise ValueError("goal_payload must be an object")
    if not isinstance(status_payload, dict):
        raise ValueError("status_payload must be an object")

    request = PlanningGoalRequest.from_dict(goal_payload)
    event_request_id = event_payload.get("request_id")
    event_fingerprint = event_payload.get("request_fingerprint")

    if event_request_id != request.request_id:
        return False, "goal-request-changed"
    if event_fingerprint != request.fingerprint():
        return False, "goal-fingerprint-changed"

    if status_payload.get("request_id") != request.request_id:
        return False, "status-request-changed"
    if status_payload.get("request_fingerprint") != request.fingerprint():
        return False, "status-fingerprint-changed"
    if status_payload.get("state") != "PAUSED_QUOTA":
        return False, "planner-not-paused"
    if status_payload.get("reason") != "planner-provider-capacity":
        return False, "pause-reason-not-capacity"

    return True, "planner-provider-capacity-still-active"


def main() -> int:
    try:
        gh = GitHubClient()
        event_payload = _event_payload()
        goal_payload, _ = gh.get_json_file(GOAL_PATH)
        status_payload, _ = gh.get_json_file(STATUS_PATH)
        should_retry, reason = retry_decision(
            event_payload=event_payload,
            goal_payload=goal_payload,
            status_payload=status_payload,
        )
        if not should_retry:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": reason,
                "request_id": event_payload.get("request_id"),
            }
            print(json.dumps(result, sort_keys=True))
            return 0

        request = PlanningGoalRequest.from_dict(goal_payload)
        gh.dispatch(
            "ade_planner_retry",
            {
                "request_id": request.request_id,
                "request_fingerprint": request.fingerprint(),
                "source": "planner-capacity-retry-watchdog",
            },
        )
        result = {
            "schema_version": 1,
            "state": "DISPATCHED",
            "reason": reason,
            "request_id": request.request_id,
            "request_fingerprint": request.fingerprint(),
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "state": "FAILED",
                    "error": str(exc).splitlines()[0][:256],
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
