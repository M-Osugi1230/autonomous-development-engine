from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from autonomous_planner_retry import retry_decision
from ade.planning_activation import PlanningGoalRequest


def _goal() -> dict:
    return {
        "schema_version": 1,
        "request_id": "proof-retry",
        "campaign_id": "proof-retry-campaign",
        "id_prefix": "pr",
        "goal": "Add a deterministic helper and focused tests.",
        "target_repository": "example/target",
        "base_branch": "main",
        "allowed_path_prefixes": ["src", "tests"],
        "min_tasks": 2,
        "max_tasks": 2,
    }


def _status(goal: dict) -> dict:
    request = PlanningGoalRequest.from_dict(goal)
    return {
        "schema_version": 1,
        "request_id": request.request_id,
        "request_fingerprint": request.fingerprint(),
        "state": "PAUSED_QUOTA",
        "attempt": 0,
        "reason": "planner-provider-capacity",
    }


def main() -> int:
    goal = _goal()
    request = PlanningGoalRequest.from_dict(goal)
    event = {
        "request_id": request.request_id,
        "request_fingerprint": request.fingerprint(),
    }
    status = _status(goal)

    assert retry_decision(
        event_payload=event,
        goal_payload=goal,
        status_payload=status,
    ) == (True, "planner-provider-capacity-still-active")

    accepted = dict(status)
    accepted["state"] = "ACCEPTED"
    assert retry_decision(
        event_payload=event,
        goal_payload=goal,
        status_payload=accepted,
    ) == (False, "planner-not-paused")

    changed_goal = dict(goal)
    changed_goal["request_id"] = "different-request"
    assert retry_decision(
        event_payload=event,
        goal_payload=changed_goal,
        status_payload=status,
    ) == (False, "goal-request-changed")

    changed_status = dict(status)
    changed_status["reason"] = "planner-retryable-failure"
    assert retry_decision(
        event_payload=event,
        goal_payload=goal,
        status_payload=changed_status,
    ) == (False, "pause-reason-not-capacity")

    print(json.dumps({
        "ok": True,
        "capacity_pause_retries": True,
        "accepted_state_noops": True,
        "stale_goal_noops": True,
        "non_capacity_pause_noops": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
