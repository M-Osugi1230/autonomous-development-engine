from __future__ import annotations

import json

from ade.autonomous_planner import plan_high_level_goal
from ade.deterministic_planner import (
    DeterministicPlanningProvider,
    build_deterministic_proposal,
)
from ade.planning_activation import PlanningGoalRequest


def run_probe() -> dict[str, object]:
    request = PlanningGoalRequest(
        request_id="deterministic-probe",
        campaign_id="deterministic-probe-campaign",
        id_prefix="detprobe",
        goal=(
            "Advance Phase 15 by creating "
            "data/candidates/akita-city/review_candidate.json and deterministic "
            "candidate regression coverage under tests/."
        ),
        target_repository="M-Osugi1230/jichi-insight",
        base_branch="main",
        allowed_path_prefixes=("data/candidates", "tests"),
        min_tasks=1,
        max_tasks=2,
    )
    proposal = build_deterministic_proposal(
        request,
        existing_paths=frozenset(),
    )
    if proposal is None:
        raise AssertionError("Jichi deterministic recipe did not match")
    result = plan_high_level_goal(
        DeterministicPlanningProvider(proposal),
        high_level_goal=request.goal,
        policy=request.planner_policy(),
        id_prefix=request.id_prefix,
        existing_paths=frozenset(),
    )
    if result.accepted_plan is None:
        raise AssertionError("deterministic proposal did not produce AcceptedPlan")
    if len(result.accepted_plan.plan.tasks) != 1:
        raise AssertionError("Jichi recipe did not coalesce work into one task")
    return {
        "ok": True,
        "provider": "deterministic",
        "task_count": len(result.accepted_plan.plan.tasks),
        "jules_planner_tasks_consumed": 0,
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
