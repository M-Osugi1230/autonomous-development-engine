from __future__ import annotations

import copy
import unittest

from ade.autonomous_planner import PlannerDisposition, PlannerPolicy, PlannerValidationError
from ade.planner_path_grounding import (
    ground_derived_plan_new_paths,
    plan_high_level_goal_with_path_grounding,
)


GOAL = "Add a focused implementation helper and prove it with a new test file."
BOUNDARIES = [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
]


def proposal() -> dict:
    return {
        "schema_version": 1,
        "goal": GOAL,
        "tasks": [
            {
                "key": "implementation",
                "title": "Update implementation helper",
                "outcome": "Update the existing helper implementation.",
                "depends_on": [],
                "allowed_paths": ["src/ade/existing_helper.py"],
                "acceptance": ["implementation remains deterministic"],
                "new_paths": [],
                "human_only": False,
                "human_reason": None,
            },
            {
                "key": "tests",
                "title": "Add focused test coverage",
                "outcome": "Add a focused test for the helper behavior.",
                "depends_on": ["implementation"],
                "allowed_paths": ["tests/test_new_helper.py"],
                "acceptance": ["focused test passes"],
                "new_paths": [],
                "human_only": False,
                "human_reason": None,
            },
        ],
        "human_boundaries": list(BOUNDARIES),
    }


def policy() -> PlannerPolicy:
    return PlannerPolicy(allowed_path_prefixes=("src/ade", "tests"))


class _Provider:
    def __init__(self, payload: dict, *, mode: str) -> None:
        self.payload = payload
        self.last_proposal_mode = mode
        self.prompts: list[str] = []

    def propose(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        return copy.deepcopy(self.payload)


class PlannerPathGroundingTests(unittest.TestCase):
    def test_grounding_marks_only_snapshot_missing_allowed_paths_new(self) -> None:
        grounded = ground_derived_plan_new_paths(
            proposal(),
            existing_paths={"src/ade/existing_helper.py"},
        )
        self.assertEqual(grounded["tasks"][0]["new_paths"], [])
        self.assertEqual(
            grounded["tasks"][1]["new_paths"],
            ["tests/test_new_helper.py"],
        )
        self.assertEqual(
            grounded["tasks"][1]["allowed_paths"],
            ["tests/test_new_helper.py"],
        )

    def test_derived_plan_steps_are_grounded_before_strict_validation(self) -> None:
        provider = _Provider(proposal(), mode="derived-plan-steps")
        result = plan_high_level_goal_with_path_grounding(
            provider,
            high_level_goal=GOAL,
            policy=policy(),
            id_prefix="grounded",
            existing_paths={"src/ade/existing_helper.py"},
        )
        self.assertEqual(result.validated.disposition, PlannerDisposition.ACCEPTED)
        self.assertIsNotNone(result.accepted_plan)
        self.assertEqual(
            result.raw_proposal["tasks"][1]["new_paths"],
            ["tests/test_new_helper.py"],
        )

    def test_structured_provider_proposal_keeps_explicit_new_path_contract(self) -> None:
        provider = _Provider(proposal(), mode="structured")
        with self.assertRaisesRegex(
            PlannerValidationError,
            "does not exist in repository snapshot and is not declared new",
        ):
            plan_high_level_goal_with_path_grounding(
                provider,
                high_level_goal=GOAL,
                policy=policy(),
                id_prefix="strict",
                existing_paths={"src/ade/existing_helper.py"},
            )

    def test_grounding_removes_false_new_declaration_for_existing_path(self) -> None:
        payload = proposal()
        payload["tasks"][0]["new_paths"] = ["src/ade/existing_helper.py"]
        provider = _Provider(payload, mode="derived-plan-steps")
        result = plan_high_level_goal_with_path_grounding(
            provider,
            high_level_goal=GOAL,
            policy=policy(),
            id_prefix="grounded",
            existing_paths={"src/ade/existing_helper.py"},
        )
        self.assertEqual(result.validated.disposition, PlannerDisposition.ACCEPTED)
        self.assertEqual(result.raw_proposal["tasks"][0]["new_paths"], [])


if __name__ == "__main__":
    unittest.main()
