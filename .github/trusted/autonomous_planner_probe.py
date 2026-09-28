from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_planner import (
    PlannerDisposition,
    PlannerPolicy,
    PlannerValidationError,
    accept_validated_proposal,
    validate_planner_proposal,
)
from ade.plan_compiler import compile_plan


GOAL = "Add a deterministic planner proof helper and focused tests."
BOUNDARIES = [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
]


def payload() -> dict:
    return {
        "schema_version": 1,
        "goal": GOAL,
        "tasks": [
            {
                "key": "helper",
                "title": "Add planner proof helper",
                "outcome": "Add a pure planner proof helper.",
                "depends_on": [],
                "allowed_paths": ["src/ade/planner_proof.py"],
                "acceptance": ["helper is deterministic"],
                "human_only": False,
                "human_reason": None,
            },
            {
                "key": "tests",
                "title": "Test planner proof helper",
                "outcome": "Add focused stdlib tests.",
                "depends_on": ["helper"],
                "allowed_paths": ["tests/test_planner_proof.py"],
                "acceptance": ["focused tests pass"],
                "human_only": False,
                "human_reason": None,
            },
        ],
        "human_boundaries": BOUNDARIES,
    }


def main() -> int:
    policy = PlannerPolicy(allowed_path_prefixes=("src/ade", "tests"))
    validated = validate_planner_proposal(
        high_level_goal=GOAL,
        proposal_payload=payload(),
        policy=policy,
        id_prefix="probe",
    )
    assert validated.disposition is PlannerDisposition.ACCEPTED
    accepted = accept_validated_proposal(validated)
    campaign, graph = compile_plan(accepted.plan, campaign_id="planner-proof")
    assert campaign.task_ids == ("probe-001", "probe-002")
    assert graph.tasks[1].depends_on == ("probe-001",)

    bad_scope = payload()
    bad_scope["tasks"][0]["allowed_paths"] = [".github/workflows/ci.yml"]
    try:
        validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=bad_scope,
            policy=PlannerPolicy(allowed_path_prefixes=(".github", "src/ade", "tests")),
        )
    except PlannerValidationError:
        pass
    else:
        raise AssertionError("protected scope was accepted")

    forward = payload()
    forward["tasks"][0]["depends_on"] = ["tests"]
    try:
        validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=forward,
            policy=policy,
        )
    except PlannerValidationError:
        pass
    else:
        raise AssertionError("forward dependency was accepted")

    human = payload()
    human["tasks"][0]["human_only"] = True
    human["tasks"][0]["human_reason"] = "destructive approval"
    human_result = validate_planner_proposal(
        high_level_goal=GOAL,
        proposal_payload=human,
        policy=policy,
    )
    assert human_result.disposition is PlannerDisposition.HUMAN_WAIT
    assert human_result.plan is None

    stable = validate_planner_proposal(
        high_level_goal="  " + GOAL + " ",
        proposal_payload=copy.deepcopy(payload()),
        policy=policy,
        id_prefix="probe",
    )
    assert accepted.fingerprint == accept_validated_proposal(stable).fingerprint

    print(json.dumps({
        "ok": True,
        "goal_only_boundary": True,
        "untrusted_proposal_validated": True,
        "trusted_ids_and_prompts": True,
        "scope_rejection": True,
        "dependency_rejection": True,
        "human_wait": True,
        "stable_fingerprint": True,
        "existing_campaign_compile": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
