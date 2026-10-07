from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / ".github" / "trusted" / "completion_planner_cycle.py"
SPEC = importlib.util.spec_from_file_location("completion_planner_cycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
completion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(completion)


class CompletionPlannerCycleTests(unittest.TestCase):
    def completion_goal(self):
        return {
            "schema_version": 1,
            "project_key": "example",
            "request_prefix": "example-finish",
            "goal": "Finish the example project.",
            "target_repository": "example/target",
            "base_branch": "main",
            "allowed_path_prefixes": ["src", "tests", "docs"],
            "repository_intelligence_prefixes": ["src", "tests", "docs"],
            "graduation_criteria": [
                "all required production behavior is implemented",
                "CI and runtime verification are green",
            ],
            "completion_marker_path": "docs/ADE_COMPLETION.json",
            "min_tasks": 1,
            "max_tasks": 4,
        }

    def planning_request(self):
        return completion.PlanningGoalRequest(
            request_id="old-request",
            campaign_id="old-campaign",
            id_prefix="old",
            goal="Old bounded goal.",
            target_repository="example/target",
            base_branch="main",
            allowed_path_prefixes=("src",),
        )

    def test_completion_goal_validation_requires_marker_inside_allowed_root(self):
        payload = self.completion_goal()
        payload["completion_marker_path"] = "private/ADE_COMPLETION.json"
        with self.assertRaisesRegex(ValueError, "completion marker"):
            completion._validate_completion_goal(payload)

    def test_successor_is_eligible_only_after_accepted_campaign_exhaustion(self):
        request = self.planning_request()
        status = {
            "state": "ACCEPTED",
            "request_fingerprint": request.fingerprint(),
        }
        state = {
            "iteration": 10,
            "current_task_id": None,
            "metadata": {"queue_exhausted": True},
        }
        self.assertTrue(completion._eligible_for_successor(request, state, status))

        running = {**state, "current_task_id": "task-1"}
        self.assertFalse(completion._eligible_for_successor(request, running, status))

        human_wait = {**status, "state": "HUMAN_WAIT"}
        self.assertFalse(completion._eligible_for_successor(request, state, human_wait))

    def test_successor_request_is_deterministic_and_carries_graduation_contract(self):
        spec = completion._validate_completion_goal(self.completion_goal())
        state = {
            "iteration": 10,
            "current_task_id": None,
            "metadata": {"queue_exhausted": True},
        }
        first = completion._build_successor_request(
            spec,
            state,
            target_head_sha="a" * 40,
        )
        second = completion._build_successor_request(
            spec,
            state,
            target_head_sha="a" * 40,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.execution_phase, "completion-runner")
        self.assertIn("docs/ADE_COMPLETION.json", first.goal)
        self.assertIn("do not stop at an intermediate milestone", first.goal)
        self.assertEqual(first.target_repository, "example/target")


if __name__ == "__main__":
    unittest.main()
