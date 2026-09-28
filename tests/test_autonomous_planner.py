from __future__ import annotations

import copy
import unittest

from ade.autonomous_planner import (
    PlannerDisposition,
    PlannerPolicy,
    PlannerValidationError,
    accept_validated_proposal,
    plan_high_level_goal,
    validate_planner_proposal,
)
from ade.plan_compiler import compile_plan


GOAL = "Add a small repository status helper and prove it with focused tests."
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
                "key": "model",
                "title": "Add repository status helper",
                "outcome": "Add a pure repository_status helper returning a deterministic summary.",
                "depends_on": [],
                "allowed_paths": ["src/ade/repository_status.py"],
                "acceptance": ["helper output is deterministic", "invalid input is rejected"],
                "human_only": False,
                "human_reason": None,
            },
            {
                "key": "tests",
                "title": "Prove repository status helper",
                "outcome": "Add focused stdlib tests for repository_status.",
                "depends_on": ["model"],
                "allowed_paths": ["tests/test_repository_status.py"],
                "acceptance": ["focused tests pass", "full repository tests remain green"],
                "human_only": False,
                "human_reason": None,
            },
        ],
        "human_boundaries": list(BOUNDARIES),
    }


def policy() -> PlannerPolicy:
    return PlannerPolicy(allowed_path_prefixes=("src/ade", "tests"))


