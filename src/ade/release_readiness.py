from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .accepted_plan import AcceptedPlan
from .campaign import AutonomousCampaign, CampaignStatus
from .release_candidate import (
    ReleaseCandidate,
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)
from .runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationReport,
)
from .runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    runtime_verification_report_path,
)


class ReleaseReadinessError(ValueError):
    """Trusted release-readiness derivation failed."""


def _payload_fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseReadinessDecision:
    candidate: ReleaseCandidate
    accepted_plan_evidence_fingerprint: str
    campaign_evidence_fingerprint: str
    runtime_report_fingerprint: str
    runtime_contract_fingerprint: str
    runtime_receipt_status: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseReadinessError(
                "unsupported release readiness schema version"
            )
        if not isinstance(self.candidate, ReleaseCandidate):
            raise ReleaseReadinessError(
                "candidate must be ReleaseCandidate"
            )
        for field_name in (
            "accepted_plan_evidence_fingerprint",
            "campaign_evidence_fingerprint",
            "runtime_report_fingerprint",
            "runtime_contract_fingerprint",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ReleaseReadinessError(
                    f"{field_name} must be sha256"
                )
        if self.runtime_receipt_status != "VERIFIED":
            raise ReleaseReadinessError(
                "release readiness requires VERIFIED runtime receipt"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate": self.candidate.canonical_dict(),
            "candidate_fingerprint": self.candidate.fingerprint(),
            "accepted_plan_evidence_fingerprint": (
                self.accepted_plan_evidence_fingerprint
            ),
            "campaign_evidence_fingerprint": (
                self.campaign_evidence_fingerprint
            ),
            "runtime_report_fingerprint": self.runtime_report_fingerprint,
            "runtime_contract_fingerprint": self.runtime_contract_fingerprint,
            "runtime_receipt_status": self.runtime_receipt_status,
            "derived_by_trusted_controller": True,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
        }

    def fingerprint(self) -> str:
        return _payload_fingerprint(self.canonical_dict())


def derive_release_readiness(
    *,
    accepted_plan: AcceptedPlan,
    campaign: AutonomousCampaign,
    runtime_contract: RuntimeVerificationContract,
    runtime_receipt: RuntimeVerificationReceipt,
    runtime_report: RuntimeVerificationReport,
    target_environment: ReleaseEnvironment,
) -> ReleaseReadinessDecision:
    if not isinstance(accepted_plan, AcceptedPlan):
        raise ReleaseReadinessError(
            "accepted_plan must be AcceptedPlan"
        )
    if not isinstance(campaign, AutonomousCampaign):
        raise ReleaseReadinessError(
            "campaign must be AutonomousCampaign"
        )
    if not isinstance(runtime_contract, RuntimeVerificationContract):
        raise ReleaseReadinessError(
            "runtime_contract must be RuntimeVerificationContract"
        )
    if not isinstance(runtime_receipt, RuntimeVerificationReceipt):
        raise ReleaseReadinessError(
            "runtime_receipt must be RuntimeVerificationReceipt"
        )
    if not isinstance(runtime_report, RuntimeVerificationReport):
        raise ReleaseReadinessError(
            "runtime_report must be RuntimeVerificationReport"
        )
    if not isinstance(target_environment, ReleaseEnvironment):
        raise ReleaseReadinessError(
            "target_environment must be ReleaseEnvironment"
        )

    if campaign.status is not CampaignStatus.COMPLETED:
        raise ReleaseReadinessError(
            "release readiness requires terminal COMPLETED Campaign"
        )
    if tuple(campaign.completed_task_ids) != tuple(campaign.task_ids):
        raise ReleaseReadinessError(
            "release readiness requires every Campaign task completed"
        )
    planned_task_ids = tuple(task.task_id for task in accepted_plan.plan.tasks)
    if campaign.goal != accepted_plan.plan.goal:
        raise ReleaseReadinessError(
            "Campaign goal does not match AcceptedPlan"
        )
    if tuple(campaign.task_ids) != planned_task_ids:
        raise ReleaseReadinessError(
            "Campaign tasks do not match AcceptedPlan"
        )

    expected_verification_id = f"rv-{runtime_contract.source_sha}"
    if runtime_contract.verification_id != expected_verification_id:
        raise ReleaseReadinessError(
            "runtime verification is not exact post-merge identity"
        )
    if runtime_receipt.status != "VERIFIED":
        raise ReleaseReadinessError(
            "runtime verification receipt must be VERIFIED"
        )
    if runtime_receipt.dispatch_count < 1:
        raise ReleaseReadinessError(
            "runtime verification receipt was never dispatched"
        )
    if runtime_receipt.task_id != campaign.completed_task_ids[-1]:
        raise ReleaseReadinessError(
            "runtime verification is not bound to final completed Campaign task"
        )

    contract_fingerprint = runtime_contract.fingerprint()
    if runtime_receipt.verification_id != runtime_contract.verification_id:
        raise ReleaseReadinessError(
            "runtime verification receipt id drift"
        )
    if runtime_receipt.target_repository != runtime_contract.target_repository:
        raise ReleaseReadinessError(
            "runtime verification receipt repository drift"
        )
    if runtime_receipt.source_sha != runtime_contract.source_sha:
        raise ReleaseReadinessError(
            "runtime verification receipt source SHA drift"
        )
    if runtime_receipt.contract_fingerprint != contract_fingerprint:
        raise ReleaseReadinessError(
            "runtime verification receipt contract drift"
        )

    if runtime_report.verification_id != runtime_contract.verification_id:
        raise ReleaseReadinessError(
            "runtime verification report id drift"
        )
    if runtime_report.source_sha != runtime_contract.source_sha:
        raise ReleaseReadinessError(
            "runtime verification report source SHA drift"
        )
    if runtime_report.contract_fingerprint != contract_fingerprint:
        raise ReleaseReadinessError(
            "runtime verification report contract drift"
        )
    if (
        runtime_report.disposition
        is not RuntimeVerificationDisposition.VERIFIED
    ):
        raise ReleaseReadinessError(
            "runtime verification report must be VERIFIED"
        )
    if runtime_report.missing_probe_ids:
        raise ReleaseReadinessError(
            "runtime verification report has missing probes"
        )

    accepted_plan_evidence_fingerprint = _payload_fingerprint(
        accepted_plan.to_dict()
    )
    campaign_evidence_fingerprint = _payload_fingerprint(
        campaign.to_dict()
    )
    runtime_report_fingerprint = runtime_report.fingerprint()

    evidence_refs = (
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
            path=".autodev/accepted-plan.json",
            fingerprint=accepted_plan_evidence_fingerprint,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.CAMPAIGN,
            path=".autodev/campaign.json",
            fingerprint=campaign_evidence_fingerprint,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
            path=runtime_verification_report_path(runtime_receipt.task_id),
            fingerprint=runtime_report_fingerprint,
        ),
    )
    candidate = build_release_candidate(
        repository=runtime_contract.target_repository,
        source_sha=runtime_contract.source_sha,
        campaign_id=campaign.campaign_id,
        accepted_plan_fingerprint=accepted_plan.fingerprint,
        runtime_verification_id=runtime_contract.verification_id,
        target_environment=target_environment,
        evidence_refs=evidence_refs,
    )

    return ReleaseReadinessDecision(
        candidate=candidate,
        accepted_plan_evidence_fingerprint=(
            accepted_plan_evidence_fingerprint
        ),
        campaign_evidence_fingerprint=campaign_evidence_fingerprint,
        runtime_report_fingerprint=runtime_report_fingerprint,
        runtime_contract_fingerprint=contract_fingerprint,
        runtime_receipt_status=runtime_receipt.status,
    )
