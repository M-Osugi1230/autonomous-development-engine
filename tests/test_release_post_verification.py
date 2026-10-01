from __future__ import annotations

from datetime import UTC, datetime
import unittest

from ade.release_candidate import ReleaseEnvironment
from ade.release_deployment import (
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
)
from ade.release_post_verification import (
    ReleasePostVerificationDisposition,
    ReleasePostVerificationError,
    arm_release_post_verification,
    build_release_post_verification_binding,
    evaluate_release_post_verification,
    finalize_release_post_verification,
)
from ade.runtime_probe_registry import (
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_target_registry import (
    RuntimeTargetKind,
    RuntimeTargetObservation,
    RuntimeTargetRegistration,
    RuntimeTargetSpec,
    TrustedRuntimeTargetRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import (
    RuntimeVerificationPolicy,
    record_runtime_verification_dispatch,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "c" * 40
NOW = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)


def deployment_receipt(
    *,
    status: ReleaseDeploymentStatus = ReleaseDeploymentStatus.DEPLOYED,
    deployment_id: str | None = "dep-preview-001",
) -> ReleaseDeploymentReceipt:
    return ReleaseDeploymentReceipt(
        deployment_request_id="deployment-release-proof-001",
        idempotency_key="ade-release-proof-001",
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        environment=ReleaseEnvironment.PREVIEW,
        transition_id="promotion-release-proof-001",
        transition_fingerprint="1" * 64,
        approval_fingerprint="2" * 64,
        adapter_implementation_id="trusted-preview-adapter-v1",
        registry_fingerprint="3" * 64,
        status=status,
        dispatch_count=1 if status is not ReleaseDeploymentStatus.ARMED else 0,
        deployment_id=deployment_id if status is ReleaseDeploymentStatus.DEPLOYED else None,
        observation_fingerprint=(
            "4" * 64 if status is ReleaseDeploymentStatus.DEPLOYED else None
        ),
    )


def target_resolution(binding, *, deployment_id: str = "dep-preview-001"):
    def observer(_):
        return RuntimeTargetObservation(
            source_sha=SOURCE_SHA,
            observed_at=NOW,
            deployment_id=deployment_id,
        )

    registry = TrustedRuntimeTargetRegistry(
        (
            RuntimeTargetRegistration(
                target_repository=REPOSITORY,
                spec=RuntimeTargetSpec(
                    target_id="preview-runtime",
                    environment="preview",
                    kind=RuntimeTargetKind.PREVIEW,
                    max_age_seconds=300,
                    max_future_skew_seconds=30,
                ),
                implementation_id="trusted-preview-runtime-v1",
                observer=observer,
            ),
        )
    )
    return registry.resolve(binding.runtime_contract, now=NOW)


class ReleasePostVerificationTests(unittest.TestCase):
    def test_deployed_receipt_builds_deterministic_exact_binding(self) -> None:
        receipt = deployment_receipt()
        first = build_release_post_verification_binding(
            deployment_receipt=receipt,
            required_probe_ids=("preview-health", "preview-import"),
            max_attempts=2,
            timeout_seconds=60,
        )
        second = build_release_post_verification_binding(
            deployment_receipt=receipt,
            required_probe_ids=("preview-import", "preview-health"),
            max_attempts=2,
            timeout_seconds=60,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.deployment_id, "dep-preview-001")
        self.assertEqual(first.repository, REPOSITORY)
        self.assertEqual(first.source_sha, SOURCE_SHA)
        self.assertEqual(first.environment, ReleaseEnvironment.PREVIEW)
        self.assertEqual(
            first.runtime_contract.environment,
            ReleaseEnvironment.PREVIEW.value,
        )
        self.assertEqual(
            first.runtime_contract.source_sha,
            SOURCE_SHA,
        )
        self.assertTrue(
            first.canonical_dict()["deployment_identity_required"]
        )
        self.assertTrue(
            first.canonical_dict()["ci_success_is_not_runtime_success"]
        )

    def test_non_deployed_receipt_cannot_start_post_verification(self) -> None:
        with self.assertRaisesRegex(
            ReleasePostVerificationError,
            "requires DEPLOYED receipt",
        ):
            build_release_post_verification_binding(
                deployment_receipt=deployment_receipt(
                    status=ReleaseDeploymentStatus.DISPATCHED,
                    deployment_id=None,
                ),
                required_probe_ids=("preview-health",),
            )

    def test_verified_report_completes_only_exact_deployment(self) -> None:
        binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
        )
        target = target_resolution(binding)
        report = evaluate_runtime_verification(
            binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SOURCE_SHA,
                ),
            ),
        )
        outcome = evaluate_release_post_verification(
            binding=binding,
            target=target,
            report=report,
        )

        self.assertEqual(
            outcome.disposition,
            ReleasePostVerificationDisposition.VERIFIED,
        )
        self.assertTrue(outcome.promotion_verified)
        self.assertIsNone(outcome.next_required_human_action)
        self.assertIsNone(outcome.failure_fingerprint)
        self.assertFalse(outcome.canonical_dict()["rollback_authority"])
        self.assertFalse(
            outcome.canonical_dict()["auto_promote_next_environment"]
        )

    def test_pending_report_remains_pending_without_promoting(self) -> None:
        binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
        )
        target = target_resolution(binding)
        report = evaluate_runtime_verification(
            binding.runtime_contract,
            (),
        )
        outcome = evaluate_release_post_verification(
            binding=binding,
            target=target,
            report=report,
        )

        self.assertEqual(
            outcome.disposition,
            ReleasePostVerificationDisposition.PENDING,
        )
        self.assertFalse(outcome.promotion_verified)
        self.assertIsNone(outcome.failure_fingerprint)

    def test_failed_runtime_verification_enters_human_wait(self) -> None:
        binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
        )
        target = target_resolution(binding)
        report = evaluate_runtime_verification(
            binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.FAIL,
                    source_sha=SOURCE_SHA,
                    detail_code="health-check-failed",
                ),
            ),
        )
        outcome = evaluate_release_post_verification(
            binding=binding,
            target=target,
            report=report,
        )

        self.assertEqual(
            outcome.disposition,
            ReleasePostVerificationDisposition.HUMAN_WAIT,
        )
        self.assertFalse(outcome.promotion_verified)
        self.assertEqual(
            outcome.next_required_human_action,
            "review-release-runtime-verification-failure",
        )
        self.assertEqual(outcome.failure_fingerprint, report.fingerprint())

    def test_target_deployment_identity_must_match_completed_deployment(self) -> None:
        binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
        )
        target = target_resolution(
            binding,
            deployment_id="dep-preview-other",
        )
        report = evaluate_runtime_verification(
            binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SOURCE_SHA,
                ),
            ),
        )
        with self.assertRaisesRegex(
            ReleasePostVerificationError,
            "deployment_id does not match completed deployment",
        ):
            evaluate_release_post_verification(
                binding=binding,
                target=target,
                report=report,
            )

    def test_runtime_report_must_match_exact_contract(self) -> None:
        binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
        )
        target = target_resolution(binding)
        other_binding = build_release_post_verification_binding(
            deployment_receipt=deployment_receipt(),
            required_probe_ids=("preview-health",),
            timeout_seconds=301,
        )
        drifted_report = evaluate_runtime_verification(
            other_binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SOURCE_SHA,
                ),
            ),
        )
        with self.assertRaisesRegex(
            ReleasePostVerificationError,
            "verification_id drift|contract fingerprint drift",
        ):
            evaluate_release_post_verification(
                binding=binding,
                target=target,
                report=drifted_report,
            )


    def test_durable_runtime_receipt_verifies_exact_deployment(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            (
                RuntimeProbeRegistration(
                    probe_id="preview-health",
                    implementation_id="preview-health-v1",
                    runner=lambda invocation: RuntimeProbeObservation(
                        status=RuntimeProbeStatus.PASS,
                    ),
                ),
            )
        )
        policy = RuntimeVerificationPolicy(
            target_repository=REPOSITORY,
            environment="preview",
            required_probe_ids=("preview-health",),
            max_attempts=1,
            timeout_seconds=60,
        )
        activation = arm_release_post_verification(
            deployment_receipt=deployment_receipt(),
            policy=policy,
            registry=registry,
            task_id="task-final",
        )
        self.assertTrue(activation.should_dispatch)
        dispatched = record_runtime_verification_dispatch(
            contract=activation.binding.runtime_contract,
            registry=registry,
            receipt=activation.receipt,
        ).receipt
        self.assertEqual(dispatched.status, "DISPATCHED")
        self.assertEqual(dispatched.dispatch_count, 1)

        resumed = arm_release_post_verification(
            deployment_receipt=deployment_receipt(),
            policy=policy,
            registry=registry,
            task_id="task-final",
            existing_receipt=dispatched,
        )
        self.assertFalse(resumed.should_dispatch)

        target = target_resolution(activation.binding)
        report = evaluate_runtime_verification(
            activation.binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SOURCE_SHA,
                ),
            ),
        )
        finalization = finalize_release_post_verification(
            activation=activation,
            target=target,
            dispatched_receipt=dispatched,
            report=report,
            state_payload={
                "status": "READY",
                "current_task_id": None,
                "metadata": {"target_repository": REPOSITORY},
            },
            campaign_payload={
                "campaign_id": "campaign-release-proof",
                "goal": "ship verified release",
                "task_ids": ["task-final"],
                "completed_task_ids": ["task-final"],
                "status": "COMPLETED",
            },
        )
        self.assertTrue(finalization.promotion_verified)
        self.assertTrue(finalization.next_environment_allowed)
        self.assertEqual(finalization.receipt.status, "VERIFIED")
        self.assertIsNone(finalization.recovery)

    def test_failed_runtime_receipt_reopens_campaign_to_human_wait(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            (
                RuntimeProbeRegistration(
                    probe_id="preview-health",
                    implementation_id="preview-health-v1",
                    runner=lambda invocation: RuntimeProbeObservation(
                        status=RuntimeProbeStatus.FAIL,
                        detail_code="health-check-failed",
                    ),
                ),
            )
        )
        policy = RuntimeVerificationPolicy(
            target_repository=REPOSITORY,
            environment="preview",
            required_probe_ids=("preview-health",),
            max_attempts=1,
            timeout_seconds=60,
        )
        activation = arm_release_post_verification(
            deployment_receipt=deployment_receipt(),
            policy=policy,
            registry=registry,
            task_id="task-final",
        )
        dispatched = record_runtime_verification_dispatch(
            contract=activation.binding.runtime_contract,
            registry=registry,
            receipt=activation.receipt,
        ).receipt
        target = target_resolution(activation.binding)
        report = evaluate_runtime_verification(
            activation.binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.FAIL,
                    source_sha=SOURCE_SHA,
                    detail_code="health-check-failed",
                ),
            ),
        )
        finalization = finalize_release_post_verification(
            activation=activation,
            target=target,
            dispatched_receipt=dispatched,
            report=report,
            state_payload={
                "status": "READY",
                "current_task_id": None,
                "metadata": {"target_repository": REPOSITORY},
            },
            campaign_payload={
                "campaign_id": "campaign-release-proof",
                "goal": "ship verified release",
                "task_ids": ["task-final"],
                "completed_task_ids": ["task-final"],
                "status": "COMPLETED",
            },
        )
        self.assertFalse(finalization.promotion_verified)
        self.assertFalse(finalization.next_environment_allowed)
        self.assertEqual(finalization.receipt.status, "HUMAN_WAIT")
        self.assertEqual(finalization.state["status"], "HUMAN_WAIT")
        self.assertEqual(finalization.campaign["status"], "HUMAN_WAIT")
        self.assertEqual(
            finalization.state["metadata"]["next_required_human_action"],
            "review-release-runtime-verification-failure",
        )
        self.assertIsNone(
            finalization.state["metadata"]["next_system_action"]
        )
        self.assertFalse(
            finalization.state["metadata"]["automatic_rollback"]
        )
        self.assertFalse(
            finalization.state["metadata"]["auto_promote_next_environment"]
        )
        self.assertIsNotNone(finalization.recovery)
        self.assertEqual(
            finalization.recovery.action.value,
            "HUMAN_WAIT",
        )

    def test_finalization_requires_exact_completed_campaign_final_task(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            (
                RuntimeProbeRegistration(
                    probe_id="preview-health",
                    implementation_id="preview-health-v1",
                    runner=lambda invocation: RuntimeProbeObservation(
                        status=RuntimeProbeStatus.PASS,
                    ),
                ),
            )
        )
        policy = RuntimeVerificationPolicy(
            target_repository=REPOSITORY,
            environment="preview",
            required_probe_ids=("preview-health",),
            max_attempts=1,
            timeout_seconds=60,
        )
        activation = arm_release_post_verification(
            deployment_receipt=deployment_receipt(),
            policy=policy,
            registry=registry,
            task_id="task-final",
        )
        dispatched = record_runtime_verification_dispatch(
            contract=activation.binding.runtime_contract,
            registry=registry,
            receipt=activation.receipt,
        ).receipt
        target = target_resolution(activation.binding)
        report = evaluate_runtime_verification(
            activation.binding.runtime_contract,
            (
                RuntimeProbeResult(
                    probe_id="preview-health",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SOURCE_SHA,
                ),
            ),
        )
        with self.assertRaisesRegex(
            ReleasePostVerificationError,
            "exact completed Campaign final task",
        ):
            finalize_release_post_verification(
                activation=activation,
                target=target,
                dispatched_receipt=dispatched,
                report=report,
                state_payload={
                    "status": "READY",
                    "metadata": {"target_repository": REPOSITORY},
                },
                campaign_payload={
                    "campaign_id": "campaign-release-proof",
                    "goal": "ship verified release",
                    "task_ids": ["task-final", "task-later"],
                    "completed_task_ids": ["task-final", "task-later"],
                    "status": "COMPLETED",
                },
            )


if __name__ == "__main__":
    unittest.main()
