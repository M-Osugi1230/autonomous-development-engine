from __future__ import annotations

import unittest

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_reconciliation import reconcile_agent_contributions
from ade.multi_agent_review_gate import (
    MultiAgentReviewGateError,
    ReviewClearance,
    build_review_clearance,
)
from ade.multi_agent_session import (
    complete_role_session,
    role_session_for_assignment,
    start_role_session,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def accepted_plan() -> AcceptedPlan:
    plan = DevelopmentPlan(
        goal="Add one bounded regression test.",
        tasks=(
            PlannedTask(
                task_id="task-001",
                title="Add bounded regression test",
                prompt="Add only the accepted bounded regression test.",
                depends_on=(),
                allowed_paths=("tests/test_models.py",),
                acceptance=("Repository CI remains green",),
            ),
        ),
    )
    return AcceptedPlan.accept(plan)


def multi_agent_plan() -> MultiAgentPlan:
    accepted = accepted_plan()
    common = dict(
        repository=REPO,
        source_sha=SOURCE_SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted.fingerprint,
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )
    return MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=REPO,
        source_sha=SOURCE_SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted.fingerprint,
        assignments=(
            AgentAssignment(
                assignment_id="implementer",
                role=AgentRole.IMPLEMENTER,
                provider_id="jules",
                objective="Implement frozen AcceptedPlan scope.",
                **common,
            ),
            AgentAssignment(
                assignment_id="reviewer",
                role=AgentRole.REVIEWER,
                provider_id="jules",
                objective="Review frozen AcceptedPlan scope.",
                **common,
            ),
        ),
    )


def completed_reviewer_session(plan: MultiAgentPlan):
    reviewer = next(
        item for item in plan.assignments if item.role is AgentRole.REVIEWER
    )
    ready = role_session_for_assignment(plan, reviewer)
    running = start_role_session(
        ready,
        provider_id=reviewer.provider_id,
        provider_session_id="review-session-001",
    )
    return complete_role_session(running)


def contribution(plan: MultiAgentPlan, verdict: ContributionVerdict):
    reviewer = next(
        item for item in plan.assignments if item.role is AgentRole.REVIEWER
    )
    return build_agent_contribution(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        verdict=verdict,
        summary="Independent reviewer evaluated the frozen AcceptedPlan scope.",
        evidence_paths=(".autodev/multi-agent/reviewer-session.json",),
        evidence_fingerprints=("d" * 64,),
    )


class MultiAgentReviewGateTests(unittest.TestCase):
    def test_clear_reviewer_builds_bound_authority_free_clearance(self) -> None:
        accepted = accepted_plan()
        plan = multi_agent_plan()
        review = contribution(plan, ContributionVerdict.CLEAR)
        reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(review,),
        )
        clearance = build_review_clearance(
            accepted_plan=accepted,
            plan=plan,
            role_session=completed_reviewer_session(plan),
            contribution=review,
            reconciliation=reconciliation,
            reviewed_head_sha=HEAD_SHA,
            pull_request_number=21,
        )
        payload = clearance.canonical_dict()
        self.assertEqual(payload["verdict"], "CLEAR")
        self.assertEqual(payload["reviewed_head_sha"], HEAD_SHA)
        self.assertEqual(payload["pull_request_number"], 21)
        self.assertEqual(payload["task_id"], "task-001")
        self.assertTrue(payload["advisory_evidence_only"])
        for field in (
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "merge_authority",
            "acceptance_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        ):
            self.assertFalse(payload[field], field)
        restored = ReviewClearance.from_dict(payload)
        self.assertEqual(restored.fingerprint(), clearance.fingerprint())

    def test_changes_required_cannot_become_clearance(self) -> None:
        accepted = accepted_plan()
        plan = multi_agent_plan()
        review = contribution(plan, ContributionVerdict.CHANGES_REQUIRED)
        reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(review,),
        )
        with self.assertRaisesRegex(MultiAgentReviewGateError, "CLEAR"):
            build_review_clearance(
                accepted_plan=accepted,
                plan=plan,
                role_session=completed_reviewer_session(plan),
                contribution=review,
                reconciliation=reconciliation,
                reviewed_head_sha=HEAD_SHA,
                pull_request_number=21,
            )

    def test_reviewer_session_must_be_completed_and_bound(self) -> None:
        accepted = accepted_plan()
        plan = multi_agent_plan()
        review = contribution(plan, ContributionVerdict.CLEAR)
        reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(review,),
        )
        reviewer = next(
            item for item in plan.assignments if item.role is AgentRole.REVIEWER
        )
        ready = role_session_for_assignment(plan, reviewer)
        running = start_role_session(
            ready,
            provider_id="jules",
            provider_session_id="review-session-001",
        )
        with self.assertRaisesRegex(MultiAgentReviewGateError, "completed"):
            build_review_clearance(
                accepted_plan=accepted,
                plan=plan,
                role_session=running,
                contribution=review,
                reconciliation=reconciliation,
                reviewed_head_sha=HEAD_SHA,
                pull_request_number=21,
            )

    def test_head_sha_and_pr_number_are_part_of_clearance_identity(self) -> None:
        accepted = accepted_plan()
        plan = multi_agent_plan()
        review = contribution(plan, ContributionVerdict.CLEAR)
        reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(review,),
        )
        session = completed_reviewer_session(plan)
        left = build_review_clearance(
            accepted_plan=accepted,
            plan=plan,
            role_session=session,
            contribution=review,
            reconciliation=reconciliation,
            reviewed_head_sha=HEAD_SHA,
            pull_request_number=21,
        )
        right = build_review_clearance(
            accepted_plan=accepted,
            plan=plan,
            role_session=session,
            contribution=review,
            reconciliation=reconciliation,
            reviewed_head_sha="e" * 40,
            pull_request_number=22,
        )
        self.assertNotEqual(left.fingerprint(), right.fingerprint())

    def test_clearance_deserialization_rejects_authority_escalation(self) -> None:
        accepted = accepted_plan()
        plan = multi_agent_plan()
        review = contribution(plan, ContributionVerdict.CLEAR)
        reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(review,),
        )
        payload = build_review_clearance(
            accepted_plan=accepted,
            plan=plan,
            role_session=completed_reviewer_session(plan),
            contribution=review,
            reconciliation=reconciliation,
            reviewed_head_sha=HEAD_SHA,
            pull_request_number=21,
        ).canonical_dict()
        payload["merge_authority"] = True
        with self.assertRaisesRegex(MultiAgentReviewGateError, "merge_authority"):
            ReviewClearance.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
