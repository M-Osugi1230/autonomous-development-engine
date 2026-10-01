from __future__ import annotations

from datetime import UTC, datetime

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


def main() -> None:
    repository = "M-Osugi1230/one-minute-thought-experiments"
    source_sha = "c" * 40
    deployment_id = "dep-preview-proof-001"
    now = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)

    deployment = ReleaseDeploymentReceipt(
        deployment_request_id="deployment-release-post-rv-001",
        idempotency_key="ade-release-post-rv-001",
        repository=repository,
        source_sha=source_sha,
        environment=ReleaseEnvironment.PREVIEW,
        transition_id="promotion-release-post-rv-001",
        transition_fingerprint="1" * 64,
        approval_fingerprint="2" * 64,
        adapter_implementation_id="trusted-preview-adapter-v1",
        registry_fingerprint="3" * 64,
        status=ReleaseDeploymentStatus.DEPLOYED,
        dispatch_count=1,
        deployment_id=deployment_id,
        observation_fingerprint="4" * 64,
    )
    binding = build_release_post_verification_binding(
        deployment_receipt=deployment,
        required_probe_ids=("preview-health",),
        timeout_seconds=60,
    )

    def observer(_):
        return RuntimeTargetObservation(
            source_sha=source_sha,
            observed_at=now,
            deployment_id=deployment_id,
        )

    target_registry = TrustedRuntimeTargetRegistry(
        (
            RuntimeTargetRegistration(
                target_repository=repository,
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
    target = target_registry.resolve(binding.runtime_contract, now=now)

    verified_report = evaluate_runtime_verification(
        binding.runtime_contract,
        (
            RuntimeProbeResult(
                probe_id="preview-health",
                status=RuntimeProbeStatus.PASS,
                source_sha=source_sha,
            ),
        ),
    )
    verified = evaluate_release_post_verification(
        binding=binding,
        target=target,
        report=verified_report,
    )
    assert verified.disposition is ReleasePostVerificationDisposition.VERIFIED
    assert verified.promotion_verified is True
    assert verified.deployment_id == deployment_id

    failed_report = evaluate_runtime_verification(
        binding.runtime_contract,
        (
            RuntimeProbeResult(
                probe_id="preview-health",
                status=RuntimeProbeStatus.FAIL,
                source_sha=source_sha,
                detail_code="health-check-failed",
            ),
        ),
    )
    contained = evaluate_release_post_verification(
        binding=binding,
        target=target,
        report=failed_report,
    )
    assert contained.disposition is ReleasePostVerificationDisposition.HUMAN_WAIT
    assert contained.promotion_verified is False
    assert (
        contained.next_required_human_action
        == "review-release-runtime-verification-failure"
    )
    assert contained.canonical_dict()["rollback_authority"] is False
    assert (
        contained.canonical_dict()["auto_promote_next_environment"]
        is False
    )

    probe_registry = TrustedRuntimeProbeRegistry(
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
        target_repository=repository,
        environment="preview",
        required_probe_ids=("preview-health",),
        max_attempts=1,
        timeout_seconds=60,
    )
    activation = arm_release_post_verification(
        deployment_receipt=deployment,
        policy=policy,
        registry=probe_registry,
        task_id="task-final",
    )
    assert activation.should_dispatch is True
    dispatched = record_runtime_verification_dispatch(
        contract=activation.binding.runtime_contract,
        registry=probe_registry,
        receipt=activation.receipt,
    ).receipt
    assert dispatched.status == "DISPATCHED"
    assert dispatched.dispatch_count == 1

    resumed = arm_release_post_verification(
        deployment_receipt=deployment,
        policy=policy,
        registry=probe_registry,
        task_id="task-final",
        existing_receipt=dispatched,
    )
    assert resumed.should_dispatch is False

    durable_target = target_registry.resolve(
        activation.binding.runtime_contract,
        now=now,
    )
    durable_verified_report = evaluate_runtime_verification(
        activation.binding.runtime_contract,
        (
            RuntimeProbeResult(
                probe_id="preview-health",
                status=RuntimeProbeStatus.PASS,
                source_sha=source_sha,
            ),
        ),
    )
    durable_verified = finalize_release_post_verification(
        activation=activation,
        target=durable_target,
        dispatched_receipt=dispatched,
        report=durable_verified_report,
        state_payload={
            "status": "READY",
            "current_task_id": None,
            "metadata": {"target_repository": repository},
        },
        campaign_payload={
            "campaign_id": "release-campaign-proof",
            "goal": "ship verified release",
            "task_ids": ["task-final"],
            "completed_task_ids": ["task-final"],
            "status": "COMPLETED",
        },
    )
    assert durable_verified.receipt.status == "VERIFIED"
    assert durable_verified.next_environment_allowed is True

    durable_failed_report = evaluate_runtime_verification(
        activation.binding.runtime_contract,
        (
            RuntimeProbeResult(
                probe_id="preview-health",
                status=RuntimeProbeStatus.FAIL,
                source_sha=source_sha,
                detail_code="health-check-failed",
            ),
        ),
    )
    durable_failed = finalize_release_post_verification(
        activation=activation,
        target=durable_target,
        dispatched_receipt=dispatched,
        report=durable_failed_report,
        state_payload={
            "status": "READY",
            "current_task_id": None,
            "metadata": {"target_repository": repository},
        },
        campaign_payload={
            "campaign_id": "release-campaign-proof",
            "goal": "ship verified release",
            "task_ids": ["task-final"],
            "completed_task_ids": ["task-final"],
            "status": "COMPLETED",
        },
    )
    assert durable_failed.receipt.status == "HUMAN_WAIT"
    assert durable_failed.state["status"] == "HUMAN_WAIT"
    assert durable_failed.campaign["status"] == "HUMAN_WAIT"
    assert durable_failed.next_environment_allowed is False
    assert (
        durable_failed.state["metadata"]["next_required_human_action"]
        == "review-release-runtime-verification-failure"
    )
    assert durable_failed.state["metadata"]["automatic_rollback"] is False

    def wrong_observer(_):
        return RuntimeTargetObservation(
            source_sha=source_sha,
            observed_at=now,
            deployment_id="dep-preview-other",
        )

    wrong_registry = TrustedRuntimeTargetRegistry(
        (
            RuntimeTargetRegistration(
                target_repository=repository,
                spec=RuntimeTargetSpec(
                    target_id="preview-runtime",
                    environment="preview",
                    kind=RuntimeTargetKind.PREVIEW,
                    max_age_seconds=300,
                    max_future_skew_seconds=30,
                ),
                implementation_id="trusted-preview-runtime-v1",
                observer=wrong_observer,
            ),
        )
    )
    wrong_target = wrong_registry.resolve(
        binding.runtime_contract,
        now=now,
    )
    try:
        evaluate_release_post_verification(
            binding=binding,
            target=wrong_target,
            report=verified_report,
        )
    except ReleasePostVerificationError:
        pass
    else:
        raise AssertionError(
            "different deployment identity must fail closed"
        )

    print(
        {
            "schema_version": 1,
            "proof": "v1.8-post-promotion-runtime-verification",
            "deployment_id": deployment_id,
            "binding_fingerprint": binding.fingerprint(),
            "verified_outcome_fingerprint": verified.fingerprint(),
            "failure_outcome_fingerprint": contained.fingerprint(),
            "verified": verified.promotion_verified,
            "failure_disposition": contained.disposition.value,
            "exact_deployment_identity_required": True,
            "auto_promote_next_environment": False,
            "durable_runtime_receipt_verified": (
                durable_verified.receipt.status == "VERIFIED"
            ),
            "failure_reopens_campaign_human_wait": (
                durable_failed.campaign["status"] == "HUMAN_WAIT"
            ),
            "automatic_rollback": False,
        }
    )


if __name__ == "__main__":
    main()
