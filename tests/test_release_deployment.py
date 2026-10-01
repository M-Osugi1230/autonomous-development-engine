from __future__ import annotations

from dataclasses import replace
import unittest

from ade.release_approval import (
    ReleaseApprovalDecision,
    ReleaseApprovalDisposition,
)
from ade.release_candidate import (
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)
from ade.release_deployment import (
    ReleaseDeploymentAdapterRegistration,
    ReleaseDeploymentError,
    ReleaseDeploymentObservation,
    ReleaseDeploymentStatus,
    TrustedReleaseDeploymentRegistry,
    arm_release_deployment,
    execute_trusted_release_deployment,
    record_release_deployment_dispatch,
    record_release_deployment_observation,
)
from ade.release_policy import plan_release_transition


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "b" * 40


def candidate(environment: ReleaseEnvironment):
    return build_release_candidate(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id="v1.8-release-deployment-001",
        accepted_plan_fingerprint="1" * 64,
        runtime_verification_id=f"rv-{SOURCE_SHA}",
        target_environment=environment,
        evidence_refs=(
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
                path=".autodev/accepted-plan.json",
                fingerprint="1" * 64,
            ),
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.CAMPAIGN,
                path=".autodev/campaign.json",
                fingerprint="2" * 64,
            ),
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
                path=".autodev/runtime-verification/release-001/report.json",
                fingerprint="3" * 64,
            ),
        ),
    )


def transition(environment: ReleaseEnvironment):
    current = {
        ReleaseEnvironment.PREVIEW: None,
        ReleaseEnvironment.STAGING: ReleaseEnvironment.PREVIEW,
        ReleaseEnvironment.PRODUCTION: ReleaseEnvironment.STAGING,
    }[environment]
    return plan_release_transition(
        candidate=candidate(environment),
        current_verified_environment=current,
    )


def approval_for(item):
    return ReleaseApprovalDecision(
        decision_id="release-approval-" + item.fingerprint()[:24],
        transition_id=item.transition_id,
        transition_fingerprint=item.fingerprint(),
        disposition=ReleaseApprovalDisposition.APPROVED,
        selected_option="approve",
    )


class IdempotentFakeDeployer:
    def __init__(self) -> None:
        self.calls = 0
        self.by_key = {}

    def __call__(self, invocation):
        self.calls += 1
        existing = self.by_key.get(invocation.idempotency_key)
        if existing is not None:
            return existing
        observation = ReleaseDeploymentObservation(
            deployment_id="dep-" + invocation.idempotency_key[-16:],
            repository=invocation.repository,
            source_sha=invocation.source_sha,
            environment=invocation.environment,
            idempotency_key=invocation.idempotency_key,
        )
        self.by_key[invocation.idempotency_key] = observation
        return observation


def registry_for(
    deployer,
    *,
    environment: ReleaseEnvironment = ReleaseEnvironment.PREVIEW,
):
    return TrustedReleaseDeploymentRegistry(
        (
            ReleaseDeploymentAdapterRegistration(
                repository=REPOSITORY,
                environment=environment,
                implementation_id=f"fake-{environment.value}-v1",
                deployer=deployer,
            ),
        )
    )


