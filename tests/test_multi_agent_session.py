from __future__ import annotations

import unittest
from datetime import UTC, datetime

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_session import (
    RoleSessionError,
    assert_no_duplicate_live_session,
    pause_role_session_for_quota,
    resume_role_session,
    role_session_for_assignment,
    start_role_session,
)


def _plan():
    common = dict(
        repository="M-Osugi1230/example",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )
    implementer = AgentAssignment(
        assignment_id="implementer",
        role=AgentRole.IMPLEMENTER,
        provider_id="jules",
        objective="Implement accepted scope.",
        **common,
    )
    reviewer = AgentAssignment(
        assignment_id="reviewer",
        role=AgentRole.REVIEWER,
        provider_id="reviewer-agent",
        objective="Review accepted scope.",
        **common,
    )
    plan = MultiAgentPlan(
        plan_id="plan-001",
        assignments=(implementer, reviewer),
        **{
            key: common[key]
            for key in (
                "repository",
                "source_sha",
                "campaign_id",
                "task_id",
                "accepted_plan_fingerprint",
            )
        },
    )
    return plan, reviewer


class MultiAgentSessionTests(unittest.TestCase):
    def test_provider_affinity_and_duplicate_suppression(self) -> None:
        plan, reviewer = _plan()
        ready = role_session_for_assignment(plan, reviewer)

        with self.assertRaisesRegex(RoleSessionError, "provider affinity"):
            start_role_session(
                ready,
                provider_id="jules",
                provider_session_id="x",
            )

        running = start_role_session(
            ready,
            provider_id="reviewer-agent",
            provider_session_id="review-1",
        )

        with self.assertRaisesRegex(RoleSessionError, "live provider session"):
            assert_no_duplicate_live_session(ready, (running,))

    def test_role_session_round_trip_rejects_authority_escalation(self) -> None:
        plan, reviewer = _plan()
        running = start_role_session(
            role_session_for_assignment(plan, reviewer),
            provider_id="reviewer-agent",
            provider_session_id="review-1",
        )
        payload = running.canonical_dict()
        restored = type(running).from_dict(payload)
        self.assertEqual(restored.fingerprint(), running.fingerprint())

        payload["merge_authority"] = True
        with self.assertRaisesRegex(RoleSessionError, "merge authority"):
            type(running).from_dict(payload)

    def test_quota_resume_is_due_time_bound_and_session_is_reused(self) -> None:
        plan, reviewer = _plan()
        running = start_role_session(
            role_session_for_assignment(plan, reviewer),
            provider_id="reviewer-agent",
            provider_session_id="review-1",
        )
        paused = pause_role_session_for_quota(
            running,
            resume_after="2026-10-01T08:00:00+00:00",
        )

        with self.assertRaisesRegex(RoleSessionError, "resume_after"):
            resume_role_session(
                paused,
                provider_id="reviewer-agent",
                now=datetime(2026, 10, 1, 7, 59, tzinfo=UTC),
            )

        resumed = resume_role_session(
            paused,
            provider_id="reviewer-agent",
            now=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
        )
        self.assertEqual(resumed.provider_session_id, "review-1")
        self.assertEqual(resumed.attempt, 1)


if __name__ == "__main__":
    unittest.main()
