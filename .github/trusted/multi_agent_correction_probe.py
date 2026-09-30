from __future__ import annotations

import json

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_correction import (
    CorrectionHumanWaitReason,
    CorrectionPolicy,
    CorrectionStage,
    advance_correction_loop,
    initial_correction_loop_state,
    mark_correction_implemented,
)
from ade.multi_agent_reconciliation import reconcile_agent_contributions


def main() -> int:
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
        human_boundaries=("destructive or irreversible operation",),
    )
    accepted = AcceptedPlan.accept(development)
    common = dict(
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted.fingerprint,
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=("b" * 64,),
    )
    plan = MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=common["repository"],
        source_sha=common["source_sha"],
        campaign_id=common["campaign_id"],
        task_id=common["task_id"],
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
                provider_id="reviewer-agent",
                objective="Review frozen AcceptedPlan scope.",
                **common,
            ),
        ),
    )
    reviewer = next(
        item for item in plan.assignments if item.role is AgentRole.REVIEWER
    )
    contribution = build_agent_contribution(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        verdict=ContributionVerdict.CHANGES_REQUIRED,
        summary="A bounded issue remains; do not expand the accepted scope.",
        evidence_paths=(".autodev/multi-agent/reviewer.json",),
        evidence_fingerprints=("c" * 64,),
    )
    reconciliation = reconcile_agent_contributions(
        plan=plan,
        contributions=(contribution,),
    )
    policy = CorrectionPolicy(max_correction_rounds=2)
    state = initial_correction_loop_state(
        accepted_plan=accepted,
        plan=plan,
    )
    request_fingerprints = []
    for expected_round in (1, 2):
        decision = advance_correction_loop(
            state=state,
            accepted_plan=accepted,
            plan=plan,
            reconciliation=reconciliation,
            contributions=(contribution,),
            policy=policy,
        )
        assert decision.state.stage is CorrectionStage.CORRECTION_PENDING
        request = decision.correction_request
        assert request is not None
        assert request.correction_round == expected_round
        assert request.allowed_paths == ("tests/test_models.py",)
        assert request.acceptance == ("Repository CI remains green",)
        assert request.canonical_dict()["execution_authority"] is False
        assert request.canonical_dict()["auto_dispatch"] is False
        request_fingerprints.append(request.fingerprint())
        state = mark_correction_implemented(
            state=decision.state,
            request=request,
        )
        assert state.stage is CorrectionStage.REVIEW_PENDING

    exhausted = advance_correction_loop(
        state=state,
        accepted_plan=accepted,
        plan=plan,
        reconciliation=reconciliation,
        contributions=(contribution,),
        policy=policy,
    )
    assert exhausted.state.stage is CorrectionStage.HUMAN_WAIT
    assert (
        exhausted.state.human_wait_reason
        is CorrectionHumanWaitReason.CORRECTION_BUDGET_EXHAUSTED
    )
    assert exhausted.correction_request is None

    print(
        json.dumps(
            {
                "ok": True,
                "bounded_correction_rounds": 2,
                "request_fingerprints": request_fingerprints,
                "scope_rederived_from_accepted_plan": True,
                "reviewer_findings_advisory_only": True,
                "reviewer_execution_authority": False,
                "auto_dispatch": False,
                "budget_exhaustion": "HUMAN_WAIT",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
