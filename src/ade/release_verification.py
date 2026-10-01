from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable

from .campaign import AutonomousCampaign, CampaignStatus
from .recovery_runtime import RecoveryRecord
from .release_candidate import ReleaseCandidate
from .release_deployment import (
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
)
from .release_policy import ReleaseTransitionPlan
from .runtime_probe_registry import TrustedRuntimeProbeRegistry
from .runtime_target_registry import (
    RuntimeTargetResolution,
    TrustedRuntimeTargetRegistry,
)
from .runtime_verification import (
    RuntimeProbeResult,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationReport,
    evaluate_runtime_verification,
)
from .runtime_verification_recovery import (
    contain_runtime_verification_failure,
)
from .runtime_verification_trigger import (
    RuntimeVerificationPolicy,
    RuntimeVerificationReceipt,
    record_runtime_verification_report,
)


class ReleaseVerificationError(ValueError):
    """Trusted post-promotion Runtime Verification validation failed."""


class ReleaseVerificationDisposition(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    HUMAN_WAIT = "HUMAN_WAIT"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseVerificationActivation:
    release_candidate_id: str
    release_candidate_fingerprint: str
    transition_id: str
    transition_fingerprint: str
    deployment_request_id: str
    deployment_receipt_fingerprint: str
    deployment_id: str
    campaign_id: str
    campaign_fingerprint: str
    final_task_id: str
    contract: RuntimeVerificationContract
    receipt: RuntimeVerificationReceipt
    target_resolution: RuntimeTargetResolution
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseVerificationError(
                "unsupported release verification activation schema version"
            )
        for field_name in (
            "release_candidate_id",
            "transition_id",
            "deployment_request_id",
            "deployment_id",
            "campaign_id",
            "final_task_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ReleaseVerificationError(
                    f"{field_name} must be non-empty"
                )
        for field_name in (
            "release_candidate_fingerprint",
            "transition_fingerprint",
            "deployment_receipt_fingerprint",
            "campaign_fingerprint",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ReleaseVerificationError(
                    f"{field_name} must be sha256"
                )
        if not isinstance(self.contract, RuntimeVerificationContract):
            raise ReleaseVerificationError(
                "contract must be RuntimeVerificationContract"
            )
        if not isinstance(self.receipt, RuntimeVerificationReceipt):
            raise ReleaseVerificationError(
                "receipt must be RuntimeVerificationReceipt"
            )
        if not isinstance(self.target_resolution, RuntimeTargetResolution):
            raise ReleaseVerificationError(
                "target_resolution must be RuntimeTargetResolution"
            )
        if self.receipt.status != "ARMED":
            raise ReleaseVerificationError(
                "release verification activation receipt must be ARMED"
            )
        if self.receipt.dispatch_count != 0:
            raise ReleaseVerificationError(
                "release verification activation must be undispatched"
            )
        if self.receipt.verification_id != self.contract.verification_id:
            raise ReleaseVerificationError(
                "release verification activation id drift"
            )
        if self.receipt.source_sha != self.contract.source_sha:
            raise ReleaseVerificationError(
                "release verification activation source SHA drift"
            )
        if self.receipt.contract_fingerprint != self.contract.fingerprint():
            raise ReleaseVerificationError(
                "release verification activation contract drift"
            )
        evidence = self.target_resolution.evidence
        if evidence.deployment_id != self.deployment_id:
            raise ReleaseVerificationError(
                "release verification activation deployment drift"
            )
        if evidence.source_sha != self.contract.source_sha:
            raise ReleaseVerificationError(
                "release verification target source SHA drift"
            )
        if evidence.target_repository != self.contract.target_repository:
            raise ReleaseVerificationError(
                "release verification target repository drift"
            )
        if evidence.environment != self.contract.environment:
            raise ReleaseVerificationError(
                "release verification target environment drift"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "release_candidate_id": self.release_candidate_id,
            "release_candidate_fingerprint": (
                self.release_candidate_fingerprint
            ),
            "transition_id": self.transition_id,
            "transition_fingerprint": self.transition_fingerprint,
            "deployment_request_id": self.deployment_request_id,
            "deployment_receipt_fingerprint": (
                self.deployment_receipt_fingerprint
            ),
            "deployment_id": self.deployment_id,
            "campaign_id": self.campaign_id,
            "campaign_fingerprint": self.campaign_fingerprint,
            "final_task_id": self.final_task_id,
            "contract": self.contract.canonical_dict(),
            "contract_fingerprint": self.contract.fingerprint(),
            "receipt": self.receipt.canonical_dict(),
            "target_resolution": self.target_resolution.canonical_dict(),
            "automatic_rollback": False,
            "auto_promote_next_environment": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReleaseVerificationResult:
    disposition: ReleaseVerificationDisposition
    activation_fingerprint: str
    report: RuntimeVerificationReport
    receipt: RuntimeVerificationReceipt
    state: dict[str, Any]
    campaign: dict[str, Any]
    recovery: RecoveryRecord | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseVerificationError(
                "unsupported release verification result schema version"
            )
        if (
            not isinstance(self.activation_fingerprint, str)
            or len(self.activation_fingerprint) != 64
            or any(
                ch not in "0123456789abcdef"
                for ch in self.activation_fingerprint
            )
        ):
            raise ReleaseVerificationError(
                "activation_fingerprint must be sha256"
            )
        if not isinstance(self.disposition, ReleaseVerificationDisposition):
            object.__setattr__(
                self,
                "disposition",
                ReleaseVerificationDisposition(self.disposition),
            )
        if not isinstance(self.report, RuntimeVerificationReport):
            raise ReleaseVerificationError(
                "report must be RuntimeVerificationReport"
            )
        if not isinstance(self.receipt, RuntimeVerificationReceipt):
            raise ReleaseVerificationError(
                "receipt must be RuntimeVerificationReceipt"
            )
        if not isinstance(self.state, dict) or not isinstance(
            self.campaign,
            dict,
        ):
            raise ReleaseVerificationError(
                "state and campaign must be objects"
            )
        if self.disposition is ReleaseVerificationDisposition.VERIFIED:
            if self.report.disposition is not RuntimeVerificationDisposition.VERIFIED:
                raise ReleaseVerificationError(
                    "VERIFIED release result requires VERIFIED runtime report"
                )
            if self.receipt.status != "VERIFIED":
                raise ReleaseVerificationError(
                    "VERIFIED release result requires VERIFIED receipt"
                )
            if self.recovery is not None:
                raise ReleaseVerificationError(
                    "VERIFIED release result cannot contain recovery"
                )
        elif self.disposition is ReleaseVerificationDisposition.HUMAN_WAIT:
            if self.report.disposition is not RuntimeVerificationDisposition.FAILED:
                raise ReleaseVerificationError(
                    "HUMAN_WAIT release result requires FAILED runtime report"
                )
            if self.receipt.status != "HUMAN_WAIT":
                raise ReleaseVerificationError(
                    "HUMAN_WAIT release result requires HUMAN_WAIT receipt"
                )
            if self.recovery is None or self.recovery.action.value != "HUMAN_WAIT":
                raise ReleaseVerificationError(
                    "HUMAN_WAIT release result requires containment recovery"
                )
        elif self.disposition is ReleaseVerificationDisposition.PENDING:
            if self.report.disposition is not RuntimeVerificationDisposition.PENDING:
                raise ReleaseVerificationError(
                    "PENDING release result requires PENDING runtime report"
                )
            if self.receipt.status != "DISPATCHED":
                raise ReleaseVerificationError(
                    "PENDING release result requires DISPATCHED receipt"
                )
            if self.recovery is not None:
                raise ReleaseVerificationError(
                    "PENDING release result cannot contain recovery"
                )

    @property
    def promotion_verified(self) -> bool:
        return self.disposition is ReleaseVerificationDisposition.VERIFIED

    @property
    def next_environment_allowed(self) -> bool:
        return self.promotion_verified

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "disposition": self.disposition.value,
            "activation_fingerprint": self.activation_fingerprint,
            "report": self.report.canonical_dict(),
            "report_fingerprint": self.report.fingerprint(),
            "receipt": self.receipt.canonical_dict(),
            "recovery": (
                self.recovery.to_dict()
                if self.recovery is not None
                else None
            ),
            "promotion_verified": self.promotion_verified,
            "next_environment_allowed": self.next_environment_allowed,
            "automatic_rollback": False,
            "auto_promote_next_environment": False,
        }


def arm_post_promotion_runtime_verification(
    *,
    candidate: ReleaseCandidate,
    transition: ReleaseTransitionPlan,
    deployment_receipt: ReleaseDeploymentReceipt,
    campaign: AutonomousCampaign,
    policy: RuntimeVerificationPolicy,
    probe_registry: TrustedRuntimeProbeRegistry,
    target_registry: TrustedRuntimeTargetRegistry,
    now: datetime,
) -> ReleaseVerificationActivation:
    if not isinstance(candidate, ReleaseCandidate):
        raise ReleaseVerificationError(
            "candidate must be ReleaseCandidate"
        )
    if not isinstance(transition, ReleaseTransitionPlan):
        raise ReleaseVerificationError(
            "transition must be ReleaseTransitionPlan"
        )
    if not isinstance(deployment_receipt, ReleaseDeploymentReceipt):
        raise ReleaseVerificationError(
            "deployment_receipt must be ReleaseDeploymentReceipt"
        )
    if not isinstance(campaign, AutonomousCampaign):
        raise ReleaseVerificationError(
            "campaign must be AutonomousCampaign"
        )
    if not isinstance(policy, RuntimeVerificationPolicy):
        raise ReleaseVerificationError(
            "policy must be RuntimeVerificationPolicy"
        )
    if not isinstance(probe_registry, TrustedRuntimeProbeRegistry):
        raise ReleaseVerificationError(
            "probe_registry must be TrustedRuntimeProbeRegistry"
        )
    if not isinstance(target_registry, TrustedRuntimeTargetRegistry):
        raise ReleaseVerificationError(
            "target_registry must be TrustedRuntimeTargetRegistry"
        )

    candidate_fingerprint = candidate.fingerprint()
    if transition.release_candidate_id != candidate.release_candidate_id:
        raise ReleaseVerificationError(
            "release transition candidate id drift"
        )
    if (
        transition.release_candidate_fingerprint
        != candidate_fingerprint
    ):
        raise ReleaseVerificationError(
            "release transition candidate fingerprint drift"
        )
    if transition.repository != candidate.repository:
        raise ReleaseVerificationError(
            "release transition repository drift"
        )
    if transition.source_sha != candidate.source_sha:
        raise ReleaseVerificationError(
            "release transition source SHA drift"
        )
    if transition.to_environment is not candidate.target_environment:
        raise ReleaseVerificationError(
            "release transition environment drift"
        )

    if deployment_receipt.status is not ReleaseDeploymentStatus.DEPLOYED:
        raise ReleaseVerificationError(
            "post-promotion verification requires DEPLOYED receipt"
        )
    if deployment_receipt.deployment_id is None:
        raise ReleaseVerificationError(
            "DEPLOYED receipt is missing deployment_id"
        )
    if deployment_receipt.repository != candidate.repository:
        raise ReleaseVerificationError(
            "deployment receipt repository drift"
        )
    if deployment_receipt.source_sha != candidate.source_sha:
        raise ReleaseVerificationError(
            "deployment receipt source SHA drift"
        )
    if (
        deployment_receipt.environment
        is not candidate.target_environment
    ):
        raise ReleaseVerificationError(
            "deployment receipt environment drift"
        )
    if deployment_receipt.transition_id != transition.transition_id:
        raise ReleaseVerificationError(
            "deployment receipt transition id drift"
        )
    if (
        deployment_receipt.transition_fingerprint
        != transition.fingerprint()
    ):
        raise ReleaseVerificationError(
            "deployment receipt transition fingerprint drift"
        )

    if campaign.status is not CampaignStatus.COMPLETED:
        raise ReleaseVerificationError(
            "post-promotion verification requires COMPLETED Campaign"
        )
    if tuple(campaign.completed_task_ids) != tuple(campaign.task_ids):
        raise ReleaseVerificationError(
            "post-promotion verification requires all Campaign tasks completed"
        )
    if candidate.campaign_id != campaign.campaign_id:
        raise ReleaseVerificationError(
            "release candidate Campaign drift"
        )
    final_task_id = campaign.completed_task_ids[-1]

    if policy.target_repository != candidate.repository:
        raise ReleaseVerificationError(
            "runtime policy repository drift"
        )
    if policy.environment != candidate.target_environment.value:
        raise ReleaseVerificationError(
            "runtime policy environment drift"
        )

    deployment_receipt_fingerprint = deployment_receipt.fingerprint()
    verification_seed = {
        "deployment_request_id": deployment_receipt.deployment_request_id,
        "deployment_receipt_fingerprint": deployment_receipt_fingerprint,
        "deployment_id": deployment_receipt.deployment_id,
        "repository": candidate.repository,
        "source_sha": candidate.source_sha,
        "environment": candidate.target_environment.value,
        "policy_fingerprint": policy.fingerprint(),
    }
    verification_id = "release-rv-" + _fingerprint(
        verification_seed
    )[:24]
    contract = RuntimeVerificationContract(
        verification_id=verification_id,
        target_repository=candidate.repository,
        source_sha=candidate.source_sha,
        environment=candidate.target_environment.value,
        required_probe_ids=policy.required_probe_ids,
        max_attempts=policy.max_attempts,
        timeout_seconds=policy.timeout_seconds,
    )
    probe_registry.ensure_contract_supported(contract)
    target_resolution = target_registry.resolve(contract, now=now)

    target_evidence = target_resolution.evidence
    if target_evidence.deployment_id != deployment_receipt.deployment_id:
        raise ReleaseVerificationError(
            "runtime target does not match exact deployment id"
        )
    if target_evidence.source_sha != deployment_receipt.source_sha:
        raise ReleaseVerificationError(
            "runtime target does not match exact deployment source SHA"
        )

    receipt = RuntimeVerificationReceipt(
        verification_id=verification_id,
        task_id=final_task_id,
        target_repository=candidate.repository,
        source_sha=candidate.source_sha,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint=probe_registry.fingerprint(),
        policy_fingerprint=policy.fingerprint(),
        status="ARMED",
        dispatch_count=0,
    )
    return ReleaseVerificationActivation(
        release_candidate_id=candidate.release_candidate_id,
        release_candidate_fingerprint=candidate_fingerprint,
        transition_id=transition.transition_id,
        transition_fingerprint=transition.fingerprint(),
        deployment_request_id=deployment_receipt.deployment_request_id,
        deployment_receipt_fingerprint=deployment_receipt_fingerprint,
        deployment_id=deployment_receipt.deployment_id,
        campaign_id=campaign.campaign_id,
        campaign_fingerprint=_fingerprint(campaign.to_dict()),
        final_task_id=final_task_id,
        contract=contract,
        receipt=receipt,
        target_resolution=target_resolution,
    )


def complete_post_promotion_runtime_verification(
    *,
    activation: ReleaseVerificationActivation,
    dispatched_receipt: RuntimeVerificationReceipt,
    results: Iterable[RuntimeProbeResult],
    state_payload: dict[str, Any],
    campaign_payload: dict[str, Any],
    previous_recovery: RecoveryRecord | None = None,
) -> ReleaseVerificationResult:
    if not isinstance(activation, ReleaseVerificationActivation):
        raise ReleaseVerificationError(
            "activation must be ReleaseVerificationActivation"
        )
    if not isinstance(dispatched_receipt, RuntimeVerificationReceipt):
        raise ReleaseVerificationError(
            "dispatched_receipt must be RuntimeVerificationReceipt"
        )
    if dispatched_receipt.status != "DISPATCHED":
        raise ReleaseVerificationError(
            "post-promotion verification requires DISPATCHED runtime receipt"
        )
    if dispatched_receipt.dispatch_count != 1:
        raise ReleaseVerificationError(
            "post-promotion verification requires single runtime dispatch"
        )
    if dispatched_receipt.verification_id != activation.contract.verification_id:
        raise ReleaseVerificationError(
            "post-promotion runtime receipt id drift"
        )
    if dispatched_receipt.task_id != activation.final_task_id:
        raise ReleaseVerificationError(
            "post-promotion runtime receipt task drift"
        )
    if dispatched_receipt.target_repository != activation.contract.target_repository:
        raise ReleaseVerificationError(
            "post-promotion runtime receipt repository drift"
        )
    if dispatched_receipt.source_sha != activation.contract.source_sha:
        raise ReleaseVerificationError(
            "post-promotion runtime receipt source SHA drift"
        )
    if (
        dispatched_receipt.contract_fingerprint
        != activation.contract.fingerprint()
    ):
        raise ReleaseVerificationError(
            "post-promotion runtime receipt contract drift"
        )
    if not isinstance(state_payload, dict):
        raise ReleaseVerificationError("state_payload must be an object")
    if not isinstance(campaign_payload, dict):
        raise ReleaseVerificationError("campaign_payload must be an object")
    if _fingerprint(campaign_payload) != activation.campaign_fingerprint:
        raise ReleaseVerificationError(
            "post-promotion Campaign evidence drift"
        )

    report = evaluate_runtime_verification(
        activation.contract,
        results,
    )
    completion = record_runtime_verification_report(
        contract=activation.contract,
        receipt=dispatched_receipt,
        report=report,
    )

    if report.disposition is RuntimeVerificationDisposition.PENDING:
        return ReleaseVerificationResult(
            disposition=ReleaseVerificationDisposition.PENDING,
            activation_fingerprint=activation.fingerprint(),
            report=report,
            receipt=completion.receipt,
            state=dict(state_payload),
            campaign=dict(campaign_payload),
            recovery=None,
        )

    if report.disposition is RuntimeVerificationDisposition.VERIFIED:
        return ReleaseVerificationResult(
            disposition=ReleaseVerificationDisposition.VERIFIED,
            activation_fingerprint=activation.fingerprint(),
            report=report,
            receipt=completion.receipt,
            state=dict(state_payload),
            campaign=dict(campaign_payload),
            recovery=None,
        )

    containment = contain_runtime_verification_failure(
        receipt=completion.receipt,
        report=report,
        state_payload=state_payload,
        campaign_payload=campaign_payload,
        previous_recovery=previous_recovery,
    )
    contained_state = dict(containment.state)
    metadata = dict(contained_state.get("metadata", {}))
    metadata["next_required_human_action"] = (
        "review-release-runtime-verification-failure"
    )
    metadata["release_deployment_id"] = activation.deployment_id
    metadata["release_verification_id"] = activation.contract.verification_id
    metadata["automatic_rollback"] = False
    metadata["auto_promote_next_environment"] = False
    contained_state["metadata"] = metadata

    return ReleaseVerificationResult(
        disposition=ReleaseVerificationDisposition.HUMAN_WAIT,
        activation_fingerprint=activation.fingerprint(),
        report=report,
        receipt=containment.receipt,
        state=contained_state,
        campaign=containment.campaign,
        recovery=containment.recovery,
    )