class ReleaseDeploymentTests(unittest.TestCase):
    def test_approved_transition_arms_deterministic_deployment(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        deployer = IdempotentFakeDeployer()
        registry = registry_for(deployer)

        first = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        second = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )

        self.assertEqual(first, second)
        self.assertTrue(first.should_dispatch)
        self.assertEqual(
            first.receipt.status,
            ReleaseDeploymentStatus.ARMED,
        )
        self.assertEqual(first.receipt.dispatch_count, 0)
        self.assertEqual(
            first.invocation.source_sha,
            SOURCE_SHA,
        )
        self.assertEqual(
            first.invocation.environment,
            ReleaseEnvironment.PREVIEW,
        )
        self.assertEqual(
            first.invocation.registry_fingerprint,
            registry.fingerprint(),
        )

    def test_unapproved_transition_cannot_arm(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        waiting = ReleaseApprovalDecision(
            decision_id="release-approval-" + item.fingerprint()[:24],
            transition_id=item.transition_id,
            transition_fingerprint=item.fingerprint(),
            disposition=ReleaseApprovalDisposition.HUMAN_WAIT,
            selected_option=None,
        )
        with self.assertRaisesRegex(
            ReleaseDeploymentError,
            "explicit satisfied release approval",
        ):
            arm_release_deployment(
                transition=item,
                approval=waiting,
                registry=registry_for(IdempotentFakeDeployer()),
            )

    def test_dispatch_is_single_and_rearm_suppresses_duplicate(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        registry = registry_for(IdempotentFakeDeployer())
        activation = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        first = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=activation.receipt,
        )
        second = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=first.receipt,
        )

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(
            second.receipt.status,
            ReleaseDeploymentStatus.DISPATCHED,
        )
        self.assertEqual(second.receipt.dispatch_count, 1)

        resumed = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
            existing_receipt=second.receipt,
        )
        self.assertFalse(resumed.should_dispatch)
        self.assertEqual(resumed.receipt, second.receipt)

    def test_trusted_adapter_is_exact_sha_and_environment_bound(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        deployer = IdempotentFakeDeployer()
        registry = registry_for(deployer)
        activation = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        dispatched = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=activation.receipt,
        ).receipt

        observation = execute_trusted_release_deployment(
            registry=registry,
            invocation=activation.invocation,
            dispatched_receipt=dispatched,
        )
        self.assertEqual(observation.source_sha, SOURCE_SHA)
        self.assertEqual(
            observation.environment,
            ReleaseEnvironment.PREVIEW,
        )
        self.assertEqual(
            observation.idempotency_key,
            activation.invocation.idempotency_key,
        )
        self.assertEqual(deployer.calls, 1)

        completed = record_release_deployment_observation(
            invocation=activation.invocation,
            receipt=dispatched,
            observation=observation,
        )
        self.assertTrue(completed.changed)
        self.assertEqual(
            completed.receipt.status,
            ReleaseDeploymentStatus.DEPLOYED,
        )
        self.assertEqual(completed.receipt.dispatch_count, 1)
        self.assertEqual(
            completed.receipt.deployment_id,
            observation.deployment_id,
        )

        resumed = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
            existing_receipt=completed.receipt,
        )
        self.assertFalse(resumed.should_dispatch)

        replay = record_release_deployment_observation(
            invocation=activation.invocation,
            receipt=completed.receipt,
            observation=observation,
        )
        self.assertFalse(replay.changed)
        self.assertEqual(replay.receipt, completed.receipt)

    def test_idempotency_key_is_stable_for_remote_retry(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        deployer = IdempotentFakeDeployer()
        registry = registry_for(deployer)
        activation = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        dispatched = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=activation.receipt,
        ).receipt

        first = execute_trusted_release_deployment(
            registry=registry,
            invocation=activation.invocation,
            dispatched_receipt=dispatched,
        )
        second = execute_trusted_release_deployment(
            registry=registry,
            invocation=activation.invocation,
            dispatched_receipt=dispatched,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first.idempotency_key,
            activation.invocation.idempotency_key,
        )
        self.assertEqual(len(deployer.by_key), 1)

    def test_adapter_observation_drift_fails_closed(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)

        def drifting(invocation):
            return ReleaseDeploymentObservation(
                deployment_id="dep-drift",
                repository=invocation.repository,
                source_sha="c" * 40,
                environment=invocation.environment,
                idempotency_key=invocation.idempotency_key,
            )

        registry = registry_for(drifting)
        activation = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        dispatched = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=activation.receipt,
        ).receipt

        with self.assertRaisesRegex(
            ReleaseDeploymentError,
            "source SHA drift",
        ):
            execute_trusted_release_deployment(
                registry=registry,
                invocation=activation.invocation,
                dispatched_receipt=dispatched,
            )

    def test_receipt_identity_drift_cannot_be_rearmed(self) -> None:
        item = transition(ReleaseEnvironment.PREVIEW)
        registry = registry_for(IdempotentFakeDeployer())
        activation = arm_release_deployment(
            transition=item,
            approval=approval_for(item),
            registry=registry,
        )
        drifted = replace(
            activation.receipt,
            source_sha="c" * 40,
        )
        with self.assertRaisesRegex(
            ReleaseDeploymentError,
            "identity drift",
        ):
            arm_release_deployment(
                transition=item,
                approval=approval_for(item),
                registry=registry,
                existing_receipt=drifted,
            )

    def test_registry_is_controller_owned_and_environment_specific(self) -> None:
        deployer = IdempotentFakeDeployer()
        registry = registry_for(deployer)
        payload = registry.canonical_dict()
        self.assertFalse(payload["provider_defined"])
        self.assertTrue(
            payload["registrations"][0]["controller_owned"]
        )
        self.assertTrue(
            payload["registrations"][0]["idempotency_required"]
        )
        with self.assertRaisesRegex(
            ReleaseDeploymentError,
            "no trusted deployment adapter",
        ):
            registry.resolve(
                REPOSITORY,
                ReleaseEnvironment.PRODUCTION,
            )


if __name__ == "__main__":
    unittest.main()
