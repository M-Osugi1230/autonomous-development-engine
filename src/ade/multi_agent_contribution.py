from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from .multi_agent import AgentAssignment, AgentRole, MultiAgentPlan


_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_MARKERS = (
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "github_pat_",
    "ghp_",
    "gho_",
    "ghs_",
    "akia",
    "bearer ",
)


class MultiAgentContributionError(ValueError):
    """Trusted multi-agent contribution validation failed."""


class ContributionKind(StrEnum):
    REVIEW = "REVIEW"
    DIAGNOSTIC = "DIAGNOSTIC"


class ContributionVerdict(StrEnum):
    CLEAR = "CLEAR"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise MultiAgentContributionError(f"{field} is invalid")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise MultiAgentContributionError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise MultiAgentContributionError("repository must be owner/name")
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise MultiAgentContributionError(
            f"{field} must be a lowercase 40-char SHA"
        )
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MultiAgentContributionError(f"{field} must be sha256")
    return value


def _provider_id(value: str) -> str:
    if not isinstance(value, str) or _PROVIDER_ID.fullmatch(value) is None:
        raise MultiAgentContributionError("provider_id is invalid")
    return value


def _summary(value: str) -> str:
    if not isinstance(value, str):
        raise MultiAgentContributionError("summary must be text")
    if _CONTROL.search(value):
        raise MultiAgentContributionError(
            "summary must be bounded printable text"
        )
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > 500:
        raise MultiAgentContributionError(
            "summary must be bounded printable text"
        )
    folded = normalized.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        raise MultiAgentContributionError(
            "summary contains a secret-like marker"
        )
    if "http://" in folded or "https://" in folded:
        raise MultiAgentContributionError("summary must not contain URLs")
    return normalized


def _evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise MultiAgentContributionError("evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise MultiAgentContributionError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise MultiAgentContributionError(
            "evidence path must be normalized"
        )
    if not value.startswith(".autodev/"):
        raise MultiAgentContributionError(
            "evidence path must remain inside .autodev/"
        )
    return value


def _authority_false(payload: dict[str, Any], field: str) -> None:
    if payload.get(field, False) is not False:
        raise MultiAgentContributionError(
            f"contribution cannot grant {field.replace('_', ' ')}"
        )


