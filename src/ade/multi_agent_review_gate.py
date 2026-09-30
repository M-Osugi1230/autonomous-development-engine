from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .accepted_plan import AcceptedPlan
from .multi_agent import AgentRole, MultiAgentPlan
from .multi_agent_contribution import (
    AgentContribution,
    ContributionVerdict,
    validate_contribution_against_plan,
)
from .multi_agent_reconciliation import (
    ReconciliationDisposition,
    ReconciliationResult,
)
from .multi_agent_session import RoleSession, RoleSessionState


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


class MultiAgentReviewGateError(ValueError):
    """Trusted review-clearance validation failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise MultiAgentReviewGateError(f"{field} must be lowercase SHA40")
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MultiAgentReviewGateError(f"{field} must be sha256")
    return value


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise MultiAgentReviewGateError(f"{field} is invalid")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise MultiAgentReviewGateError("target_repository must be owner/name")
    return value


@dataclass(frozen=True, slots=True)
class ReviewClearance:
    clearance_id: str
    task_id: str
    target_repository: str
    plan_source_sha: str
    reviewed_head_sha: str
    pull_request_number: int
    accepted_plan_fingerprint: str
    multi_agent_plan_fingerprint: str
    reviewer_assignment_id: str
    reviewer_assignment_fingerprint: str
    reviewer_role_session_fingerprint: str
    contribution_fingerprint: str
    reconciliation_fingerprint: str
    reviewer_provider_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentReviewGateError(
                "unsupported review-clearance schema version"
            )
        object.__setattr__(
            self,
            "clearance_id",
            _identifier(self.clearance_id, field="clearance_id"),
        )
        object.__setattr__(
            self,
            "task_id",
            _identifier(self.task_id, field="task_id"),
        )
        object.__setattr__(
            self,
            "target_repository",
            _repository(self.target_repository),
        )
        object.__setattr__(
            self,
            "plan_source_sha",
            _sha40(self.plan_source_sha, field="plan_source_sha"),
        )
        object.__setattr__(
            self,
            "reviewed_head_sha",
            _sha40(self.reviewed_head_sha, field="reviewed_head_sha"),
        )
        if (
            type(self.pull_request_number) is not int
            or self.pull_request_number < 1
        ):
            raise MultiAgentReviewGateError(
                "pull_request_number must be positive"
            )
        for field in (
            "accepted_plan_fingerprint",
            "multi_agent_plan_fingerprint",
            "reviewer_assignment_fingerprint",
            "reviewer_role_session_fingerprint",
            "contribution_fingerprint",
            "reconciliation_fingerprint",
        ):
            _sha256(getattr(self, field), field=field)
        object.__setattr__(
            self,
            "reviewer_assignment_id",
            _identifier(
                self.reviewer_assignment_id,
                field="reviewer_assignment_id",
            ),
        )
        if (
            not isinstance(self.reviewer_provider_id, str)
            or not self.reviewer_provider_id.strip()
            or self.reviewer_provider_id != self.reviewer_provider_id.strip()
        ):
            raise MultiAgentReviewGateError(
                "reviewer_provider_id must be non-empty"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "clearance_id": self.clearance_id,
            "task_id": self.task_id,
            "target_repository": self.target_repository,
            "plan_source_sha": self.plan_source_sha,
            "reviewed_head_sha": self.reviewed_head_sha,
            "pull_request_number": self.pull_request_number,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "multi_agent_plan_fingerprint": self.multi_agent_plan_fingerprint,
            "reviewer_assignment_id": self.reviewer_assignment_id,
            "reviewer_assignment_fingerprint": (
                self.reviewer_assignment_fingerprint
            ),
            "reviewer_role_session_fingerprint": (
                self.reviewer_role_session_fingerprint
            ),
            "contribution_fingerprint": self.contribution_fingerprint,
            "reconciliation_fingerprint": self.reconciliation_fingerprint,
            "reviewer_provider_id": self.reviewer_provider_id,
            "verdict": "CLEAR",
            "advisory_evidence_only": True,
            "execution_authority": False,
            "code_mutation_authority": False,
            "campaign_state_authority": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "runtime_verification_authority": False,
            "auto_dispatch": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: object) -> "ReviewClearance":
        if not isinstance(payload, dict):
            raise MultiAgentReviewGateError(
                "review clearance must be a JSON object"
            )
        allowed = {
            "schema_version",
            "clearance_id",
            "task_id",
            "target_repository",
            "plan_source_sha",
            "reviewed_head_sha",
            "pull_request_number",
            "accepted_plan_fingerprint",
            "multi_agent_plan_fingerprint",
            "reviewer_assignment_id",
            "reviewer_assignment_fingerprint",
            "reviewer_role_session_fingerprint",
            "contribution_fingerprint",
            "reconciliation_fingerprint",
            "reviewer_provider_id",
            "verdict",
            "advisory_evidence_only",
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "merge_authority",
            "acceptance_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise MultiAgentReviewGateError(
                f"unknown review-clearance fields: {sorted(unknown)}"
            )
        if payload.get("verdict") != "CLEAR":
            raise MultiAgentReviewGateError(
                "review clearance requires CLEAR verdict"
            )
        if payload.get("advisory_evidence_only") is not True:
            raise MultiAgentReviewGateError(
                "review clearance must remain advisory evidence"
            )
        for field in (
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "merge_authority",
            "acceptance_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        ):
            if payload.get(field, False) is not False:
                raise MultiAgentReviewGateError(
                    f"review clearance cannot grant {field}"
                )
        return cls(
            schema_version=payload.get("schema_version", 0),
            clearance_id=payload.get("clearance_id", ""),
            task_id=payload.get("task_id", ""),
            target_repository=payload.get("target_repository", ""),
            plan_source_sha=payload.get("plan_source_sha", ""),
            reviewed_head_sha=payload.get("reviewed_head_sha", ""),
            pull_request_number=payload.get("pull_request_number", 0),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            multi_agent_plan_fingerprint=payload.get(
                "multi_agent_plan_fingerprint",
                "",
            ),
            reviewer_assignment_id=payload.get(
                "reviewer_assignment_id",
                "",
            ),
            reviewer_assignment_fingerprint=payload.get(
                "reviewer_assignment_fingerprint",
                "",
            ),
            reviewer_role_session_fingerprint=payload.get(
                "reviewer_role_session_fingerprint",
                "",
            ),
            contribution_fingerprint=payload.get(
                "contribution_fingerprint",
                "",
            ),
            reconciliation_fingerprint=payload.get(
                "reconciliation_fingerprint",
                "",
            ),
            reviewer_provider_id=payload.get("reviewer_provider_id", ""),
        )


def build_review_clearance(
    *,
    accepted_plan: AcceptedPlan,
    plan: MultiAgentPlan,
    role_session: RoleSession,
    contribution: AgentContribution,
    reconciliation: ReconciliationResult,
    reviewed_head_sha: str,
    pull_request_number: int,
) -> ReviewClearance:
    if not isinstance(accepted_plan, AcceptedPlan):
        raise MultiAgentReviewGateError(
            "accepted_plan must be AcceptedPlan"
        )
    if accepted_plan.fingerprint != plan.accepted_plan_fingerprint:
        raise MultiAgentReviewGateError(
            "AcceptedPlan fingerprint does not match MultiAgentPlan"
        )
    if plan.task_id not in {
        task.task_id for task in accepted_plan.plan.tasks
    }:
        raise MultiAgentReviewGateError(
            "MultiAgentPlan task is absent from AcceptedPlan"
        )

    reviewer = next(
        (
            item
            for item in plan.assignments
            if item.role is AgentRole.REVIEWER
        ),
        None,
    )
    if reviewer is None:
        raise MultiAgentReviewGateError(
            "review clearance requires REVIEWER assignment"
        )

    validate_contribution_against_plan(contribution, plan)
    if contribution.role is not AgentRole.REVIEWER:
        raise MultiAgentReviewGateError(
            "review clearance requires REVIEWER contribution"
        )
    if contribution.verdict is not ContributionVerdict.CLEAR:
        raise MultiAgentReviewGateError(
            "review clearance requires CLEAR contribution"
        )

    if role_session.state is not RoleSessionState.COMPLETED:
        raise MultiAgentReviewGateError(
            "review clearance requires completed reviewer role session"
        )
    if role_session.plan_fingerprint != plan.fingerprint():
        raise MultiAgentReviewGateError("reviewer role-session plan drift")
    if (
        role_session.assignment_id != reviewer.assignment_id
        or role_session.assignment_fingerprint != reviewer.fingerprint()
        or role_session.role != AgentRole.REVIEWER.value
        or role_session.provider_id != reviewer.provider_id
    ):
        raise MultiAgentReviewGateError(
            "reviewer role-session assignment drift"
        )

    if reconciliation.disposition is not ReconciliationDisposition.CLEAR:
        raise MultiAgentReviewGateError(
            "review clearance requires CLEAR reconciliation"
        )
    if reconciliation.multi_agent_plan_fingerprint != plan.fingerprint():
        raise MultiAgentReviewGateError("reconciliation plan drift")
    if reconciliation.accepted_plan_fingerprint != accepted_plan.fingerprint:
        raise MultiAgentReviewGateError(
            "reconciliation AcceptedPlan drift"
        )
    contribution_fp = contribution.fingerprint()
    if contribution_fp not in reconciliation.contribution_fingerprints:
        raise MultiAgentReviewGateError(
            "review contribution is absent from reconciliation"
        )

    reviewed_sha = _sha40(
        reviewed_head_sha,
        field="reviewed_head_sha",
    )
    if type(pull_request_number) is not int or pull_request_number < 1:
        raise MultiAgentReviewGateError(
            "pull_request_number must be positive"
        )

    identity = _fingerprint(
        {
            "task_id": plan.task_id,
            "target_repository": plan.repository,
            "plan_source_sha": plan.source_sha,
            "reviewed_head_sha": reviewed_sha,
            "pull_request_number": pull_request_number,
            "accepted_plan_fingerprint": accepted_plan.fingerprint,
            "multi_agent_plan_fingerprint": plan.fingerprint(),
            "reviewer_assignment_fingerprint": reviewer.fingerprint(),
            "reviewer_role_session_fingerprint": role_session.fingerprint(),
            "contribution_fingerprint": contribution_fp,
            "reconciliation_fingerprint": reconciliation.fingerprint(),
        }
    )
    return ReviewClearance(
        clearance_id=f"review-clearance-{identity[:24]}",
        task_id=plan.task_id,
        target_repository=plan.repository,
        plan_source_sha=plan.source_sha,
        reviewed_head_sha=reviewed_sha,
        pull_request_number=pull_request_number,
        accepted_plan_fingerprint=accepted_plan.fingerprint,
        multi_agent_plan_fingerprint=plan.fingerprint(),
        reviewer_assignment_id=reviewer.assignment_id,
        reviewer_assignment_fingerprint=reviewer.fingerprint(),
        reviewer_role_session_fingerprint=role_session.fingerprint(),
        contribution_fingerprint=contribution_fp,
        reconciliation_fingerprint=reconciliation.fingerprint(),
        reviewer_provider_id=reviewer.provider_id,
    )
