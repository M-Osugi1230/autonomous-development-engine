from __future__ import annotations

import json

from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan


def main() -> int:
    repository = "M-Osugi1230/one-minute-thought-experiments"
    source_sha = "a" * 40
    accepted_plan_fingerprint = "b" * 64
    evidence_fingerprint = "c" * 64

    implementer = AgentAssignment(
        assignment_id="agent-implementer",
        role=AgentRole.IMPLEMENTER,
        provider_id="jules",
        repository=repository,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted_plan_fingerprint,
        objective="Implement the exact accepted task without expanding scope.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=(evidence_fingerprint,),
    )
    reviewer = AgentAssignment(
        assignment_id="agent-reviewer",
        role=AgentRole.REVIEWER,
        provider_id="github-copilot",
        repository=repository,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted_plan_fingerprint,
        objective="Review the bounded implementation against trusted evidence.",
        evidence_paths=(".autodev/accepted-plan.json",),
        evidence_fingerprints=(evidence_fingerprint,),
    )
    plan = MultiAgentPlan(
        plan_id="multi-agent-plan-001",
        repository=repository,
        source_sha=source_sha,
        campaign_id="campaign-001",
        task_id="task-001",
        accepted_plan_fingerprint=accepted_plan_fingerprint,
        assignments=(reviewer, implementer),
    )
    restored = MultiAgentPlan.from_dict(plan.canonical_dict())
    assert restored.fingerprint() == plan.fingerprint()
    assert restored.provider_ids == ("github-copilot", "jules")
    payload = restored.canonical_dict()
    assert payload["execution_authority"] is False
    assert payload["auto_dispatch"] is False
    assert payload["merge_authority"] is False
    assert payload["acceptance_authority"] is False
    assert payload["may_expand_scope"] is False

    print(
        json.dumps(
            {
                "ok": True,
                "roles": [item.role.value for item in restored.assignments],
                "providers": list(restored.provider_ids),
                "exact_accepted_plan_binding": True,
                "deterministic_fingerprint": restored.fingerprint(),
                "execution_authority": False,
                "auto_dispatch": False,
                "merge_authority": False,
                "acceptance_authority": False,
                "may_expand_scope": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
