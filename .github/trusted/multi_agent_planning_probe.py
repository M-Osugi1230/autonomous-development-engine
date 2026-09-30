from __future__ import annotations

import json

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentRole
from ade.multi_agent_planning import (
    MultiAgentDerivationPolicy,
    derive_multi_agent_plan,
)
from ade.provider_registry import ProviderRegistry
from ade.provider_router import (
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
)
from ade.provider_routing import (
    ProviderCapability,
    ProviderDescriptor,
    RoutingRequest,
)


class FakeProvider:
    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        raise AssertionError("trusted derivation cannot create sessions")

    def get_session(self, session_id):
        raise AssertionError("trusted derivation cannot read sessions")

    def list_activities(self, session_id):
        raise AssertionError("trusted derivation cannot read activities")

    def send_message(self, session_id, prompt):
        raise AssertionError("trusted derivation cannot steer sessions")

    def approve_plan(self, session_id):
        raise AssertionError("trusted derivation cannot approve plans")


def main() -> int:
    task = PlannedTask(
        task_id="task-001",
        title="Add bounded regression test",
        prompt="Add only the accepted bounded regression test.",
        depends_on=(),
        allowed_paths=("tests/test_models.py",),
        acceptance=("Repository CI remains green",),
    )
    development_plan = DevelopmentPlan(
        goal="Add one bounded regression test.",
        tasks=(task,),
    )
    accepted = AcceptedPlan.accept(development_plan)

    provider = FakeProvider()
    reviewer = FakeProvider()
    registry = ProviderRegistry.from_pairs(
        (
            (
                ProviderDescriptor(
                    provider_id="jules",
                    display_name="Jules",
                    capabilities=(
                        ProviderCapability.GITHUB_SOURCE,
                        ProviderCapability.AUTO_CREATE_PR,
                        ProviderCapability.HOSTED_EXECUTION,
                    ),
                    priority=10,
                ),
                provider,
            ),
            (
                ProviderDescriptor(
                    provider_id="reviewer-agent",
                    display_name="Reviewer Agent",
                    capabilities=(
                        ProviderCapability.GITHUB_SOURCE,
                        ProviderCapability.HOSTED_EXECUTION,
                    ),
                    priority=5,
                ),
                reviewer,
            ),
        )
    )
    policy = MultiAgentDerivationPolicy(
        implementer_request=RoutingRequest(
            required_capabilities=(
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.AUTO_CREATE_PR,
                ProviderCapability.HOSTED_EXECUTION,
            ),
            preferred_provider_ids=("jules",),
        ),
        reviewer_request=RoutingRequest(
            required_capabilities=(
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.HOSTED_EXECUTION,
            ),
            preferred_provider_ids=("reviewer-agent",),
        ),
    )
    plan = derive_multi_agent_plan(
        accepted_plan=accepted,
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="a" * 40,
        campaign_id="campaign-001",
        task_id="task-001",
        registry=registry,
        availability=(
            ProviderAvailabilitySnapshot(
                "jules",
                ProviderAvailability.AVAILABLE,
            ),
            ProviderAvailabilitySnapshot(
                "reviewer-agent",
                ProviderAvailability.AVAILABLE,
            ),
        ),
        accepted_plan_path=".autodev/accepted-plan.json",
        accepted_plan_evidence_fingerprint="b" * 64,
        provider_availability_path=".autodev/runtime/provider-availability.json",
        provider_availability_evidence_fingerprint="c" * 64,
        policy=policy,
    )
    by_role = {item.role: item.provider_id for item in plan.assignments}
    assert by_role == {
        AgentRole.IMPLEMENTER: "jules",
        AgentRole.REVIEWER: "reviewer-agent",
    }
    payload = plan.canonical_dict()
    assert payload["execution_authority"] is False
    assert payload["auto_dispatch"] is False
    assert payload["merge_authority"] is False
    assert payload["acceptance_authority"] is False
    assert payload["may_expand_scope"] is False

    print(
        json.dumps(
            {
                "ok": True,
                "accepted_plan_bound": True,
                "task_scope_source": "AcceptedPlan",
                "implementer": by_role[AgentRole.IMPLEMENTER],
                "reviewer": by_role[AgentRole.REVIEWER],
                "distinct_reviewer_preferred": True,
                "provider_sessions_created": False,
                "execution_authority": False,
                "auto_dispatch": False,
                "merge_authority": False,
                "acceptance_authority": False,
                "may_expand_scope": False,
                "plan_fingerprint": plan.fingerprint(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