@dataclass(frozen=True, slots=True)
class AgentContribution:
    contribution_id: str
    kind: ContributionKind
    verdict: ContributionVerdict
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    multi_agent_plan_fingerprint: str
    assignment_id: str
    assignment_fingerprint: str
    role: AgentRole
    provider_id: str
    summary: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentContributionError(
                "unsupported contribution schema version"
            )
        object.__setattr__(
            self,
            "contribution_id",
            _identifier(self.contribution_id, field="contribution_id"),
        )
        if not isinstance(self.kind, ContributionKind):
            raise MultiAgentContributionError(
                "kind must be ContributionKind"
            )
        if not isinstance(self.verdict, ContributionVerdict):
            raise MultiAgentContributionError(
                "verdict must be ContributionVerdict"
            )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "source_sha",
            _sha40(self.source_sha, field="source_sha"),
        )
        object.__setattr__(
            self,
            "campaign_id",
            _identifier(self.campaign_id, field="campaign_id"),
        )
        object.__setattr__(
            self,
            "task_id",
            _identifier(self.task_id, field="task_id"),
        )
        object.__setattr__(
            self,
            "accepted_plan_fingerprint",
            _sha256(
                self.accepted_plan_fingerprint,
                field="accepted_plan_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "multi_agent_plan_fingerprint",
            _sha256(
                self.multi_agent_plan_fingerprint,
                field="multi_agent_plan_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "assignment_id",
            _identifier(self.assignment_id, field="assignment_id"),
        )
        object.__setattr__(
            self,
            "assignment_fingerprint",
            _sha256(
                self.assignment_fingerprint,
                field="assignment_fingerprint",
            ),
        )
        if not isinstance(self.role, AgentRole):
            raise MultiAgentContributionError("role must be AgentRole")
        if self.role not in {AgentRole.REVIEWER, AgentRole.DIAGNOSTIC}:
            raise MultiAgentContributionError(
                "only REVIEWER or DIAGNOSTIC may produce advisory contributions"
            )
        expected_kind = (
            ContributionKind.REVIEW
            if self.role is AgentRole.REVIEWER
            else ContributionKind.DIAGNOSTIC
        )
        if self.kind is not expected_kind:
            raise MultiAgentContributionError(
                "contribution kind does not match agent role"
            )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(self, "summary", _summary(self.summary))

        paths = tuple(sorted({_evidence_path(path) for path in self.evidence_paths}))
        fingerprints = tuple(
            sorted(
                {
                    _sha256(value, field="evidence_fingerprint")
                    for value in self.evidence_fingerprints
                }
            )
        )
        if not paths or not fingerprints:
            raise MultiAgentContributionError(
                "contribution requires trusted evidence"
            )
        if len(paths) > 8 or len(fingerprints) > 8:
            raise MultiAgentContributionError(
                "contribution evidence exceeds trusted budget"
            )
        object.__setattr__(self, "evidence_paths", paths)
        object.__setattr__(self, "evidence_fingerprints", fingerprints)

    def trust_anchor(self) -> tuple[str, str, str, str, str]:
        return (
            self.repository,
            self.source_sha,
            self.campaign_id,
            self.task_id,
            self.accepted_plan_fingerprint,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "contribution_id": self.contribution_id,
            "kind": self.kind.value,
            "verdict": self.verdict.value,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "multi_agent_plan_fingerprint": (
                self.multi_agent_plan_fingerprint
            ),
            "assignment_id": self.assignment_id,
            "assignment_fingerprint": self.assignment_fingerprint,
            "role": self.role.value,
            "provider_id": self.provider_id,
            "summary": self.summary,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "advisory_only": True,
            "execution_authority": False,
            "code_mutation_authority": False,
            "campaign_state_authority": False,
            "acceptance_authority": False,
            "merge_authority": False,
            "runtime_verification_authority": False,
            "auto_dispatch": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentContribution":
        if not isinstance(payload, dict):
            raise MultiAgentContributionError(
                "contribution must be a JSON object"
            )
        allowed = {
            "schema_version",
            "contribution_id",
            "kind",
            "verdict",
            "repository",
            "source_sha",
            "campaign_id",
            "task_id",
            "accepted_plan_fingerprint",
            "multi_agent_plan_fingerprint",
            "assignment_id",
            "assignment_fingerprint",
            "role",
            "provider_id",
            "summary",
            "evidence_paths",
            "evidence_fingerprints",
            "advisory_only",
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "acceptance_authority",
            "merge_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise MultiAgentContributionError(
                f"unknown contribution fields: {sorted(unknown)}"
            )
        if payload.get("advisory_only", True) is not True:
            raise MultiAgentContributionError(
                "contribution must remain advisory only"
            )
        for field in (
            "execution_authority",
            "code_mutation_authority",
            "campaign_state_authority",
            "acceptance_authority",
            "merge_authority",
            "runtime_verification_authority",
            "auto_dispatch",
            "may_expand_scope",
        ):
            _authority_false(payload, field)
        try:
            kind = ContributionKind(payload.get("kind"))
            verdict = ContributionVerdict(payload.get("verdict"))
            role = AgentRole(payload.get("role"))
        except (ValueError, TypeError) as exc:
            raise MultiAgentContributionError(
                "contribution enum value is invalid"
            ) from exc
        raw_paths = payload.get("evidence_paths")
        raw_fingerprints = payload.get("evidence_fingerprints")
        if not isinstance(raw_paths, list):
            raise MultiAgentContributionError(
                "evidence_paths must be a list"
            )
        if not isinstance(raw_fingerprints, list):
            raise MultiAgentContributionError(
                "evidence_fingerprints must be a list"
            )
        return cls(
            schema_version=payload.get("schema_version", 0),
            contribution_id=payload.get("contribution_id", ""),
            kind=kind,
            verdict=verdict,
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            campaign_id=payload.get("campaign_id", ""),
            task_id=payload.get("task_id", ""),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            multi_agent_plan_fingerprint=payload.get(
                "multi_agent_plan_fingerprint",
                "",
            ),
            assignment_id=payload.get("assignment_id", ""),
            assignment_fingerprint=payload.get(
                "assignment_fingerprint",
                "",
            ),
            role=role,
            provider_id=payload.get("provider_id", ""),
            summary=payload.get("summary", ""),
            evidence_paths=tuple(raw_paths),
            evidence_fingerprints=tuple(raw_fingerprints),
        )


def build_agent_contribution(
    *,
    plan: MultiAgentPlan,
    assignment_id: str,
    verdict: ContributionVerdict,
    summary: str,
    evidence_paths: tuple[str, ...],
    evidence_fingerprints: tuple[str, ...],
) -> AgentContribution:
    if not isinstance(plan, MultiAgentPlan):
        raise MultiAgentContributionError(
            "plan must be a MultiAgentPlan"
        )
    assignment = next(
        (
            item
            for item in plan.assignments
            if item.assignment_id == assignment_id
        ),
        None,
    )
    if assignment is None:
        raise MultiAgentContributionError(
            "assignment_id is not present in the MultiAgentPlan"
        )
    if assignment.role is AgentRole.IMPLEMENTER:
        raise MultiAgentContributionError(
            "IMPLEMENTER cannot emit reviewer/diagnostic contribution"
        )
    try:
        normalized_verdict = ContributionVerdict(verdict)
    except (ValueError, TypeError) as exc:
        raise MultiAgentContributionError(
            "contribution verdict is invalid"
        ) from exc
    kind = (
        ContributionKind.REVIEW
        if assignment.role is AgentRole.REVIEWER
        else ContributionKind.DIAGNOSTIC
    )
    plan_fingerprint = plan.fingerprint()
    assignment_fingerprint = assignment.fingerprint()
    digest = _fingerprint(
        {
            "plan_fingerprint": plan_fingerprint,
            "assignment_fingerprint": assignment_fingerprint,
            "verdict": normalized_verdict.value,
            "summary": _summary(summary),
            "evidence_paths": sorted(evidence_paths),
            "evidence_fingerprints": sorted(evidence_fingerprints),
        }
    )
    return AgentContribution(
        contribution_id=f"contribution-{digest[:24]}",
        kind=kind,
        verdict=normalized_verdict,
        repository=plan.repository,
        source_sha=plan.source_sha,
        campaign_id=plan.campaign_id,
        task_id=plan.task_id,
        accepted_plan_fingerprint=plan.accepted_plan_fingerprint,
        multi_agent_plan_fingerprint=plan_fingerprint,
        assignment_id=assignment.assignment_id,
        assignment_fingerprint=assignment_fingerprint,
        role=assignment.role,
        provider_id=assignment.provider_id,
        summary=summary,
        evidence_paths=evidence_paths,
        evidence_fingerprints=evidence_fingerprints,
    )


def validate_contribution_against_plan(
    contribution: AgentContribution,
    plan: MultiAgentPlan,
) -> None:
    if not isinstance(contribution, AgentContribution):
        raise MultiAgentContributionError(
            "contribution must be AgentContribution"
        )
    if not isinstance(plan, MultiAgentPlan):
        raise MultiAgentContributionError(
            "plan must be MultiAgentPlan"
        )
    if contribution.multi_agent_plan_fingerprint != plan.fingerprint():
        raise MultiAgentContributionError(
            "contribution MultiAgentPlan fingerprint mismatch"
        )
    expected_anchor = (
        plan.repository,
        plan.source_sha,
        plan.campaign_id,
        plan.task_id,
        plan.accepted_plan_fingerprint,
    )
    if contribution.trust_anchor() != expected_anchor:
        raise MultiAgentContributionError(
            "contribution trust anchor mismatch"
        )
    assignment = next(
        (
            item
            for item in plan.assignments
            if item.assignment_id == contribution.assignment_id
        ),
        None,
    )
    if assignment is None:
        raise MultiAgentContributionError(
            "contribution assignment is not in MultiAgentPlan"
        )
    if contribution.assignment_fingerprint != assignment.fingerprint():
        raise MultiAgentContributionError(
            "contribution assignment fingerprint mismatch"
        )
    if contribution.role is not assignment.role:
        raise MultiAgentContributionError(
            "contribution role mismatch"
        )
    if contribution.provider_id != assignment.provider_id:
        raise MultiAgentContributionError(
            "contribution provider mismatch"
        )
