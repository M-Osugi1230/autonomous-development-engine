from __future__ import annotations

import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
)
from ade.autonomous_backlog_goal import (
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def candidate(*, human_only: bool = False) -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id="backlog-followup",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=SHA,
        statement="Trusted evidence identifies a bounded test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("b" * 64,),
        tags=("repair",),
        human_only=human_only,
    )


def policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=REPO,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        min_tasks=1,
        max_tasks=2,
    )


def chain(value: BacklogCandidate):
    backlog = AutonomousBacklog(candidates=(value,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=REPO,
        source_sha=SHA,
    )
    return backlog, resolution, selection


class AutonomousBacklogGoalTests(unittest.TestCase):
    def test_handoff_builds_only_high_level_planning_request(self) -> None:
        backlog, resolution, selection = chain(candidate())
        handoff = build_planning_goal_handoff(
            backlog,
            resolution,
            selection,
            policy=policy(),
        )
        request = handoff.request
        self.assertEqual(request.target_repository, REPO)
        self.assertEqual(request.allowed_path_prefixes, ("tests",))
        self.assertEqual(request.min_tasks, 1)
        self.assertEqual(request.max_tasks, 2)
        self.assertIn("Resolve trusted Autonomous Backlog candidate", request.goal)
        payload = handoff.canonical_dict()
        self.assertEqual(payload["handoff_target"], "AutonomousPlanner")
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["accepted_plan_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertNotIn("tasks", payload["planning_goal_request"])

    def test_scope_comes_from_trusted_policy_not_candidate(self) -> None:
        backlog, resolution, selection = chain(candidate())
        first = build_planning_goal_handoff(
            backlog,
            resolution,
            selection,
            policy=policy(),
        )
        second_policy = BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("src", "tests"),
            max_tasks=3,
        )
        second = build_planning_goal_handoff(
            backlog,
            resolution,
            selection,
            policy=second_policy,
        )
        self.assertEqual(first.request.allowed_path_prefixes, ("tests",))
        self.assertEqual(second.request.allowed_path_prefixes, ("src", "tests"))
        self.assertNotEqual(first.policy_fingerprint, second.policy_fingerprint)

    def test_protected_scope_is_rejected_by_policy(self) -> None:
        for root in (".github", ".autodev", ".env", "secrets", "credentials"):
            with self.subTest(root=root):
                with self.assertRaisesRegex(AutonomousBacklogError, "unsafe"):
                    BacklogPlanningPolicy(
                        repository=REPO,
                        base_branch="main",
                        allowed_path_prefixes=(root,),
                    )

    def test_human_only_or_empty_selection_cannot_handoff(self) -> None:
        backlog, resolution, selection = chain(candidate(human_only=True))
        self.assertIsNone(selection.selected_candidate_id)
        with self.assertRaisesRegex(AutonomousBacklogError, "no eligible"):
            build_planning_goal_handoff(
                backlog,
                resolution,
                selection,
                policy=policy(),
            )

    def test_handoff_is_deterministic(self) -> None:
        backlog, resolution, selection = chain(candidate())
        left = build_planning_goal_handoff(
            backlog,
            resolution,
            selection,
            policy=policy(),
        )
        right = build_planning_goal_handoff(
            backlog,
            resolution,
            selection,
            policy=policy(),
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())
        self.assertEqual(left.request.fingerprint(), right.request.fingerprint())


if __name__ == "__main__":
    unittest.main()
