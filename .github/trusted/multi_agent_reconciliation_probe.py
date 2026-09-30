from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ade.decision_store import DecisionStore
from ade.human_interrupt import HumanInterruptCoordinator
from ade.interrupt_policy import (
    DecisionKind,
    InterruptDisposition,
)
from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_reconciliation import (
    ReconciliationDisposition,
    ReconciliationReason,
    build_reconciliation_decision_request,
    reconcile_agent_contributions,
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


def contribution(
    plan: MultiAgentPlan,
    role: AgentRole,
    verdict: ContributionVerdict,
    fingerprint_char: str,
):
    assignee = next(item for item in plan.assignments if item.role is role)
    return build_agent_contribution(
        plan=plan,
        assignment_id=assignee.assignment_id,
        verdict=verdict,
        summary=f"Bounded {role.value.lower()} finding is {verdict.value.lower()}.",
        evidence_paths=(
            f".autodev/multi-agent/{role.value.lower()}.json",
        ),
        evidence_fingerprints=(fingerprint_char * 64,),
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
    review = contribution(
        plan,
        AgentRole.REVIEWER,
        ContributionVerdict.CLEAR,
        "d",
    )
    diagnostic = contribution(
        plan,
        AgentRole.DIAGNOSTIC,
        ContributionVerdict.CHANGES_REQUIRED,
        "e",
    )

    result = reconcile_agent_contributions(
        plan=plan,
        contributions=(review, diagnostic),
    )
    assert result.disposition is ReconciliationDisposition.HUMAN_WAIT
    assert result.reason is ReconciliationReason.MATERIAL_DISAGREEMENT
    assert result.canonical_dict()["majority_voting"] is False
    request = build_reconciliation_decision_request(result)

    with tempfile.TemporaryDirectory() as temp_dir:
        store = DecisionStore(Path(temp_dir) / "decisions.json")
        coordinator = HumanInterruptCoordinator(store)
        disposition = coordinator.request_decision(
            DecisionKind.SPECIFICATION_AMBIGUITY,
            request,
        )
        assert disposition is InterruptDisposition.HUMAN_WAIT
        open_records = store.list_open()
        assert len(open_records) == 1
        assert open_records[0].decision_id == request.decision_id

    print(
        json.dumps(
            {
                "ok": True,
                "reconciliation": result.disposition.value,
                "reason": result.reason.value,
                "majority_voting": False,
                "human_interrupt": "HUMAN_WAIT",
                "decision_id": request.decision_id,
                "merge_authority": False,
                "acceptance_authority": False,
                "runtime_verification_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
