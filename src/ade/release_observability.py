from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from .release_approval import (
    ReleaseApprovalDecision,
    ReleaseApprovalDisposition,
)
from .release_candidate import ReleaseCandidate, ReleaseEnvironment
from .release_deployment import (
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
)
from .release_policy import ReleaseTransitionPlan
from .release_post_verification import (
    ReleasePostVerificationDisposition,
    ReleasePostVerificationFinalization,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ReleaseObservabilityError(ValueError):
    """Trusted release observability projection validation failed."""


class ReleaseApprovalViewState(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    HUMAN_WAIT = "HUMAN_WAIT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReleaseDeploymentViewState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    ARMED = "ARMED"
    DISPATCHED = "DISPATCHED"
    DEPLOYED = "DEPLOYED"


class ReleaseVerificationViewState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    HUMAN_WAIT = "HUMAN_WAIT"


class ReleaseContainmentViewState(StrEnum):
    NONE = "NONE"
    HUMAN_WAIT = "HUMAN_WAIT"


class ReleasePromotionViewState(StrEnum):
    CANDIDATE_READY = "CANDIDATE_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    DEPLOYMENT_ARMED = "DEPLOYMENT_ARMED"
    DEPLOYING = "DEPLOYING"
    DEPLOYED_AWAITING_VERIFICATION = "DEPLOYED_AWAITING_VERIFICATION"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    HUMAN_WAIT = "HUMAN_WAIT"


def _safe_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ReleaseObservabilityError(f"{field} is invalid")
    folded = value.casefold()
    if any(
        marker in folded
        for marker in (
            "github_pat_",
            "ghp_",
            "gho_",
            "ghs_",
            "akia",
            "bearer",
        )
    ):
        raise ReleaseObservabilityError(
            f"{field} contains a secret-like marker"
        )
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise ReleaseObservabilityError("repository must be owner/name")
    return value


def _sha40(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ReleaseObservabilityError(
            "source_sha must be a lowercase 40-char SHA"
        )
    return value


def _optional_action(value: str | None) -> str | None:
    if value is None:
        return None
    return _safe_id(value, field="next_required_human_action")


@dataclass(frozen=True, slots=True)
class ReleaseObservabilitySnapshot:
    release_candidate_id: str
    repository: str
    source_sha: str
    target_environment: ReleaseEnvironment
    approval_state: ReleaseApprovalViewState
    promotion_state: ReleasePromotionViewState
    deployment_state: ReleaseDeploymentViewState
    verification_state: ReleaseVerificationViewState
    containment_state: ReleaseContainmentViewState
    deployment_identity_present: bool
    next_required_human_action: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseObservabilityError(
                "unsupported release observability schema version"
            )
        object.__setattr__(
            self,
            "release_candidate_id",
            _safe_id(
                self.release_candidate_id,
                field="release_candidate_id",
            ),
        )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "source_sha", _sha40(self.source_sha))
        if not isinstance(self.target_environment, ReleaseEnvironment):
            object.__setattr__(
                self,
                "target_environment",
                ReleaseEnvironment(self.target_environment),
            )
        for field_name, enum_type in (
            ("approval_state", ReleaseApprovalViewState),
            ("promotion_state", ReleasePromotionViewState),
            ("deployment_state", ReleaseDeploymentViewState),
            ("verification_state", ReleaseVerificationViewState),
            ("containment_state", ReleaseContainmentViewState),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, enum_type):
                try:
                    object.__setattr__(self, field_name, enum_type(value))
                except (TypeError, ValueError) as exc:
                    raise ReleaseObservabilityError(
                        f"{field_name} is invalid"
                    ) from exc
        if type(self.deployment_identity_present) is not bool:
            raise ReleaseObservabilityError(
                "deployment_identity_present must be boolean"
            )
        object.__setattr__(
            self,
            "next_required_human_action",
            _optional_action(self.next_required_human_action),
        )

        if (
            self.deployment_state is ReleaseDeploymentViewState.DEPLOYED
        ) != self.deployment_identity_present:
            raise ReleaseObservabilityError(
                "deployment identity presence must match DEPLOYED state"
            )
        if (
            self.verification_state
            is ReleaseVerificationViewState.VERIFIED
            and self.promotion_state
            is not ReleasePromotionViewState.VERIFIED
        ):
            raise ReleaseObservabilityError(
                "verified release must have VERIFIED promotion state"
            )
        if (
            self.containment_state
            is ReleaseContainmentViewState.HUMAN_WAIT
        ):
            if (
                self.verification_state
                is not ReleaseVerificationViewState.HUMAN_WAIT
                or self.promotion_state
                is not ReleasePromotionViewState.HUMAN_WAIT
                or self.next_required_human_action
                != "review-release-runtime-verification-failure"
            ):
                raise ReleaseObservabilityError(
                    "release containment HUMAN_WAIT state is inconsistent"
                )
        elif (
            self.verification_state
            is ReleaseVerificationViewState.HUMAN_WAIT
        ):
            raise ReleaseObservabilityError(
                "runtime HUMAN_WAIT requires containment HUMAN_WAIT"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "release_candidate_id": self.release_candidate_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "target_environment": self.target_environment.value,
            "approval_state": self.approval_state.value,
            "promotion_state": self.promotion_state.value,
            "deployment_state": self.deployment_state.value,
            "verification_state": self.verification_state.value,
            "containment_state": self.containment_state.value,
            "deployment_identity_present": self.deployment_identity_present,
            "next_required_human_action": self.next_required_human_action,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ReleaseObservabilitySnapshot":
        if not isinstance(payload, dict):
            raise ReleaseObservabilityError(
                "release observability snapshot must be a JSON object"
            )
        allowed = {
            "schema_version",
            "release_candidate_id",
            "repository",
            "source_sha",
            "target_environment",
            "approval_state",
            "promotion_state",
            "deployment_state",
            "verification_state",
            "containment_state",
            "deployment_identity_present",
            "next_required_human_action",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ReleaseObservabilityError(
                f"unknown release observability fields: {sorted(unknown)}"
            )
        try:
            environment = ReleaseEnvironment(payload.get("target_environment"))
            approval_state = ReleaseApprovalViewState(
                payload.get("approval_state")
            )
            promotion_state = ReleasePromotionViewState(
                payload.get("promotion_state")
            )
            deployment_state = ReleaseDeploymentViewState(
                payload.get("deployment_state")
            )
            verification_state = ReleaseVerificationViewState(
                payload.get("verification_state")
            )
            containment_state = ReleaseContainmentViewState(
                payload.get("containment_state")
            )
        except (TypeError, ValueError) as exc:
            raise ReleaseObservabilityError(
                "release observability state is invalid"
            ) from exc
        return cls(
            schema_version=payload.get("schema_version", 0),
            release_candidate_id=payload.get("release_candidate_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            target_environment=environment,
            approval_state=approval_state,
            promotion_state=promotion_state,
            deployment_state=deployment_state,
            verification_state=verification_state,
            containment_state=containment_state,
            deployment_identity_present=payload.get(
                "deployment_identity_present"
            ),
            next_required_human_action=payload.get(
                "next_required_human_action"
            ),
        )


def build_release_observability_snapshot(
    *,
    candidate: ReleaseCandidate,
    transition: ReleaseTransitionPlan | None = None,
    approval: ReleaseApprovalDecision | None = None,
    deployment_receipt: ReleaseDeploymentReceipt | None = None,
    finalization: ReleasePostVerificationFinalization | None = None,
) -> ReleaseObservabilitySnapshot:
    if not isinstance(candidate, ReleaseCandidate):
        raise ReleaseObservabilityError(
            "candidate must be ReleaseCandidate"
        )

    if transition is not None:
        if not isinstance(transition, ReleaseTransitionPlan):
            raise ReleaseObservabilityError(
                "transition must be ReleaseTransitionPlan or null"
            )
        if transition.release_candidate_id != candidate.release_candidate_id:
            raise ReleaseObservabilityError(
                "transition release candidate id drift"
            )
        if (
            transition.release_candidate_fingerprint
            != candidate.fingerprint()
        ):
            raise ReleaseObservabilityError(
                "transition release candidate fingerprint drift"
            )
        if transition.repository != candidate.repository:
            raise ReleaseObservabilityError(
                "transition repository drift"
            )
        if transition.source_sha != candidate.source_sha:
            raise ReleaseObservabilityError(
                "transition source SHA drift"
            )
        if transition.to_environment is not candidate.target_environment:
            raise ReleaseObservabilityError(
                "transition target environment drift"
            )

    if approval is not None:
        if transition is None:
            raise ReleaseObservabilityError(
                "approval requires transition"
            )
        if not isinstance(approval, ReleaseApprovalDecision):
            raise ReleaseObservabilityError(
                "approval must be ReleaseApprovalDecision or null"
            )
        if approval.transition_id != transition.transition_id:
            raise ReleaseObservabilityError(
                "approval transition id drift"
            )
        if approval.transition_fingerprint != transition.fingerprint():
            raise ReleaseObservabilityError(
                "approval transition fingerprint drift"
            )

    if deployment_receipt is not None:
        if transition is None or approval is None:
            raise ReleaseObservabilityError(
                "deployment receipt requires transition and approval"
            )
        if not isinstance(deployment_receipt, ReleaseDeploymentReceipt):
            raise ReleaseObservabilityError(
                "deployment_receipt must be ReleaseDeploymentReceipt or null"
            )
        if not approval.approval_satisfied:
            raise ReleaseObservabilityError(
                "deployment receipt requires satisfied approval"
            )
        if (
            deployment_receipt.transition_id
            != transition.transition_id
            or deployment_receipt.transition_fingerprint
            != transition.fingerprint()
        ):
            raise ReleaseObservabilityError(
                "deployment transition drift"
            )
        if deployment_receipt.approval_fingerprint != approval.fingerprint():
            raise ReleaseObservabilityError(
                "deployment approval fingerprint drift"
            )
        if deployment_receipt.repository != candidate.repository:
            raise ReleaseObservabilityError(
                "deployment repository drift"
            )
        if deployment_receipt.source_sha != candidate.source_sha:
            raise ReleaseObservabilityError(
                "deployment source SHA drift"
            )
        if (
            deployment_receipt.environment
            is not candidate.target_environment
        ):
            raise ReleaseObservabilityError(
                "deployment environment drift"
            )

    if finalization is not None:
        if deployment_receipt is None:
            raise ReleaseObservabilityError(
                "post-verification finalization requires deployment receipt"
            )
        if not isinstance(
            finalization,
            ReleasePostVerificationFinalization,
        ):
            raise ReleaseObservabilityError(
                "finalization must be ReleasePostVerificationFinalization or null"
            )
        if (
            deployment_receipt.status
            is not ReleaseDeploymentStatus.DEPLOYED
            or deployment_receipt.deployment_id is None
        ):
            raise ReleaseObservabilityError(
                "post-verification finalization requires DEPLOYED receipt"
            )
        if finalization.outcome.deployment_id != deployment_receipt.deployment_id:
            raise ReleaseObservabilityError(
                "post-verification deployment identity drift"
            )
        if finalization.outcome.environment is not candidate.target_environment:
            raise ReleaseObservabilityError(
                "post-verification environment drift"
            )

    if approval is None:
        approval_state = ReleaseApprovalViewState.NOT_REQUESTED
    elif (
        approval.disposition
        is ReleaseApprovalDisposition.HUMAN_WAIT
    ):
        approval_state = ReleaseApprovalViewState.HUMAN_WAIT
    elif (
        approval.disposition
        is ReleaseApprovalDisposition.APPROVED
    ):
        approval_state = ReleaseApprovalViewState.APPROVED
    else:
        approval_state = ReleaseApprovalViewState.REJECTED

    if deployment_receipt is None:
        deployment_state = ReleaseDeploymentViewState.NOT_STARTED
        deployment_identity_present = False
    else:
        deployment_state = ReleaseDeploymentViewState(
            deployment_receipt.status.value
        )
        deployment_identity_present = (
            deployment_receipt.status
            is ReleaseDeploymentStatus.DEPLOYED
            and deployment_receipt.deployment_id is not None
        )

    if finalization is None:
        verification_state = ReleaseVerificationViewState.NOT_STARTED
        containment_state = ReleaseContainmentViewState.NONE
    elif (
        finalization.outcome.disposition
        is ReleasePostVerificationDisposition.VERIFIED
    ):
        verification_state = ReleaseVerificationViewState.VERIFIED
        containment_state = ReleaseContainmentViewState.NONE
    elif (
        finalization.outcome.disposition
        is ReleasePostVerificationDisposition.PENDING
    ):
        verification_state = ReleaseVerificationViewState.PENDING
        containment_state = ReleaseContainmentViewState.NONE
    else:
        verification_state = ReleaseVerificationViewState.HUMAN_WAIT
        containment_state = ReleaseContainmentViewState.HUMAN_WAIT

    next_required_human_action: str | None = None
    if finalization is not None and containment_state is ReleaseContainmentViewState.HUMAN_WAIT:
        promotion_state = ReleasePromotionViewState.HUMAN_WAIT
        next_required_human_action = (
            "review-release-runtime-verification-failure"
        )
    elif finalization is not None and verification_state is ReleaseVerificationViewState.VERIFIED:
        promotion_state = ReleasePromotionViewState.VERIFIED
    elif finalization is not None:
        promotion_state = ReleasePromotionViewState.VERIFYING
    elif deployment_receipt is not None:
        if (
            deployment_receipt.status
            is ReleaseDeploymentStatus.DEPLOYED
        ):
            promotion_state = (
                ReleasePromotionViewState.DEPLOYED_AWAITING_VERIFICATION
            )
        elif (
            deployment_receipt.status
            is ReleaseDeploymentStatus.DISPATCHED
        ):
            promotion_state = ReleasePromotionViewState.DEPLOYING
        else:
            promotion_state = ReleasePromotionViewState.DEPLOYMENT_ARMED
    elif approval is not None:
        if (
            approval.disposition
            is ReleaseApprovalDisposition.APPROVED
        ):
            promotion_state = ReleasePromotionViewState.APPROVED
        elif (
            approval.disposition
            is ReleaseApprovalDisposition.REJECTED
        ):
            promotion_state = ReleasePromotionViewState.REJECTED
        else:
            promotion_state = ReleasePromotionViewState.AWAITING_APPROVAL
            next_required_human_action = "review-release-promotion-approval"
    elif transition is not None:
        promotion_state = ReleasePromotionViewState.AWAITING_APPROVAL
        next_required_human_action = "review-release-promotion-approval"
    else:
        promotion_state = ReleasePromotionViewState.CANDIDATE_READY

    return ReleaseObservabilitySnapshot(
        release_candidate_id=candidate.release_candidate_id,
        repository=candidate.repository,
        source_sha=candidate.source_sha,
        target_environment=candidate.target_environment,
        approval_state=approval_state,
        promotion_state=promotion_state,
        deployment_state=deployment_state,
        verification_state=verification_state,
        containment_state=containment_state,
        deployment_identity_present=deployment_identity_present,
        next_required_human_action=next_required_human_action,
    )
