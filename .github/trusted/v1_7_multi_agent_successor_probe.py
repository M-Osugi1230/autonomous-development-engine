from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(".github/trusted/v1_7_multi_agent_successor.py")
spec = importlib.util.spec_from_file_location(
    "v1_7_multi_agent_successor_probe_module",
    SCRIPT,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _state() -> dict:
    return {
        "schema_version": 1,
        "project_id": "autonomous-development-engine",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": ["abgproof-777c97294d-001"],
        "failed_task_ids": [],
        "metadata": {
            "phase": "v1.6-autonomous-backlog",
            "milestone": "v1.6-graduated",
            "v1_6_graduated": True,
            "v1_6_graduation_evidence": (
                ".autodev/campaign-evidence/"
                "v1.6-autonomous-backlog-proof-001.json"
            ),
            "v1_6_post_retirement_queue_empty": True,
            "v1_6_proof_target_final_sha": "a" * 40,
        },
    }


def main() -> int:
    state = _state()
    activation = module.build_activation(state_payload=state)
    goal = activation["planning_goal"]

    assert activation["phase"] == "v1.7-multi-agent"
    assert goal["request_id"] == "v1.7-multi-agent-proof-001"
    assert goal["campaign_id"] == "v1.7-multi-agent-campaign-001"
    assert goal["allowed_path_prefixes"] == ["tests"]
    assert goal.get("min_tasks", 1) == 1
    assert goal["max_tasks"] == 1
    assert activation["reviewer_required"] is True
    assert activation["independent_reviewer_session_required"] is True
    assert activation["target_merge_gate_authority"] is True
    assert activation["execution_authority"] is False
    assert activation["accepted_plan_authority"] is False
    assert activation["merge_authority"] is False
    assert activation["auto_dispatch"] is False
    assert activation["may_expand_scope"] is False
    assert len(activation["activation_fingerprint"]) == 64

    blocked = 0
    for mutate in (
        lambda payload: payload["metadata"].__setitem__("v1_6_graduated", False),
        lambda payload: payload.__setitem__("current_task_id", "still-running"),
        lambda payload: payload.__setitem__("failed_task_ids", ["failed-task"]),
        lambda payload: payload["metadata"].__setitem__(
            "v1_6_post_retirement_queue_empty",
            False,
        ),
    ):
        candidate = _state()
        mutate(candidate)
        try:
            module.build_activation(state_payload=candidate)
        except ValueError:
            blocked += 1
    assert blocked == 4

    print(
        json.dumps(
            {
                "ok": True,
                "requires_v1_6_graduation": True,
                "requires_ready_idle_state": True,
                "requires_empty_post_retirement_queue": True,
                "tests_only_planning_goal": True,
                "single_task_budget": True,
                "independent_reviewer_required": True,
                "target_gate_retains_merge_authority": True,
                "execution_authority": False,
                "accepted_plan_authority": False,
                "merge_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