class _Provider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def propose(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        return copy.deepcopy(self.payload)


class AutonomousPlannerTests(unittest.TestCase):
    def test_goal_only_provider_proposal_becomes_accepted_plan(self) -> None:
        provider = _Provider(proposal())
        result = plan_high_level_goal(
            provider,
            high_level_goal=GOAL,
            policy=policy(),
            id_prefix="v12",
        )
        self.assertEqual(result.validated.disposition, PlannerDisposition.ACCEPTED)
        self.assertIsNotNone(result.accepted_plan)
        assert result.accepted_plan is not None
        self.assertEqual(
            [task.task_id for task in result.accepted_plan.plan.tasks],
            ["v12-001", "v12-002"],
        )
        self.assertEqual(result.accepted_plan.plan.tasks[1].depends_on, ("v12-001",))
        self.assertIn("untrusted planning component", provider.prompts[0])
        self.assertIn("concrete repository files", provider.prompts[0])
        self.assertNotIn("v12-001", proposal()["tasks"][0]["key"])

    def test_validated_plan_compiles_into_existing_campaign_path(self) -> None:
        validated = validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=proposal(),
            policy=policy(),
            id_prefix="v12",
        )
        accepted = accept_validated_proposal(validated)
        campaign, graph = compile_plan(accepted.plan, campaign_id="v1.2-proof")
        self.assertEqual(campaign.task_ids, ("v12-001", "v12-002"))
        self.assertEqual(graph.tasks[1].depends_on, ("v12-001",))

    def test_identical_normalized_inputs_have_stable_fingerprint(self) -> None:
        first = validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=proposal(),
            policy=policy(),
            id_prefix="v12",
        )
        second_payload = proposal()
        second_payload["goal"] = "  Add a small repository status helper   and prove it with focused tests. "
        second = validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=second_payload,
            policy=policy(),
            id_prefix="v12",
        )
        self.assertEqual(first.plan.fingerprint(), second.plan.fingerprint())  # type: ignore[union-attr]
        self.assertEqual(
            accept_validated_proposal(first).fingerprint,
            accept_validated_proposal(second).fingerprint,
        )

    def test_unknown_schema_fields_are_rejected(self) -> None:
        payload = proposal()
        payload["execute_now"] = True
        with self.assertRaisesRegex(PlannerValidationError, "unknown planner proposal"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_goal_drift_is_rejected(self) -> None:
        payload = proposal()
        payload["goal"] = "Different goal"
        with self.assertRaisesRegex(PlannerValidationError, "does not match"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_scope_and_protected_paths_are_rejected(self) -> None:
        outside = proposal()
        outside["tasks"][0]["allowed_paths"] = ["README.md"]
        with self.assertRaisesRegex(PlannerValidationError, "outside trusted roots"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=outside,
                policy=policy(),
            )

        protected = proposal()
        protected["tasks"][0]["allowed_paths"] = [".github/workflows/ci.yml"]
        broad_policy = PlannerPolicy(allowed_path_prefixes=(".github", "src/ade", "tests"))
        with self.assertRaisesRegex(PlannerValidationError, "protected planner path"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=protected,
                policy=broad_policy,
            )

    def test_dependency_and_duplicate_key_rejection(self) -> None:
        forward = proposal()
        forward["tasks"][0]["depends_on"] = ["tests"]
        with self.assertRaisesRegex(PlannerValidationError, "forward or cyclic"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=forward,
                policy=policy(),
            )

        duplicate = proposal()
        duplicate["tasks"][1]["key"] = "model"
        with self.assertRaisesRegex(PlannerValidationError, "duplicate planner task key"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=duplicate,
                policy=policy(),
            )

    def test_minimum_task_budget_is_enforced(self) -> None:
        payload = proposal()
        payload["tasks"] = payload["tasks"][:1]
        with self.assertRaisesRegex(PlannerValidationError, "task-count budget"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=PlannerPolicy(
                    allowed_path_prefixes=("src/ade", "tests"),
                    min_tasks=2,
                ),
            )

    def test_trusted_root_directory_is_not_an_executable_scope(self) -> None:
        payload = proposal()
        payload["tasks"][0]["allowed_paths"] = ["src/ade"]
        with self.assertRaisesRegex(PlannerValidationError, "concrete file"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_planner_protocol_meta_task_is_rejected(self) -> None:
        payload = proposal()
        payload["tasks"][0]["title"] = "Formulate the JSON proposal"
        payload["tasks"][0]["outcome"] = (
            "Define tasks matching schema_version and allowed_paths."
        )
        with self.assertRaisesRegex(PlannerValidationError, "planner protocol"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_budgets_are_enforced(self) -> None:
        payload = proposal()
        payload["tasks"][0]["allowed_paths"] = [
            "src/ade/a.py",
            "src/ade/b.py",
        ]
        tight = PlannerPolicy(
            allowed_path_prefixes=("src/ade", "tests"),
            max_paths_per_task=1,
        )
        with self.assertRaisesRegex(PlannerValidationError, "path budget"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=tight,
            )

    def test_mandatory_human_boundaries_are_required(self) -> None:
        payload = proposal()
        payload["human_boundaries"] = BOUNDARIES[:-1]
        with self.assertRaisesRegex(PlannerValidationError, "missing mandatory human boundaries"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_secret_like_planner_text_is_rejected(self) -> None:
        payload = proposal()
        payload["tasks"][0]["outcome"] = "Use bearer abcdefghijklmnopqrstuvwxyz0123456789-secret"
        with self.assertRaisesRegex(PlannerValidationError, "secret pattern"):
            validate_planner_proposal(
                high_level_goal=GOAL,
                proposal_payload=payload,
                policy=policy(),
            )

    def test_human_only_proposal_cannot_be_accepted(self) -> None:
        payload = proposal()
        payload["tasks"][0]["human_only"] = True
        payload["tasks"][0]["human_reason"] = "Requires destructive migration approval"
        validated = validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=payload,
            policy=policy(),
        )
        self.assertEqual(validated.disposition, PlannerDisposition.HUMAN_WAIT)
        self.assertIsNone(validated.plan)
        with self.assertRaisesRegex(PlannerValidationError, "only an ACCEPTED"):
            accept_validated_proposal(validated)

    def test_sensitive_action_marker_forces_human_wait(self) -> None:
        payload = proposal()
        payload["tasks"][0]["outcome"] = "Deploy to production after changing the helper."
        validated = validate_planner_proposal(
            high_level_goal=GOAL,
            proposal_payload=payload,
            policy=policy(),
        )
        self.assertEqual(validated.disposition, PlannerDisposition.HUMAN_WAIT)


if __name__ == "__main__":
    unittest.main()
