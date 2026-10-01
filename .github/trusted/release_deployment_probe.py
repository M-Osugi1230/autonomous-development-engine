from __future__ import annotations

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
    ReleaseDeploymentObservation,
    ReleaseDeploymentStatus,
    TrustedReleaseDeploymentRegistry,
    arm_release_deployment,
    execute_trusted_release_deployment,
    record_release_deployment_dispatch,
    record_release_deployment_observation,
)
from ade.release_policy import plan_release_transition


def main() -> None:
    repository = "M-Osugi1230/one-minute-thought-experiments"
    source_sha = "b" * 40
    candidate = build_release_candidate(
        repository=repository,
        source_sha=source_sha,
        campaign_id="v1.8-release-deployment-probe-001",
        accepted_plan_fingerprint="1" * 64,
        runtime_verification_id=f"rv-{source_sha}",
        target_environment=ReleaseEnvironment.PREVIEW,
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
    transition = plan_release_transition(
        candidate=candidate,
        current_verified_environment=None,
    )
    approval = ReleaseApprovalDecision(
        decision_id="release-approval-" + transition.fingerprint()[:24],
        transition_id=transition.transition_id,
        transition_fingerprint=transition.fingerprint(),
        disposition=ReleaseApprovalDisposition.APPROVED,
        selected_option="approve",
    )

    calls: dict[str, ReleaseDeploymentObservation] = {}

    def deployer(invocation):
        existing = calls.get(invocation.idempotency_key)
        if existing is not None:
            return existing
        observation = ReleaseDeploymentObservation(
            deployment_id="dep-" + invocation.idempotency_key[-16:],
            repository=invocation.repository,
            source_sha=invocation.source_sha,
            environment=invocation.environment,
            idempotency_key=invocation.idempotency_key,
        )
        calls[invocation.idempotency_key] = observation
        return observation

    registry = TrustedReleaseDeploymentRegistry(
        (
            ReleaseDeploymentAdapterRegistration(
                repository=repository,
                environment=ReleaseEnvironment.PREVIEW,
                implementation_id="trusted-preview-adapter-v1",
                deployer=deployer,
            ),
        )
    )
    activation = arm_release_deployment(
        transition=transition,
        approval=approval,
        registry=registry,
    )
    assert activation.should_dispatch is True
    assert activation.receipt.status is ReleaseDeploymentStatus.ARMED

    dispatch = record_release_deployment_dispatch(
        invocation=activation.invocation,
        receipt=activation.receipt,
    )
    assert dispatch.changed is True
    assert dispatch.receipt.status is ReleaseDeploymentStatus.DISPATCHED
    assert dispatch.receipt.dispatch_count == 1

    resumed = arm_release_deployment(
        transition=transition,
        approval=approval,
        registry=registry,
        existing_receipt=dispatch.receipt,
    )
    assert resumed.should_dispatch is False

    observation = execute_trusted_release_deployment(
        registry=registry,
        invocation=activation.invocation,
        dispatched_receipt=dispatch.receipt,
    )
    completion = record_release_deployment_observation(
        invocation=activation.invocation,
        receipt=dispatch.receipt,
        observation=observation,
    )
    assert completion.changed is True
    assert completion.receipt.status is ReleaseDeploymentStatus.DEPLOYED
    assert completion.receipt.dispatch_count == 1
    assert completion.receipt.source_sha == source_sha
    assert completion.receipt.environment is ReleaseEnvironment.PREVIEW

    terminal = arm_release_deployment(
        transition=transition,
        approval=approval,
        registry=registry,
        existing_receipt=completion.receipt,
    )
    assert terminal.should_dispatch is False

    print(
        {
            "schema_version": 1,
            "proof": "v1.8-trusted-deployment-adapter",
            "deployment_request_id": activation.invocation.deployment_request_id,
            "idempotency_key": activation.invocation.idempotency_key,
            "registry_fingerprint": registry.fingerprint(),
            "source_sha": source_sha,
            "environment": ReleaseEnvironment.PREVIEW.value,
            "status": completion.receipt.status.value,
            "dispatch_count": completion.receipt.dispatch_count,
            "duplicate_suppressed": True,
            "controller_owned_adapter": True,
        }
    )


if __name__ == "__main__":
    main()
