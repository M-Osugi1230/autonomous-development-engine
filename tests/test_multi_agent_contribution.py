from __future__ import annotations

import unittest

from ade.multi_agent import (
    AgentAssignment,
    AgentRole,
    MultiAgentPlan,
)
from ade.multi_agent_contribution import (
    AgentContribution,
    ContributionKind,
    ContributionVerdict,
    MultiAgentContributionError,
    build_agent_contribution,
    validate_contribution_against_plan,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
PLAN_FP = "b" * 64
EVIDENCE_FP = "c" * 64


def assignment(
    role: AgentRole,
    *,
    assignment_id: str | None = None,
    provider_id: str | None = None,
) -> AgentAssignment:
    return AgentAssignment(
        assignment_id=assignment_id or f"agent-{role.value.lower()}",
        role=role,
        provider_id=provider_id or (
            "jules" if role is AgentRole.IMPLEMENTER else "reviewer-agent"
        ),
        repository=REPO,
        source_sha=SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=PLAN_FP,
        objective=f"Perform bounded {role.value.lower()} role.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=(EVIDENCE_FP,),
    )


def plan(*roles: AgentRole) -> MultiAgentPlan:
    assignments = [assignment(AgentRole.IMPLEMENTER)]
    for role in roles:
        assignments.append(assignment(role))
    return MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=REPO,
        source_sha=SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=PLAN_FP,
        assignments=tuple(assignments),
    )


class MultiAgentContributionTests(unittest.TestCase):
    def test_reviewer_contribution_is_deterministic_and_advisory_only(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        left = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            verdict=ContributionVerdict.CLEAR,
            summary="No material issue found within the frozen task scope.",
            evidence_paths=(".autodev/multi-agent/review.json",),
            evidence_fingerprints=("d" * 64,),
        )
        right = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            verdict=ContributionVerdict.CLEAR,
            summary="No material issue found within the frozen task scope.",
            evidence_paths=(".autodev/multi-agent/review.json",),
            evidence_fingerprints=("d" * 64,),
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())
        self.assertEqual(left.kind, ContributionKind.REVIEW)
        validate_contribution_against_plan(left, trusted_plan)

        payload = left.canonical_dict()
        self.assertTrue(payload["advisory_only"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["code_mutation_authority"])
        self.assertFalse(payload["campaign_state_authority"])
        self.assertFalse(payload["acceptance_authority"])
        self.assertFalse(payload["merge_authority"])
        self.assertFalse(payload["runtime_verification_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["may_expand_scope"])

    def test_diagnostic_contribution_is_supported(self):
        trusted_plan = plan(AgentRole.DIAGNOSTIC)
        diagnostic = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.DIAGNOSTIC
        )
        contribution = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=diagnostic.assignment_id,
            verdict=ContributionVerdict.CHANGES_REQUIRED,
            summary="Observed a bounded reproducible issue in the tested path.",
            evidence_paths=(".autodev/multi-agent/diagnostic.json",),
            evidence_fingerprints=("e" * 64,),
        )
        self.assertEqual(contribution.kind, ContributionKind.DIAGNOSTIC)
        self.assertEqual(
            contribution.verdict,
            ContributionVerdict.CHANGES_REQUIRED,
        )
        validate_contribution_against_plan(contribution, trusted_plan)

    def test_implementer_cannot_emit_advisory_contribution(self):
        trusted_plan = plan()
        implementer = trusted_plan.assignments[0]
        with self.assertRaisesRegex(
            MultiAgentContributionError,
            "IMPLEMENTER",
        ):
            build_agent_contribution(
                plan=trusted_plan,
                assignment_id=implementer.assignment_id,
                verdict=ContributionVerdict.CLEAR,
                summary="Implementation is complete.",
                evidence_paths=(".autodev/multi-agent/implementer.json",),
                evidence_fingerprints=("f" * 64,),
            )

    def test_contribution_round_trip_preserves_fingerprint(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        contribution = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            verdict=ContributionVerdict.HUMAN_REVIEW_REQUIRED,
            summary="A trusted human boundary requires an explicit decision.",
            evidence_paths=(".autodev/multi-agent/review.json",),
            evidence_fingerprints=("d" * 64,),
        )
        restored = AgentContribution.from_dict(
            contribution.canonical_dict()
        )
        self.assertEqual(restored.fingerprint(), contribution.fingerprint())
        validate_contribution_against_plan(restored, trusted_plan)

    def test_authority_escalation_is_rejected(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        payload = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            verdict=ContributionVerdict.CLEAR,
            summary="No material issue found.",
            evidence_paths=(".autodev/multi-agent/review.json",),
            evidence_fingerprints=("d" * 64,),
        ).canonical_dict()
        for field in (
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "acceptance_authority",
            "merge_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        ):
            with self.subTest(field=field):
                tampered = dict(payload)
                tampered[field] = True
                with self.assertRaises(MultiAgentContributionError):
                    AgentContribution.from_dict(tampered)

    def test_plan_or_assignment_drift_fails_closed(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        contribution = build_agent_contribution(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            verdict=ContributionVerdict.CLEAR,
            summary="No material issue found.",
            evidence_paths=(".autodev/multi-agent/review.json",),
            evidence_fingerprints=("d" * 64,),
        )
        different_plan = MultiAgentPlan(
            plan_id="multi-agent-plan-002",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(
                assignment(AgentRole.IMPLEMENTER),
                assignment(
                    AgentRole.REVIEWER,
                    provider_id="github-copilot",
                ),
            ),
        )
        with self.assertRaisesRegex(
            MultiAgentContributionError,
            "MultiAgentPlan fingerprint",
        ):
            validate_contribution_against_plan(
                contribution,
                different_plan,
            )

    def test_unsafe_summary_and_evidence_fail_closed(self):
        trusted_plan = plan(AgentRole.REVIEWER)
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        with self.assertRaisesRegex(
            MultiAgentContributionError,
            "URLs",
        ):
            build_agent_contribution(
                plan=trusted_plan,
                assignment_id=reviewer.assignment_id,
                verdict=ContributionVerdict.CLEAR,
                summary="See https://example.com for review.",
                evidence_paths=(".autodev/multi-agent/review.json",),
                evidence_fingerprints=("d" * 64,),
            )
        with self.assertRaisesRegex(
            MultiAgentContributionError,
            "inside .autodev",
        ):
            build_agent_contribution(
                plan=trusted_plan,
                assignment_id=reviewer.assignment_id,
                verdict=ContributionVerdict.CLEAR,
                summary="No material issue found.",
                evidence_paths=("review.json",),
                evidence_fingerprints=("d" * 64,),
            )


if __name__ == "__main__":
    unittest.main()
