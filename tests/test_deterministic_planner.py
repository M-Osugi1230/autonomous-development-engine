from __future__ import annotations

import unittest

from ade.deterministic_planner import (
    DeterministicPlanningProvider,
    build_deterministic_proposal,
)
from ade.autonomous_planner import plan_high_level_goal
from ade.planning_activation import PlanningGoalRequest


class DeterministicPlannerRecipeTests(unittest.TestCase):
    def test_jichi_recipe_coalesces_candidate_and_test_into_one_task(self) -> None:
        request = PlanningGoalRequest(
            request_id="jichi-akita-test",
            campaign_id="jichi-akita-campaign",
            id_prefix="akita",
            goal=(
                "Advance Phase 15. Create "
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
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(len(proposal["tasks"]), 1)
        task = proposal["tasks"][0]
        self.assertEqual(
            task["allowed_paths"],
            [
                "data/candidates/akita-city/review_candidate.json",
                "tests/test_phase15_akita_review_candidate_staging.py",
            ],
        )
        self.assertEqual(task["new_paths"], task["allowed_paths"])

        result = plan_high_level_goal(
            DeterministicPlanningProvider(proposal),
            high_level_goal=request.goal,
            policy=request.planner_policy(),
            id_prefix=request.id_prefix,
            existing_paths=frozenset(),
        )
        self.assertIsNotNone(result.accepted_plan)
        assert result.accepted_plan is not None
        self.assertEqual(len(result.accepted_plan.plan.tasks), 1)

    def test_chu_kei_recipe_uses_minimum_task_count_and_skips_existing_batch(self) -> None:
        request = PlanningGoalRequest(
            request_id="chu-test",
            campaign_id="chu-campaign",
            id_prefix="chu",
            goal=(
                "Expand Chu-kei Plan Detection beginning with ade-batch-002 "
                "through bounded non-public candidate batches."
            ),
            target_repository="M-Osugi1230/chu-kei",
            base_branch="main",
            allowed_path_prefixes=("operations/plan-detection/candidates",),
            min_tasks=2,
            max_tasks=6,
        )
        existing = frozenset(
            {
                "operations/plan-detection/candidates/ade-batch-002/candidates-v1.json",
            }
        )
        proposal = build_deterministic_proposal(
            request,
            existing_paths=existing,
        )
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(len(proposal["tasks"]), 2)
        self.assertEqual(
            proposal["tasks"][0]["allowed_paths"],
            [
                "operations/plan-detection/candidates/ade-batch-003/candidates-v1.json"
            ],
        )
        self.assertEqual(
            proposal["tasks"][1]["allowed_paths"],
            [
                "operations/plan-detection/candidates/ade-batch-004/candidates-v1.json"
            ],
        )
        self.assertEqual(
            proposal["tasks"][1]["depends_on"],
            ["deterministic-step-001"],
        )

        result = plan_high_level_goal(
            DeterministicPlanningProvider(proposal),
            high_level_goal=request.goal,
            policy=request.planner_policy(),
            id_prefix=request.id_prefix,
            existing_paths=existing,
        )
        self.assertIsNotNone(result.accepted_plan)
        assert result.accepted_plan is not None
        self.assertEqual(len(result.accepted_plan.plan.tasks), 2)

    def test_unknown_repository_falls_back_to_external_planner(self) -> None:
        request = PlanningGoalRequest(
            request_id="unknown-test",
            campaign_id="unknown-campaign",
            id_prefix="unknown",
            goal="Change one file.",
            target_repository="M-Osugi1230/other",
            base_branch="main",
            allowed_path_prefixes=("src",),
            min_tasks=1,
            max_tasks=2,
        )
        self.assertIsNone(
            build_deterministic_proposal(
                request,
                existing_paths=frozenset({"src/app.py"}),
            )
        )


if __name__ == "__main__":
    unittest.main()
