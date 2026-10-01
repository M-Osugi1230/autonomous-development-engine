from __future__ import annotations

from ade.accepted_plan import AcceptedPlan
from ade.campaign import AutonomousCampaign, CampaignStatus
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.release_candidate import ReleaseEnvironment
from ade.release_readiness import ReleaseReadinessError, derive_release_readiness
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


def main() -> None:
    repository = "M-Osugi1230/one-minute-thought-experiments"
    source_sha = "8" * 40
    plan = DevelopmentPlan(
        goal="Ship a verified bounded improvement.",
        tasks=(
            PlannedTask(
                task_id="release-001",
                title="Bounded release task",
                prompt="Implement one bounded verified change.",
                depends_on=(),
                allowed_paths=("tests/test_models.py",),
                acceptance=("Target regression passes.",),
            ),
        ),
    )
    accepted_plan = AcceptedPlan.accept(plan)
    campaign = AutonomousCampaign(
        campaign_id="v1.8-release-probe-001",
        goal=plan.goal,
        task_ids=("release-001",),
        status=CampaignStatus.COMPLETED,
        completed_task_ids=("release-001",),
    )
    contract = RuntimeVerificationContract(
        verification_id=f"rv-{source_sha}",
        target_repository=repository,
        source_sha=source_sha,
        environment="repository",
        required_probe_ids=("production-import-smoke",),
    )
    report = evaluate_runtime_verification(
        contract,
        (
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=source_sha,
            ),
        ),
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="release-001",
        target_repository=repository,
        source_sha=source_sha,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="a" * 64,
        policy_fingerprint="b" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )

    decision = derive_release_readiness(
        accepted_plan=accepted_plan,
        campaign=campaign,
        runtime_contract=contract,
        runtime_receipt=receipt,
        runtime_report=report,
        target_environment=ReleaseEnvironment.STAGING,
    )
    assert decision.candidate.source_sha == source_sha
    assert decision.candidate.requires_human_approval is True
    assert decision.runtime_receipt_status == "VERIFIED"
    assert decision.canonical_dict()["promotion_authority"] is False

    failed_receipt = RuntimeVerificationReceipt(
        verification_id=receipt.verification_id,
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        source_sha=receipt.source_sha,
        contract_fingerprint=receipt.contract_fingerprint,
        registry_fingerprint=receipt.registry_fingerprint,
        policy_fingerprint=receipt.policy_fingerprint,
        status="FAILED",
        dispatch_count=1,
    )
    try:
        derive_release_readiness(
            accepted_plan=accepted_plan,
            campaign=campaign,
            runtime_contract=contract,
            runtime_receipt=failed_receipt,
            runtime_report=report,
            target_environment=ReleaseEnvironment.STAGING,
        )
    except ReleaseReadinessError:
        pass
    else:
        raise AssertionError("failed runtime receipt must block release readiness")

    print(
        {
            "schema_version": 1,
            "proof": "v1.8-release-readiness",
            "candidate_id": decision.candidate.release_candidate_id,
            "candidate_fingerprint": decision.candidate.fingerprint(),
            "decision_fingerprint": decision.fingerprint(),
            "runtime_status": decision.runtime_receipt_status,
            "promotion_authority": False,
        }
    )


if __name__ == "__main__":
    main()
