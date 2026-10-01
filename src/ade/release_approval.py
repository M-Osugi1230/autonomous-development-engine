from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any

from .decisions import (
    DecisionPriority,
    DecisionRecord,
    DecisionRequest,
    DecisionStatus,
)
from .human_interrupt import HumanInterruptCoordinator
from .interrupt_policy import DecisionKind, InterruptDisposition
from .release_policy import ReleaseTransitionPlan


class ReleaseApprovalError(ValueError):
    """Trusted release-approval gate validation failed."""


class ReleaseApprovalDisposition(StrEnum):
    HUMAN_WAIT = "HUMAN_WAIT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_release_approval_request(
    transition: ReleaseTransitionPlan,
) -> DecisionRequest:
    if not isinstance(transition, ReleaseTransitionPlan):
        raise ReleaseApprovalError(
            "transition must be ReleaseTransitionPlan"
        )

    transition_fingerprint = transition.fingerprint()
    decision_id = "release-approval-" + transition_fingerprint[:24]
    from_environment = (
        transition.from_environment.value
        if transition.from_environment is not None
        else "none"
    )
    question = (
        "Approve release promotion for "
        f"{transition.repository} from {from_environment} "
        f"to {transition.to_environment.value}?"
    )
    return DecisionRequest(
        decision_id=decision_id,
        question=question,
        options=("approve", "reject"),
        priority=DecisionPriority.P0,
        blocking_task_id=transition.transition_id,
        context={
            "schema_version": 1,
            "kind": "release_promotion",
            "transition_id": transition.transition_id,
            "transition_fingerprint": transition_fingerprint,
            "release_candidate_id": transition.release_candidate_id,
            "release_candidate_fingerprint": (
                transition.release_candidate_fingerprint
            ),
            "repository": transition.repository,
            "source_sha": transition.source_sha,
            "from_environment": (
                transition.from_environment.value
                if transition.from_environment is not None
                else None
            ),
            "to_environment": transition.to_environment.value,
            "policy_fingerprint": transition.policy_fingerprint,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
        },
    )


@dataclass(frozen=True, slots=True)
class ReleaseApprovalDecision:
    decision_id: str
    transition_id: str
    transition_fingerprint: str
    disposition: ReleaseApprovalDisposition
    selected_option: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseApprovalError(
                "unsupported release approval schema version"
            )
        for field_name in (
            "decision_id",
            "transition_id",
            "transition_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ReleaseApprovalError(
                    f"{field_name} must be non-empty"
                )
        if (
            len(self.transition_fingerprint) != 64
            or any(
                char not in "0123456789abcdef"
                for char in self.transition_fingerprint
            )
        ):
            raise ReleaseApprovalError(
                "transition_fingerprint must be sha256"
            )
        if not isinstance(self.disposition, ReleaseApprovalDisposition):
            object.__setattr__(
                self,
                "disposition",
                ReleaseApprovalDisposition(self.disposition),
            )

        if self.disposition is ReleaseApprovalDisposition.HUMAN_WAIT:
            if self.selected_option is not None:
                raise ReleaseApprovalError(
                    "HUMAN_WAIT approval cannot have selected_option"
                )
        elif self.disposition is ReleaseApprovalDisposition.APPROVED:
            if self.selected_option != "approve":
                raise ReleaseApprovalError(
                    "APPROVED disposition requires explicit approve option"
                )
        elif self.disposition is ReleaseApprovalDisposition.REJECTED:
            if self.selected_option != "reject":
                raise ReleaseApprovalError(
                    "REJECTED disposition requires explicit reject option"
                )

    @property
    def approval_satisfied(self) -> bool:
        return self.disposition is ReleaseApprovalDisposition.APPROVED

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision_id": self.decision_id,
            "transition_id": self.transition_id,
            "transition_fingerprint": self.transition_fingerprint,
            "disposition": self.disposition.value,
            "selected_option": self.selected_option,
            "approval_satisfied": self.approval_satisfied,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def request_release_approval(
    *,
    coordinator: HumanInterruptCoordinator,
    transition: ReleaseTransitionPlan,
) -> ReleaseApprovalDecision:
    if not isinstance(coordinator, HumanInterruptCoordinator):
        raise ReleaseApprovalError(
            "coordinator must be HumanInterruptCoordinator"
        )
    request = build_release_approval_request(transition)
    disposition = coordinator.request_decision(
        DecisionKind.EXTERNAL_SIDE_EFFECT,
        request,
    )
    if disposition is not InterruptDisposition.HUMAN_WAIT:
        raise ReleaseApprovalError(
            "release promotion must enter HUMAN_WAIT"
        )
    return ReleaseApprovalDecision(
        decision_id=request.decision_id,
        transition_id=transition.transition_id,
        transition_fingerprint=transition.fingerprint(),
        disposition=ReleaseApprovalDisposition.HUMAN_WAIT,
        selected_option=None,
    )


def evaluate_release_approval(
    *,
    transition: ReleaseTransitionPlan,
    record: DecisionRecord,
) -> ReleaseApprovalDecision:
    if not isinstance(transition, ReleaseTransitionPlan):
        raise ReleaseApprovalError(
            "transition must be ReleaseTransitionPlan"
        )
    if not isinstance(record, DecisionRecord):
        raise ReleaseApprovalError(
            "record must be DecisionRecord"
        )

    expected_request = build_release_approval_request(transition)
    if record.request != expected_request:
        raise ReleaseApprovalError(
            "decision record does not match exact release transition"
        )

    transition_fingerprint = transition.fingerprint()
    if record.status is DecisionStatus.OPEN:
        return ReleaseApprovalDecision(
            decision_id=expected_request.decision_id,
            transition_id=transition.transition_id,
            transition_fingerprint=transition_fingerprint,
            disposition=ReleaseApprovalDisposition.HUMAN_WAIT,
            selected_option=None,
        )
    if record.status is DecisionStatus.CANCELLED:
        return ReleaseApprovalDecision(
            decision_id=expected_request.decision_id,
            transition_id=transition.transition_id,
            transition_fingerprint=transition_fingerprint,
            disposition=ReleaseApprovalDisposition.REJECTED,
            selected_option="reject",
        )
    if record.status is not DecisionStatus.RESOLVED:
        raise ReleaseApprovalError(
            "release decision status is invalid"
        )
    if record.response is None:
        raise ReleaseApprovalError(
            "resolved release decision is missing response"
        )
    if record.response.decision_id != expected_request.decision_id:
        raise ReleaseApprovalError(
            "release decision response id drift"
        )

    selected = record.response.selected_option
    if selected == "approve":
        disposition = ReleaseApprovalDisposition.APPROVED
    elif selected == "reject":
        disposition = ReleaseApprovalDisposition.REJECTED
    else:
        raise ReleaseApprovalError(
            "release approval requires explicit approve or reject option"
        )

    return ReleaseApprovalDecision(
        decision_id=expected_request.decision_id,
        transition_id=transition.transition_id,
        transition_fingerprint=transition_fingerprint,
        disposition=disposition,
        selected_option=selected,
    )
