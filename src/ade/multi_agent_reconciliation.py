from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable

from .decisions import DecisionPriority, DecisionRequest
from .multi_agent import AgentRole, MultiAgentPlan
from .multi_agent_contribution import (
    AgentContribution,
    ContributionVerdict,
    MultiAgentContributionError,
    validate_contribution_against_plan,
)


class MultiAgentReconciliationError(ValueError):
    """Trusted multi-agent reconciliation failed."""


class ReconciliationDisposition(StrEnum):
    CLEAR = "CLEAR"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    HUMAN_WAIT = "HUMAN_WAIT"
    INCOMPLETE = "INCOMPLETE"


class ReconciliationReason(StrEnum):
    ALL_CLEAR = "ALL_CLEAR"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    MATERIAL_DISAGREEMENT = "MATERIAL_DISAGREEMENT"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    MISSING_REQUIRED_CONTRIBUTION = "MISSING_REQUIRED_CONTRIBUTION"


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
class ReconciliationPolicy:
    reviewer_required: bool = True
    diagnostic_required: bool = False
    disagreement_to_human_wait: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentReconciliationError(
                "unsupported reconciliation policy schema version"
            )
        for field in (
            "reviewer_required",
            "diagnostic_required",
            "disagreement_to_human_wait",
        ):
            if type(getattr(self, field)) is not bool:
                raise MultiAgentReconciliationError(
                    f"{field} must be a bool"
                )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "reviewer_required": self.reviewer_required,
            "diagnostic_required": self.diagnostic_required,
            "disagreement_to_human_wait": self.disagreement_to_human_wait,
            "majority_voting": False,
            "execution_authority": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "runtime_verification_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    multi_agent_plan_fingerprint: str
    contribution_fingerprints: tuple[str, ...]
    disposition: ReconciliationDisposition
    reason: ReconciliationReason
    policy_fingerprint: str
    human_decision_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentReconciliationError(
                "unsupported reconciliation result schema version"
            )
        try:
            disposition = ReconciliationDisposition(self.disposition)
            reason = ReconciliationReason(self.reason)
        except (ValueError, TypeError) as exc:
            raise MultiAgentReconciliationError(
                "invalid reconciliation enum value"
            ) from exc
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason", reason)

        fingerprints = tuple(sorted(set(self.contribution_fingerprints)))
        if len(fingerprints) != len(self.contribution_fingerprints):
            raise MultiAgentReconciliationError(
                "contribution fingerprints must be unique"
            )
        for value in fingerprints:
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise MultiAgentReconciliationError(
                    "contribution fingerprint must be sha256"
                )
        object.__setattr__(
            self,
            "contribution_fingerprints",
            fingerprints,
        )

        for field in (
            "accepted_plan_fingerprint",
            "multi_agent_plan_fingerprint",
            "policy_fingerprint",
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise MultiAgentReconciliationError(
                    f"{field} must be sha256"
                )

        if disposition is ReconciliationDisposition.HUMAN_WAIT:
            if not isinstance(self.human_decision_id, str) or not self.human_decision_id:
                raise MultiAgentReconciliationError(
                    "HUMAN_WAIT requires human_decision_id"
                )
        elif self.human_decision_id is not None:
            raise MultiAgentReconciliationError(
                "only HUMAN_WAIT may carry human_decision_id"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "multi_agent_plan_fingerprint": self.multi_agent_plan_fingerprint,
            "contribution_fingerprints": list(
                self.contribution_fingerprints
            ),
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "policy_fingerprint": self.policy_fingerprint,
            "human_decision_id": self.human_decision_id,
            "majority_voting": False,
            "execution_authority": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "runtime_verification_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def _human_decision_id(
    *,
    plan: MultiAgentPlan,
    contribution_fingerprints: tuple[str, ...],
    reason: ReconciliationReason,
) -> str:
    digest = _fingerprint(
        {
            "plan_fingerprint": plan.fingerprint(),
            "contribution_fingerprints": sorted(
                contribution_fingerprints
            ),
            "reason": reason.value,
        }
    )
    return f"multi-agent-decision-{digest[:24]}"


def _result(
    *,
    plan: MultiAgentPlan,
    contributions: tuple[AgentContribution, ...],
    disposition: ReconciliationDisposition,
    reason: ReconciliationReason,
    policy: ReconciliationPolicy,
) -> ReconciliationResult:
    contribution_fingerprints = tuple(
        sorted(item.fingerprint() for item in contributions)
    )
    decision_id = (
        _human_decision_id(
            plan=plan,
            contribution_fingerprints=contribution_fingerprints,
            reason=reason,
        )
        if disposition is ReconciliationDisposition.HUMAN_WAIT
        else None
    )
    return ReconciliationResult(
        repository=plan.repository,
        source_sha=plan.source_sha,
        campaign_id=plan.campaign_id,
        task_id=plan.task_id,
        accepted_plan_fingerprint=plan.accepted_plan_fingerprint,
        multi_agent_plan_fingerprint=plan.fingerprint(),
        contribution_fingerprints=contribution_fingerprints,
        disposition=disposition,
        reason=reason,
        policy_fingerprint=policy.fingerprint(),
        human_decision_id=decision_id,
    )


def reconcile_agent_contributions(
    *,
    plan: MultiAgentPlan,
    contributions: Iterable[AgentContribution],
    policy: ReconciliationPolicy | None = None,
) -> ReconciliationResult:
    if not isinstance(plan, MultiAgentPlan):
        raise MultiAgentReconciliationError(
            "plan must be MultiAgentPlan"
        )
    resolved_policy = (
        policy if policy is not None else ReconciliationPolicy()
    )
    if not isinstance(resolved_policy, ReconciliationPolicy):
        raise MultiAgentReconciliationError(
            "policy must be ReconciliationPolicy or None"
        )
    if isinstance(contributions, (str, bytes)):
        raise MultiAgentReconciliationError(
            "contributions must be an iterable"
        )
    try:
        items = tuple(contributions)
    except TypeError as exc:
        raise MultiAgentReconciliationError(
            "contributions must be an iterable"
        ) from exc

    expected_by_role = {
        assignment.role: assignment
        for assignment in plan.assignments
        if assignment.role in {
            AgentRole.REVIEWER,
            AgentRole.DIAGNOSTIC,
        }
    }
    if (
        resolved_policy.reviewer_required
        and AgentRole.REVIEWER not in expected_by_role
    ):
        raise MultiAgentReconciliationError(
            "reconciliation policy requires REVIEWER assignment"
        )
    if (
        resolved_policy.diagnostic_required
        and AgentRole.DIAGNOSTIC not in expected_by_role
    ):
        raise MultiAgentReconciliationError(
            "reconciliation policy requires DIAGNOSTIC assignment"
        )

    seen_assignments: set[str] = set()
    contributions_by_role: dict[AgentRole, AgentContribution] = {}
    for contribution in items:
        if not isinstance(contribution, AgentContribution):
            raise MultiAgentReconciliationError(
                "contributions must contain AgentContribution values"
            )
        try:
            validate_contribution_against_plan(
                contribution,
                plan,
            )
        except MultiAgentContributionError as exc:
            raise MultiAgentReconciliationError(str(exc)) from exc
        if contribution.assignment_id in seen_assignments:
            raise MultiAgentReconciliationError(
                "duplicate contribution for assignment"
            )
        seen_assignments.add(contribution.assignment_id)
        contributions_by_role[contribution.role] = contribution

    if (
        resolved_policy.reviewer_required
        and AgentRole.REVIEWER not in contributions_by_role
    ) or (
        resolved_policy.diagnostic_required
        and AgentRole.DIAGNOSTIC not in contributions_by_role
    ):
        return _result(
            plan=plan,
            contributions=items,
            disposition=ReconciliationDisposition.INCOMPLETE,
            reason=ReconciliationReason.MISSING_REQUIRED_CONTRIBUTION,
            policy=resolved_policy,
        )

    if not items:
        return _result(
            plan=plan,
            contributions=items,
            disposition=ReconciliationDisposition.INCOMPLETE,
            reason=ReconciliationReason.MISSING_REQUIRED_CONTRIBUTION,
            policy=resolved_policy,
        )

    verdicts = {item.verdict for item in items}
    if ContributionVerdict.HUMAN_REVIEW_REQUIRED in verdicts:
        return _result(
            plan=plan,
            contributions=items,
            disposition=ReconciliationDisposition.HUMAN_WAIT,
            reason=ReconciliationReason.HUMAN_REVIEW_REQUIRED,
            policy=resolved_policy,
        )

    has_clear = ContributionVerdict.CLEAR in verdicts
    has_changes = ContributionVerdict.CHANGES_REQUIRED in verdicts
    if (
        has_clear
        and has_changes
        and resolved_policy.disagreement_to_human_wait
    ):
        return _result(
            plan=plan,
            contributions=items,
            disposition=ReconciliationDisposition.HUMAN_WAIT,
            reason=ReconciliationReason.MATERIAL_DISAGREEMENT,
            policy=resolved_policy,
        )

    if has_changes:
        return _result(
            plan=plan,
            contributions=items,
            disposition=ReconciliationDisposition.CHANGES_REQUIRED,
            reason=ReconciliationReason.CHANGES_REQUESTED,
            policy=resolved_policy,
        )

    return _result(
        plan=plan,
        contributions=items,
        disposition=ReconciliationDisposition.CLEAR,
        reason=ReconciliationReason.ALL_CLEAR,
        policy=resolved_policy,
    )


def build_reconciliation_decision_request(
    result: ReconciliationResult,
) -> DecisionRequest:
    if not isinstance(result, ReconciliationResult):
        raise MultiAgentReconciliationError(
            "result must be ReconciliationResult"
        )
    if result.disposition is not ReconciliationDisposition.HUMAN_WAIT:
        raise MultiAgentReconciliationError(
            "human decision request requires HUMAN_WAIT result"
        )
    assert result.human_decision_id is not None
    return DecisionRequest(
        decision_id=result.human_decision_id,
        question=(
            "Multi-agent review evidence requires a trusted human decision "
            f"for task {result.task_id}."
        ),
        options=(
            "require_changes",
            "accept_current_scope",
            "abort_task",
        ),
        priority=DecisionPriority.P1,
        blocking_task_id=result.task_id,
        context={
            "repository": result.repository,
            "source_sha": result.source_sha,
            "campaign_id": result.campaign_id,
            "accepted_plan_fingerprint": (
                result.accepted_plan_fingerprint
            ),
            "multi_agent_plan_fingerprint": (
                result.multi_agent_plan_fingerprint
            ),
            "contribution_fingerprints": list(
                result.contribution_fingerprints
            ),
            "reason": result.reason.value,
        },
    )
