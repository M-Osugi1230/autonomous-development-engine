from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_runtime import (
    MultiAgentLeaseState,
    RoleSessionAction,
    decide_role_session_action,
    mark_role_running,
    pause_role_for_quota,
    pending_role_checkpoint,
)
from ade.provider_availability import ProviderAvailabilityRecord
from ade.provider_router import ProviderAvailability


def assignment(role: AgentRole) -> AgentAssignment:
    return AgentAssignment(
        assignment_id=f"agent-{role.value.lower()}",
        role=role,
        provider_id="jules",
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        objective=f"Perform bounded {role.value.lower()} role.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )


def main() -> int:
    plan = MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        assignments=(
            assignment(AgentRole.IMPLEMENTER),
            assignment(AgentRole.REVIEWER),
        ),
    )
    implementer = next(
        item for item in plan.assignments
        if item.role is AgentRole.IMPLEMENTER
    )
    reviewer = next(
        item for item in plan.assignments
        if item.role is AgentRole.REVIEWER
    )
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    ttl = timedelta(minutes=15)

    leases = MultiAgentLeaseState()
    leases, implementer_lease = leases.acquire(
        plan=plan,
        assignment_id=implementer.assignment_id,
        owner_id="worker-implementer",
        now=now,
        ttl=ttl,
    )
    leases, reviewer_lease = leases.acquire(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        owner_id="worker-reviewer",
        now=now,
        ttl=ttl,
    )
    assert implementer_lease.task_id != reviewer_lease.task_id
    assert len(leases.leases) == 2

    reviewer_checkpoint = mark_role_running(
        pending_role_checkpoint(plan, reviewer.assignment_id),
        provider_session_id="review-session-1",
    )
    assert decide_role_session_action(
        checkpoint=reviewer_checkpoint,
        plan=plan,
        availability=ProviderAvailabilityRecord(
            provider_id="jules",
            availability=ProviderAvailability.AVAILABLE,
        ),
        now=now,
    ) is RoleSessionAction.MONITOR

    paused = pause_role_for_quota(
        reviewer_checkpoint,
        resume_after="2026-10-01T01:00:00+00:00",
        last_error="provider quota is temporarily exhausted",
    )
    assert decide_role_session_action(
        checkpoint=paused,
        plan=plan,
        availability=ProviderAvailabilityRecord(
            provider_id="jules",
            availability=ProviderAvailability.QUOTA_PAUSED,
            resume_after="2026-10-01T01:00:00+00:00",
            last_error="provider quota is temporarily exhausted",
        ),
        now=datetime(2026, 10, 1, 0, 30, tzinfo=UTC),
    ) is RoleSessionAction.WAIT_QUOTA
    assert decide_role_session_action(
        checkpoint=paused,
        plan=plan,
        availability=ProviderAvailabilityRecord(
            provider_id="jules",
            availability=ProviderAvailability.QUOTA_PAUSED,
            resume_after="2026-10-01T01:00:00+00:00",
            last_error="provider quota is temporarily exhausted",
        ),
        now=datetime(2026, 10, 1, 1, 1, tzinfo=UTC),
    ) is RoleSessionAction.MONITOR
    assert paused.provider_id == reviewer.provider_id
    assert paused.provider_session_id == "review-session-1"

    duplicate_suppressed = False
    try:
        leases.acquire(
            plan=plan,
            assignment_id=reviewer.assignment_id,
            owner_id="duplicate-worker",
            now=now + timedelta(minutes=1),
            ttl=ttl,
        )
    except RuntimeError:
        duplicate_suppressed = True
    assert duplicate_suppressed

    print(
        json.dumps(
            {
                "ok": True,
                "independent_role_leases": True,
                "same_task_same_provider_supported": True,
                "duplicate_suppressed": True,
                "running_action": "MONITOR",
                "quota_action_before_due": "WAIT_QUOTA",
                "quota_action_after_due": "MONITOR",
                "provider_affinity_preserved": True,
                "session_affinity_preserved": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
