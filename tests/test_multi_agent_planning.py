from __future__ import annotations

import unittest

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentRole
from ade.multi_agent_planning import (
    MultiAgentDerivationPolicy,
    MultiAgentPlanningError,
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
    def __init__(self) -> None:
        self.create_calls = 0

    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        self.create_calls += 1
        raise AssertionError("plan derivation must not create provider sessions")

    def get_session(self, session_id):
        raise AssertionError("plan derivation must not read provider sessions")

    def list_activities(self, session_id):
        raise AssertionError("plan derivation must not read provider activities")

    def send_message(self, session_id, prompt):
        raise AssertionError("plan derivation must not steer provider sessions")

    def approve_plan(self, session_id):
        raise AssertionError("plan derivation must not approve provider plans")


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
EVIDENCE_A = "b" * 64
EVIDENCE_B = "c" * 64


def accepted_plan(status: str = "ACCEPTED") -> AcceptedPlan:
    plan = DevelopmentPlan(
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
        human_boundaries=(
            "destructive or irreversible operation",
        ),
    )
    return AcceptedPlan(
        plan=plan,
        fingerprint=plan.fingerprint(),
        status=status,
    )


def registry():
    primary = FakeProvider()
    fallback = FakeProvider()
    reviewer = FakeProvider()
    pairs = (
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
            primary,
        ),
        (
            ProviderDescriptor(
                provider_id="github-copilot",
                display_name="GitHub Copilot",
                capabilities=(
                    ProviderCapability.GITHUB_SOURCE,
                    ProviderCapability.AUTO_CREATE_PR,
                    ProviderCapability.HOSTED_EXECUTION,
                ),
                priority=20,
            ),
            fallback,
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
    return ProviderRegistry.from_pairs(pairs), (primary, fallback, reviewer)


def policy() -> MultiAgentDerivationPolicy:
    return MultiAgentDerivationPolicy(
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
            preferred_provider_ids=("reviewer-agent", "github-copilot"),
        ),
        reviewer_required=True,
        prefer_distinct_reviewer=True,
    )


def derive(
    availability,
    *,
    accepted: AcceptedPlan | None = None,
    trusted_registry: ProviderRegistry | None = None,
):
    trusted_registry = trusted_registry or registry()[0]
    return derive_multi_agent_plan(
        accepted_plan=accepted or accepted_plan(),
        repository=REPO,
        source_sha=SHA,
        campaign_id="campaign-001",
        task_id="task-001",
        registry=trusted_registry,
        availability=availability,
        accepted_plan_path=".autodev/accepted-plan.json",
        accepted_plan_evidence_fingerprint=EVIDENCE_A,
        provider_availability_path=".autodev/runtime/provider-availability.json",
        provider_availability_evidence_fingerprint=EVIDENCE_B,
        policy=policy(),
    )


class MultiAgentPlanningTests(unittest.TestCase):
    def test_derives_implementer_and_distinct_reviewer_without_sessions(self):
        trusted_registry, providers = registry()
        plan = derive(
            (
                ProviderAvailabilitySnapshot(
                    "jules",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "github-copilot",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "reviewer-agent",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
            trusted_registry=trusted_registry,
        )
        by_role = {item.role: item for item in plan.assignments}
        self.assertEqual(
            by_role[AgentRole.IMPLEMENTER].provider_id,
            "jules",
        )
        self.assertEqual(
            by_role[AgentRole.REVIEWER].provider_id,
            "reviewer-agent",
        )
        self.assertEqual(
            plan.accepted_plan_fingerprint,
            accepted_plan().fingerprint,
        )
        self.assertTrue(
            all(
                ".autodev/accepted-plan.json" in item.evidence_paths
                for item in plan.assignments
            )
        )
        self.assertEqual(
            [provider.create_calls for provider in providers],
            [0, 0, 0],
        )

    def test_distinct_reviewer_preference_falls_back_to_same_provider(self):
        trusted_registry, _ = registry()
        plan = derive(
            (
                ProviderAvailabilitySnapshot(
                    "jules",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "github-copilot",
                    ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                    reason="temporary",
                ),
                ProviderAvailabilitySnapshot(
                    "reviewer-agent",
                    ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                    reason="temporary",
                ),
            ),
            trusted_registry=trusted_registry,
        )
        by_role = {item.role: item for item in plan.assignments}
        self.assertEqual(
            by_role[AgentRole.IMPLEMENTER].provider_id,
            "jules",
        )
        self.assertEqual(
            by_role[AgentRole.REVIEWER].provider_id,
            "jules",
        )

    def test_no_implementer_fails_closed(self):
        trusted_registry, _ = registry()
        with self.assertRaisesRegex(MultiAgentPlanningError, "IMPLEMENTER"):
            derive(
                (
                    ProviderAvailabilitySnapshot(
                        "jules",
                        ProviderAvailability.QUOTA_PAUSED,
                        reason="quota",
                    ),
                    ProviderAvailabilitySnapshot(
                        "github-copilot",
                        ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                        reason="temporary",
                    ),
                    ProviderAvailabilitySnapshot(
                        "reviewer-agent",
                        ProviderAvailability.AVAILABLE,
                    ),
                ),
                trusted_registry=trusted_registry,
            )

    def test_nonaccepted_plan_fails_closed(self):
        with self.assertRaisesRegex(MultiAgentPlanningError, "ACCEPTED"):
            derive(
                (),
                accepted=accepted_plan(status="RUNNING"),
            )

    def test_unknown_task_fails_closed(self):
        trusted_registry, _ = registry()
        with self.assertRaisesRegex(MultiAgentPlanningError, "task_id"):
            derive_multi_agent_plan(
                accepted_plan=accepted_plan(),
                repository=REPO,
                source_sha=SHA,
                campaign_id="campaign-001",
                task_id="missing-task",
                registry=trusted_registry,
                availability=(),
                accepted_plan_path=".autodev/accepted-plan.json",
                accepted_plan_evidence_fingerprint=EVIDENCE_A,
                provider_availability_path=".autodev/runtime/provider-availability.json",
                provider_availability_evidence_fingerprint=EVIDENCE_B,
                policy=policy(),
            )

    def test_derivation_is_deterministic(self):
        trusted_registry, _ = registry()
        availability = (
            ProviderAvailabilitySnapshot(
                "jules",
                ProviderAvailability.AVAILABLE,
            ),
            ProviderAvailabilitySnapshot(
                "reviewer-agent",
                ProviderAvailability.AVAILABLE,
            ),
            ProviderAvailabilitySnapshot(
                "github-copilot",
                ProviderAvailability.AVAILABLE,
            ),
        )
        left = derive(
            availability,
            trusted_registry=trusted_registry,
        )
        right = derive(
            tuple(reversed(availability)),
            trusted_registry=trusted_registry,
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())

    def test_policy_is_authority_free(self):
        payload = policy().canonical_dict()
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["merge_authority"])
        self.assertFalse(payload["acceptance_authority"])
        self.assertFalse(payload["may_expand_scope"])


if __name__ == "__main__":
    unittest.main()
