from __future__ import annotations

import json

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_reconciliation import reconcile_agent_contributions
from ade.multi_agent_review_gate import build_review_clearance
from ade.multi_agent_session import (
    complete_role_session,
    role_session_for_assignment,
    start_role_session,
)


def main() -> int:
    repository = "M-Osugi1230/one-minute-thought-experiments"
    source_sha = "a" * 40
    head_sha = "b" * 40
    development = DevelopmentPlan(
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
    accepted = AcceptedPlan.accept(development)
    common = dict(
        repository=repository,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted.fingerprint,
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("c" * 64,),
    )
    implementer = AgentAssignment(
        assignment_id="implementer",
        role=AgentRole.IMPLEMENTER,
        provider_id="jules",
        objective="Implement frozen AcceptedPlan scope.",
        **common,
    )
    reviewer = AgentAssignment(
        assignment_id="reviewer",
        role=AgentRole.REVIEWER,
        provider_id="jules",
        objective="Review frozen AcceptedPlan scope.",
        **common,
    )
    plan = MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=repository,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted.fingerprint,
        assignments=(implementer, reviewer),
    )
    role_session = complete_role_session(
        start_role_session(
            role_session_for_assignment(plan, reviewer),
            provider_id="jules",
            provider_session_id="independent-review-session",
        )
    )
    contribution = build_agent_contribution(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        verdict=ContributionVerdict.CLEAR,
        summary=(
            "Independent reviewer reported no material issue within the "
            "frozen AcceptedPlan scope."
        ),
        evidence_paths=(".autodev/multi-agent/reviewer-observation.json",),
        evidence_fingerprints=("d" * 64,),
    )
    reconciliation = reconcile_agent_contributions(
        plan=plan,
        contributions=(contribution,),
    )
    clearance = build_review_clearance(
        accepted_plan=accepted,
        plan=plan,
        role_session=role_session,
        contribution=contribution,
        reconciliation=reconciliation,
        reviewed_head_sha=head_sha,
        pull_request_number=21,
    )
    payload = clearance.canonical_dict()
    assert payload["verdict"] == "CLEAR"
    assert payload["reviewed_head_sha"] == head_sha
    assert payload["pull_request_number"] == 21
    assert payload["reviewer_provider_id"] == "jules"
    assert payload["advisory_evidence_only"] is True
    assert payload["execution_authority"] is False
    assert payload["code_mutation_authority"] is False
    assert payload["merge_authority"] is False
    assert payload["acceptance_authority"] is False
    assert payload["runtime_verification_authority"] is False
    assert payload["auto_dispatch"] is False
    assert payload["may_expand_scope"] is False
    assert role_session.provider_session_id != "implementer-session"

    print(
        json.dumps(
            {
                "ok": True,
                "independent_role_session": True,
                "clearance_bound_to_pr_head": True,
                "clearance_bound_to_reviewer_evidence": True,
                "reviewer_merge_authority": False,
                "reviewer_execution_authority": False,
                "clearance_fingerprint": clearance.fingerprint(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
