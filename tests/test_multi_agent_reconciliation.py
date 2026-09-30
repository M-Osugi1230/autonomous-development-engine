from __future__ import annotations

import unittest

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_reconciliation import (
    MultiAgentReconciliationError,
    ReconciliationDisposition,
    ReconciliationPolicy,
    ReconciliationReason,
    build_reconciliation_decision_request,
    reconcile_agent_contributions,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
PLAN_FP = "b" * 64


def assignment(role: AgentRole, provider_id: str) -> AgentAssignment:
    return AgentAssignment(
        assignment_id=f"agent-{role.value.lower()}",
        role=role,
        provider_id=provider_id,
        repository=REPO,
        source_sha=SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=PLAN_FP,
        objective=f"Perform bounded {role.value.lower()} role.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )


def plan(*roles: AgentRole) -> MultiAgentPlan:
    providers = {
        AgentRole.IMPLEMENTER: "jules",
        AgentRole.REVIEWER: "reviewer-agent",
        AgentRole.DIAGNOSTIC: "github-copilot",
    }
    items = [assignment(AgentRole.IMPLEMENTER, providers[AgentRole.IMPLEMENTER])]
    items.extend(assignment(role, providers[role]) for role in roles)
    return MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=REPO,
        source_sha=SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=PLAN_FP,
        assignments=tuple(items),
    )


def contribution(
    trusted_plan: MultiAgentPlan,
    role: AgentRole,
    verdict: ContributionVerdict,
):
    assignee = next(
        item for item in trusted_plan.assignments if item.role is role
    )
    return build_agent_contribution(
        plan=trusted_plan,
        assignment_id=assignee.assignment_id,
        verdict=verdict,
        summary=f"Bounded {role.value.lower()} finding is {verdict.value.lower()}.",
        evidence_paths=(
            f".autodev/multi-agent/{role.value.lower()}.json",
        ),
        evidence_fingerprints=(
            "d" * 64 if role is AgentRole.REVIEWER else "e" * 64,
        ),
    )


class MultiAgentReconciliationTests(unittest.TestCase):
    def test_all_clear_is_clear_without_merge_authority(self):
        trusted_plan = plan(AgentRole.REVIEWER, AgentRole.DIAGNOSTIC)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.REVIEWER,
                    ContributionVerdict.CLEAR,
                ),
                contribution(
                    trusted_plan,
                    AgentRole.DIAGNOSTIC,
                    ContributionVerdict.CLEAR,
                ),
            ),
        )
        self.assertEqual(
            result.disposition,
            ReconciliationDisposition.CLEAR,
        )
        self.assertEqual(result.reason, ReconciliationReason.ALL_CLEAR)
        payload = result.canonical_dict()
        self.assertFalse(payload["majority_voting"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["merge_authority"])
        self.assertFalse(payload["acceptance_authority"])
        self.assertFalse(payload["runtime_verification_authority"])

    def test_unanimous_changes_required_is_changes_required(self):
        trusted_plan = plan(AgentRole.REVIEWER, AgentRole.DIAGNOSTIC)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.REVIEWER,
                    ContributionVerdict.CHANGES_REQUIRED,
                ),
                contribution(
                    trusted_plan,
                    AgentRole.DIAGNOSTIC,
                    ContributionVerdict.CHANGES_REQUIRED,
                ),
            ),
        )
        self.assertEqual(
            result.disposition,
            ReconciliationDisposition.CHANGES_REQUIRED,
        )
        self.assertEqual(
            result.reason,
            ReconciliationReason.CHANGES_REQUESTED,
        )

    def test_material_disagreement_enters_human_wait_not_vote(self):
        trusted_plan = plan(AgentRole.REVIEWER, AgentRole.DIAGNOSTIC)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.REVIEWER,
                    ContributionVerdict.CLEAR,
                ),
                contribution(
                    trusted_plan,
                    AgentRole.DIAGNOSTIC,
                    ContributionVerdict.CHANGES_REQUIRED,
                ),
            ),
        )
        self.assertEqual(
            result.disposition,
            ReconciliationDisposition.HUMAN_WAIT,
        )
        self.assertEqual(
            result.reason,
            ReconciliationReason.MATERIAL_DISAGREEMENT,
        )
        request = build_reconciliation_decision_request(result)
        self.assertEqual(request.blocking_task_id, trusted_plan.task_id)
        self.assertEqual(request.decision_id, result.human_decision_id)
        self.assertEqual(
            request.context["multi_agent_plan_fingerprint"],
            trusted_plan.fingerprint(),
        )

    def test_explicit_human_review_verdict_enters_human_wait(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.REVIEWER,
                    ContributionVerdict.HUMAN_REVIEW_REQUIRED,
                ),
            ),
        )
        self.assertEqual(
            result.disposition,
            ReconciliationDisposition.HUMAN_WAIT,
        )
        self.assertEqual(
            result.reason,
            ReconciliationReason.HUMAN_REVIEW_REQUIRED,
        )

    def test_missing_required_reviewer_is_incomplete(self):
        trusted_plan = plan(AgentRole.REVIEWER, AgentRole.DIAGNOSTIC)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.DIAGNOSTIC,
                    ContributionVerdict.CLEAR,
                ),
            ),
        )
        self.assertEqual(
            result.disposition,
            ReconciliationDisposition.INCOMPLETE,
        )
        self.assertEqual(
            result.reason,
            ReconciliationReason.MISSING_REQUIRED_CONTRIBUTION,
        )

    def test_duplicate_assignment_contribution_fails_closed(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        item = contribution(
            trusted_plan,
            AgentRole.REVIEWER,
            ContributionVerdict.CLEAR,
        )
        with self.assertRaisesRegex(
            MultiAgentReconciliationError,
            "duplicate contribution",
        ):
            reconcile_agent_contributions(
                plan=trusted_plan,
                contributions=(item, item),
            )

    def test_policy_requires_reviewer_assignment(self):
        trusted_plan = plan()
        with self.assertRaisesRegex(
            MultiAgentReconciliationError,
            "REVIEWER assignment",
        ):
            reconcile_agent_contributions(
                plan=trusted_plan,
                contributions=(),
            )

    def test_decision_request_only_exists_for_human_wait(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        result = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(
                contribution(
                    trusted_plan,
                    AgentRole.REVIEWER,
                    ContributionVerdict.CLEAR,
                ),
            ),
        )
        with self.assertRaisesRegex(
            MultiAgentReconciliationError,
            "HUMAN_WAIT",
        ):
            build_reconciliation_decision_request(result)

    def test_reconciliation_is_order_deterministic(self):
        trusted_plan = plan(AgentRole.REVIEWER, AgentRole.DIAGNOSTIC)
        review = contribution(
            trusted_plan,
            AgentRole.REVIEWER,
            ContributionVerdict.CLEAR,
        )
        diagnostic = contribution(
            trusted_plan,
            AgentRole.DIAGNOSTIC,
            ContributionVerdict.CHANGES_REQUIRED,
        )
        left = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(review, diagnostic),
        )
        right = reconcile_agent_contributions(
            plan=trusted_plan,
            contributions=(diagnostic, review),
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())

    def test_policy_never_uses_majority_voting(self):
        payload = ReconciliationPolicy().canonical_dict()
        self.assertFalse(payload["majority_voting"])
        self.assertFalse(payload["merge_authority"])
        self.assertFalse(payload["acceptance_authority"])


if __name__ == "__main__":
    unittest.main()
