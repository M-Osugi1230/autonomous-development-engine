from __future__ import annotations

from datetime import UTC, datetime

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_session import (
    RoleSessionError,
    assert_no_duplicate_live_session,
    complete_role_session,
    pause_role_session_for_quota,
    resume_role_session,
    role_session_for_assignment,
    start_role_session,
)


def main() -> int:
    assignment = AgentAssignment(
        assignment_id="agent-reviewer",
        role=AgentRole.REVIEWER,
        provider_id="reviewer-agent",
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint="b" * 64,
        objective="Review bounded accepted task evidence.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )
    implementer = AgentAssignment(
        assignment_id="agent-implementer",
        role=AgentRole.IMPLEMENTER,
        provider_id="jules",
        repository=assignment.repository,
        source_sha=assignment.source_sha,
        campaign_id=assignment.campaign_id,
        task_id=assignment.task_id,
        accepted_plan_fingerprint=assignment.accepted_plan_fingerprint,
        objective="Implement bounded accepted task.",
        evidence_paths=assignment.evidence_paths,
        evidence_fingerprints=assignment.evidence_fingerprints,
    )
    plan = MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=assignment.repository,
        source_sha=assignment.source_sha,
        campaign_id=assignment.campaign_id,
        task_id=assignment.task_id,
        accepted_plan_fingerprint=assignment.accepted_plan_fingerprint,
        assignments=(implementer, assignment),
    )
    ready = role_session_for_assignment(plan, assignment)
    running = start_role_session(
        ready,
        provider_id="reviewer-agent",
        provider_session_id="review-session-001",
    )
    try:
        assert_no_duplicate_live_session(ready, (running,))
    except RoleSessionError:
        pass
    else:
        raise AssertionError("duplicate live reviewer session was not rejected")

    paused = pause_role_session_for_quota(
        running,
        resume_after="2026-10-01T08:00:00+00:00",
    )
    try:
        resume_role_session(
            paused,
            provider_id="reviewer-agent",
            now=datetime(2026, 10, 1, 7, 59, tzinfo=UTC),
        )
    except RoleSessionError:
        pass
    else:
        raise AssertionError("pre-due quota resume was not rejected")

    resumed = resume_role_session(
        paused,
        provider_id="reviewer-agent",
        now=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
    )
    completed = complete_role_session(resumed)
    payload = completed.canonical_dict()
    assert payload["provider_id"] == "reviewer-agent"
    assert payload["provider_session_id"] == "review-session-001"
    assert payload["execution_authority"] is False
    assert payload["merge_authority"] is False
    assert payload["acceptance_authority"] is False
    assert payload["may_expand_scope"] is False
    print("multi-agent role session lifecycle proof: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
