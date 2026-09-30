from __future__ import annotations

import json

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
    validate_contribution_against_plan,
)


def assignment(role: AgentRole, provider_id: str) -> AgentAssignment:
    return AgentAssignment(
        assignment_id=f"agent-{role.value.lower()}",
        role=role,
        provider_id=provider_id,
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
            assignment(AgentRole.IMPLEMENTER, "jules"),
            assignment(AgentRole.REVIEWER, "reviewer-agent"),
            assignment(AgentRole.DIAGNOSTIC, "github-copilot"),
        ),
    )

    reviewer = next(
        item
        for item in plan.assignments
        if item.role is AgentRole.REVIEWER
    )
    diagnostic = next(
        item
        for item in plan.assignments
        if item.role is AgentRole.DIAGNOSTIC
    )
    review = build_agent_contribution(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        verdict=ContributionVerdict.CLEAR,
        summary="No material issue found within the frozen task scope.",
        evidence_paths=(".autodev/multi-agent/review.json",),
        evidence_fingerprints=("d" * 64,),
    )
    diagnosis = build_agent_contribution(
        plan=plan,
        assignment_id=diagnostic.assignment_id,
        verdict=ContributionVerdict.CHANGES_REQUIRED,
        summary="Observed one bounded issue requiring controller reconciliation.",
        evidence_paths=(".autodev/multi-agent/diagnostic.json",),
        evidence_fingerprints=("e" * 64,),
    )
    validate_contribution_against_plan(review, plan)
    validate_contribution_against_plan(diagnosis, plan)

    for contribution in (review, diagnosis):
        payload = contribution.canonical_dict()
        assert payload["advisory_only"] is True
        assert payload["execution_authority"] is False
        assert payload["code_mutation_authority"] is False
        assert payload["campaign_state_authority"] is False
        assert payload["acceptance_authority"] is False
        assert payload["merge_authority"] is False
        assert payload["runtime_verification_authority"] is False
        assert payload["auto_dispatch"] is False
        assert payload["may_expand_scope"] is False

    print(
        json.dumps(
            {
                "ok": True,
                "review_fingerprint": review.fingerprint(),
                "diagnostic_fingerprint": diagnosis.fingerprint(),
                "plan_bound": True,
                "assignment_bound": True,
                "fixed_verdicts": [
                    review.verdict.value,
                    diagnosis.verdict.value,
                ],
                "advisory_only": True,
                "code_mutation_authority": False,
                "campaign_state_authority": False,
                "acceptance_authority": False,
                "merge_authority": False,
                "runtime_verification_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
