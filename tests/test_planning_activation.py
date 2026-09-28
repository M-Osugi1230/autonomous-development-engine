from __future__ import annotations

import unittest

from ade.autonomous_planner import PlannerPolicy, validate_planner_proposal
from ade.models import ProjectState, ProjectStatus
from ade.planning_activation import PlanningGoalRequest, build_planning_activation


BOUNDARIES = [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
]


class PlanningActivationTests(unittest.TestCase):
    def request(self):
        return PlanningGoalRequest(
            request_id="v12-proof-001",
            campaign_id="v12-campaign-001",
            id_prefix="v12p",
            goal="Add a small target helper and focused tests.",
            target_repository="example/target",
            base_branch="main",
            allowed_path_prefixes=("src", "tests"),
        )

    def validated(self):
        request = self.request()
        payload = {
            "schema_version": 1,
            "goal": request.goal,
            "tasks": [
                {
                    "key": "helper",
                    "title": "Add target helper",
                    "outcome": "Add a pure target helper.",
                    "depends_on": [],
                    "allowed_paths": ["src/helper.py"],
                    "acceptance": ["helper is deterministic"],
                    "human_only": False,
                    "human_reason": None,
                },
                {
                    "key": "tests",
                    "title": "Prove target helper",
                    "outcome": "Add focused tests.",
                    "depends_on": ["helper"],
                    "allowed_paths": ["tests/test_helper.py"],
                    "acceptance": ["focused tests pass"],
                    "human_only": False,
                    "human_reason": None,
                },
            ],
            "human_boundaries": BOUNDARIES,
        }
        return validate_planner_proposal(
            high_level_goal=request.goal,
            proposal_payload=payload,
            policy=request.planner_policy(),
            id_prefix=request.id_prefix,
        )

    def previous_state(self):
        return ProjectState(
            schema_version=1,
            project_id="ade",
            status=ProjectStatus.READY,
            iteration=52,
            current_task_id=None,
            completed_task_ids=["old-1"],
            failed_task_ids=[],
            provider="jules",
            updated_at="2026-09-28T00:00:00+00:00",
            metadata={"old": "kept"},
        )

    def test_request_round_trip_and_fingerprint_are_stable(self):
        request = self.request()
        loaded = PlanningGoalRequest.from_dict(request.to_dict())
        self.assertEqual(loaded, request)
        self.assertEqual(loaded.fingerprint(), request.fingerprint())

    def test_activation_builds_running_first_task_and_target_metadata(self):
        request = self.request()
        bundle = build_planning_activation(
            request=request,
            validated=self.validated(),
            previous_state=self.previous_state(),
        )
        self.assertEqual(bundle.campaign.status.value, "RUNNING")
        self.assertEqual(bundle.graph.tasks[0].status.value, "RUNNING")
        self.assertEqual(bundle.graph.tasks[1].status.value, "PENDING")
        self.assertEqual(bundle.cycle_task.task_id, "v12p-001")
        self.assertEqual(bundle.cycle_task.starting_branch, "main")
        self.assertEqual(bundle.state.current_task_id, "v12p-001")
        self.assertEqual(bundle.state.status.value, "READY")
        self.assertEqual(bundle.state.metadata["target_repository"], "example/target")
        self.assertEqual(bundle.state.metadata["old"], "kept")
        self.assertEqual(
            bundle.state.metadata["accepted_plan_fingerprint"],
            bundle.accepted_plan.fingerprint,
        )

    def test_activation_refuses_existing_current_task(self):
        state = self.previous_state()
        state.current_task_id = "busy"
        with self.assertRaisesRegex(ValueError, "another task"):
            build_planning_activation(
                request=self.request(),
                validated=self.validated(),
                previous_state=state,
            )

    def test_request_rejects_unsafe_scope(self):
        with self.assertRaisesRegex(ValueError, "unsafe allowed path"):
            PlanningGoalRequest(
                request_id="r1",
                campaign_id="c1",
                id_prefix="p1",
                goal="g",
                target_repository="example/target",
                base_branch="main",
                allowed_path_prefixes=("../secrets",),
            )


if __name__ == "__main__":
    unittest.main()
