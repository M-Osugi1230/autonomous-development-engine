from __future__ import annotations

import unittest

from ade.multi_agent import (
    AgentAssignment,
    AgentRole,
    MultiAgentError,
    MultiAgentPlan,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
PLAN_FP = "b" * 64
EVIDENCE_FP = "c" * 64


def assignment(
    role: AgentRole,
    *,
    assignment_id: str | None = None,
    provider_id: str = "jules",
    source_sha: str = SHA,
) -> AgentAssignment:
    return AgentAssignment(
        assignment_id=assignment_id or f"agent-{role.value.lower()}",
        role=role,
        provider_id=provider_id,
        repository=REPO,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=PLAN_FP,
        objective=f"Perform the bounded {role.value.lower()} role for task-001.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=(EVIDENCE_FP,),
    )


class MultiAgentTests(unittest.TestCase):
    def test_plan_is_order_deterministic_and_authority_free(self) -> None:
        implementer = assignment(AgentRole.IMPLEMENTER)
        reviewer = assignment(
            AgentRole.REVIEWER,
            provider_id="github-copilot",
        )
        left = MultiAgentPlan(
            plan_id="multi-agent-plan-001",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(reviewer, implementer),
        )
        right = MultiAgentPlan(
            plan_id="multi-agent-plan-001",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(implementer, reviewer),
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())
        payload = left.canonical_dict()
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["merge_authority"])
        self.assertFalse(payload["acceptance_authority"])
        self.assertFalse(payload["may_expand_scope"])
        self.assertEqual(
            payload["provider_ids"],
            ["github-copilot", "jules"],
        )

    def test_round_trip_preserves_fingerprint(self) -> None:
        plan = MultiAgentPlan(
            plan_id="multi-agent-plan-001",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(
                assignment(AgentRole.IMPLEMENTER),
                assignment(AgentRole.DIAGNOSTIC),
            ),
        )
        restored = MultiAgentPlan.from_dict(plan.canonical_dict())
        self.assertEqual(restored.fingerprint(), plan.fingerprint())

    def test_exactly_one_implementer_is_required(self) -> None:
        with self.assertRaisesRegex(MultiAgentError, "IMPLEMENTER"):
            MultiAgentPlan(
                plan_id="multi-agent-plan-001",
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="task-001",
                accepted_plan_fingerprint=PLAN_FP,
                assignments=(assignment(AgentRole.REVIEWER),),
            )

        with self.assertRaisesRegex(MultiAgentError, "duplicate agent role"):
            MultiAgentPlan(
                plan_id="multi-agent-plan-001",
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="task-001",
                accepted_plan_fingerprint=PLAN_FP,
                assignments=(
                    assignment(AgentRole.IMPLEMENTER, assignment_id="impl-a"),
                    assignment(AgentRole.IMPLEMENTER, assignment_id="impl-b"),
                ),
            )

    def test_cross_anchor_assignment_fails_closed(self) -> None:
        with self.assertRaisesRegex(MultiAgentError, "trust anchor"):
            MultiAgentPlan(
                plan_id="multi-agent-plan-001",
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="task-001",
                accepted_plan_fingerprint=PLAN_FP,
                assignments=(
                    assignment(
                        AgentRole.IMPLEMENTER,
                        source_sha="d" * 40,
                    ),
                ),
            )

    def test_authority_escalation_is_rejected(self) -> None:
        payload = assignment(AgentRole.IMPLEMENTER).canonical_dict()
        payload["merge_authority"] = True
        with self.assertRaisesRegex(MultiAgentError, "merge authority"):
            AgentAssignment.from_dict(payload)

        plan = MultiAgentPlan(
            plan_id="multi-agent-plan-001",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(assignment(AgentRole.IMPLEMENTER),),
        ).canonical_dict()
        plan["execution_authority"] = True
        with self.assertRaisesRegex(MultiAgentError, "execution authority"):
            MultiAgentPlan.from_dict(plan)

    def test_objective_and_evidence_are_bounded(self) -> None:
        with self.assertRaisesRegex(MultiAgentError, "URLs"):
            AgentAssignment(
                assignment_id="agent-implementer",
                role=AgentRole.IMPLEMENTER,
                provider_id="jules",
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="task-001",
                accepted_plan_fingerprint=PLAN_FP,
                objective="Read https://example.com and implement it.",
                evidence_paths=(".autodev/accepted-plan.json",),
                evidence_fingerprints=(EVIDENCE_FP,),
            )

        with self.assertRaisesRegex(MultiAgentError, "trusted evidence"):
            AgentAssignment(
                assignment_id="agent-implementer",
                role=AgentRole.IMPLEMENTER,
                provider_id="jules",
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="task-001",
                accepted_plan_fingerprint=PLAN_FP,
                objective="Implement only the accepted bounded task.",
                evidence_paths=(),
                evidence_fingerprints=(),
            )

    def test_same_provider_can_hold_distinct_roles_without_gaining_authority(self) -> None:
        plan = MultiAgentPlan(
            plan_id="multi-agent-plan-001",
            repository=REPO,
            source_sha=SHA,
            campaign_id="campaign-001",
            task_id="task-001",
            accepted_plan_fingerprint=PLAN_FP,
            assignments=(
                assignment(AgentRole.IMPLEMENTER, provider_id="jules"),
                assignment(AgentRole.REVIEWER, provider_id="jules"),
            ),
        )
        self.assertEqual(plan.provider_ids, ("jules",))
        self.assertEqual(len(plan.assignments), 2)


if __name__ == "__main__":
    unittest.main()
