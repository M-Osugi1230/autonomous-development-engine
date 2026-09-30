from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_runtime import (
    MultiAgentLeaseState,
    MultiAgentRuntimeError,
    RoleSessionAction,
    RoleSessionState,
    complete_role_session,
    decide_role_session_action,
    mark_role_running,
    pause_role_for_quota,
    pending_role_checkpoint,
    validate_role_checkpoint,
)
from ade.provider_availability import ProviderAvailabilityRecord
from ade.provider_router import ProviderAvailability


REPO = "M-Osugi1230/one-minute-thought-experiments"


def assignment(role: AgentRole, provider_id: str = "jules") -> AgentAssignment:
    return AgentAssignment(
        assignment_id=f"agent-{role.value.lower()}",
        role=role,
        provider_id=provider_id,
        repository=REPO,
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        objective=f"Perform bounded {role.value.lower()} role.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )


def plan() -> MultiAgentPlan:
    return MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=REPO,
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        assignments=(
            assignment(AgentRole.IMPLEMENTER, "jules"),
            assignment(AgentRole.REVIEWER, "jules"),
        ),
    )


def available(provider_id: str = "jules") -> ProviderAvailabilityRecord:
    return ProviderAvailabilityRecord(
        provider_id=provider_id,
        availability=ProviderAvailability.AVAILABLE,
    )


class MultiAgentRuntimeTests(unittest.TestCase):
    def test_pending_role_starts_then_running_only_monitors(self):
        trusted_plan = plan()
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        checkpoint = pending_role_checkpoint(
            trusted_plan,
            reviewer.assignment_id,
        )
        now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        self.assertEqual(
            decide_role_session_action(
                checkpoint=checkpoint,
                plan=trusted_plan,
                availability=available(),
                now=now,
            ),
            RoleSessionAction.START_NEW,
        )
        running = mark_role_running(
            checkpoint,
            provider_session_id="review-session-1",
        )
        self.assertEqual(running.state, RoleSessionState.RUNNING)
        self.assertEqual(running.attempt, 1)
        self.assertEqual(
            decide_role_session_action(
                checkpoint=running,
                plan=trusted_plan,
                availability=available(),
                now=now,
            ),
            RoleSessionAction.MONITOR,
        )

    def test_quota_pause_preserves_provider_and_session_affinity(self):
        trusted_plan = plan()
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        checkpoint = mark_role_running(
            pending_role_checkpoint(
                trusted_plan,
                reviewer.assignment_id,
            ),
            provider_session_id="review-session-1",
        )
        paused = pause_role_for_quota(
            checkpoint,
            resume_after="2026-10-01T01:00:00+00:00",
            last_error="provider quota is temporarily exhausted",
        )
        self.assertEqual(paused.provider_id, "jules")
        self.assertEqual(
            paused.provider_session_id,
            "review-session-1",
        )
        self.assertEqual(
            decide_role_session_action(
                checkpoint=paused,
                plan=trusted_plan,
                availability=ProviderAvailabilityRecord(
                    provider_id="jules",
                    availability=ProviderAvailability.QUOTA_PAUSED,
                    resume_after="2026-10-01T01:00:00+00:00",
                    last_error="provider quota is temporarily exhausted",
                ),
                now=datetime(2026, 10, 1, 0, 30, tzinfo=UTC),
            ),
            RoleSessionAction.WAIT_QUOTA,
        )
        self.assertEqual(
            decide_role_session_action(
                checkpoint=paused,
                plan=trusted_plan,
                availability=ProviderAvailabilityRecord(
                    provider_id="jules",
                    availability=ProviderAvailability.QUOTA_PAUSED,
                    resume_after="2026-10-01T01:00:00+00:00",
                    last_error="provider quota is temporarily exhausted",
                ),
                now=datetime(2026, 10, 1, 1, 1, tzinfo=UTC),
            ),
            RoleSessionAction.MONITOR,
        )

    def test_quota_before_session_restarts_same_assignment_when_due(self):
        trusted_plan = plan()
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        pending = pending_role_checkpoint(
            trusted_plan,
            reviewer.assignment_id,
        )
        paused = pause_role_for_quota(
            pending,
            resume_after="2026-10-01T01:00:00+00:00",
            last_error="provider quota is temporarily exhausted",
        )
        self.assertIsNone(paused.provider_session_id)
        self.assertEqual(
            decide_role_session_action(
                checkpoint=paused,
                plan=trusted_plan,
                availability=available(),
                now=datetime(2026, 10, 1, 1, 1, tzinfo=UTC),
            ),
            RoleSessionAction.START_NEW,
        )
        self.assertEqual(paused.provider_id, reviewer.provider_id)

    def test_provider_affinity_mismatch_fails_closed(self):
        trusted_plan = plan()
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        checkpoint = pending_role_checkpoint(
            trusted_plan,
            reviewer.assignment_id,
        )
        with self.assertRaisesRegex(
            MultiAgentRuntimeError,
            "provider",
        ):
            decide_role_session_action(
                checkpoint=checkpoint,
                plan=trusted_plan,
                availability=available("github-copilot"),
                now=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
            )

    def test_role_leases_are_independent_and_duplicate_safe(self):
        trusted_plan = plan()
        implementer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.IMPLEMENTER
        )
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        ttl = timedelta(minutes=15)
        leases = MultiAgentLeaseState()

        leases, impl_lease = leases.acquire(
            plan=trusted_plan,
            assignment_id=implementer.assignment_id,
            owner_id="worker-implementer",
            now=now,
            ttl=ttl,
        )
        leases, review_lease = leases.acquire(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            owner_id="worker-reviewer",
            now=now,
            ttl=ttl,
        )
        self.assertNotEqual(impl_lease.task_id, review_lease.task_id)
        self.assertEqual(len(leases.leases), 2)

        same_state, same_lease = leases.acquire(
            plan=trusted_plan,
            assignment_id=reviewer.assignment_id,
            owner_id="worker-reviewer",
            now=now + timedelta(minutes=1),
            ttl=ttl,
        )
        self.assertEqual(same_lease, review_lease)
        self.assertEqual(same_state.fingerprint(), leases.fingerprint())

        with self.assertRaisesRegex(RuntimeError, "live execution lease"):
            leases.acquire(
                plan=trusted_plan,
                assignment_id=reviewer.assignment_id,
                owner_id="duplicate-worker",
                now=now + timedelta(minutes=1),
                ttl=ttl,
            )

    def test_checkpoint_round_trip_and_completion(self):
        trusted_plan = plan()
        reviewer = next(
            item
            for item in trusted_plan.assignments
            if item.role is AgentRole.REVIEWER
        )
        running = mark_role_running(
            pending_role_checkpoint(
                trusted_plan,
                reviewer.assignment_id,
            ),
            provider_session_id="review-session-1",
        )
        restored = type(running).from_dict(running.canonical_dict())
        self.assertEqual(restored.fingerprint(), running.fingerprint())
        validate_role_checkpoint(restored, trusted_plan)
        completed = complete_role_session(restored)
        self.assertEqual(completed.state, RoleSessionState.COMPLETED)
        self.assertEqual(
            decide_role_session_action(
                checkpoint=completed,
                plan=trusted_plan,
                availability=available(),
                now=datetime(2026, 10, 1, 2, 0, tzinfo=UTC),
            ),
            RoleSessionAction.NOOP,
        )


if __name__ == "__main__":
    unittest.main()
