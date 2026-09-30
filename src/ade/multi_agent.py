from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
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
MAX_AGENT_ASSIGNMENTS = 3


class MultiAgentError(ValueError):
    """Trusted multi-agent validation failed."""


class AgentRole(StrEnum):
    IMPLEMENTER = "IMPLEMENTER"
    REVIEWER = "REVIEWER"
    DIAGNOSTIC = "DIAGNOSTIC"


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
        raise MultiAgentError(f"{field} is invalid")
    return value


def _provider_id(value: str) -> str:
    if not isinstance(value, str) or _PROVIDER_ID.fullmatch(value) is None:
        raise MultiAgentError("provider_id is invalid")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise MultiAgentError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise MultiAgentError("repository must be owner/name")
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise MultiAgentError(f"{field} must be a lowercase 40-char SHA")
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MultiAgentError(f"{field} must be sha256")
    return value


def _bounded_text(value: str, *, field: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise MultiAgentError(f"{field} must be text")
    if _CONTROL.search(value):
        raise MultiAgentError(f"{field} must be bounded printable text")
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > max_chars:
        raise MultiAgentError(f"{field} must be bounded printable text")
    folded = normalized.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        raise MultiAgentError(f"{field} contains a secret-like marker")
    if "http://" in folded or "https://" in folded:
        raise MultiAgentError(f"{field} must not contain URLs")
    return normalized


def _evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise MultiAgentError("evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise MultiAgentError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise MultiAgentError("evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise MultiAgentError("evidence path must remain inside .autodev/")
    return value


def _authority_false(payload: dict[str, Any], field: str) -> None:
    if payload.get(field, False) is not False:
        raise MultiAgentError(
            f"multi-agent data cannot grant {field.replace('_', ' ')}"
        )


@dataclass(frozen=True, slots=True)
class AgentAssignment:
    assignment_id: str
    role: AgentRole
    provider_id: str
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    objective: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentError("unsupported agent assignment schema version")
        object.__setattr__(
            self,
            "assignment_id",
            _identifier(self.assignment_id, field="assignment_id"),
        )
        if not isinstance(self.role, AgentRole):
            raise MultiAgentError("role must be AgentRole")
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
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
            "objective",
            _bounded_text(self.objective, field="objective", max_chars=500),
        )

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
            raise MultiAgentError("agent assignment requires trusted evidence")
        if len(paths) > 6 or len(fingerprints) > 6:
            raise MultiAgentError("agent assignment evidence exceeds trusted budget")
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
            "assignment_id": self.assignment_id,
            "role": self.role.value,
            "provider_id": self.provider_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "objective": self.objective,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "execution_authority": False,
            "auto_dispatch": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentAssignment":
        if not isinstance(payload, dict):
            raise MultiAgentError("agent assignment must be a JSON object")
        allowed = {
            "schema_version",
            "assignment_id",
            "role",
            "provider_id",
            "repository",
            "source_sha",
            "campaign_id",
            "task_id",
            "accepted_plan_fingerprint",
            "objective",
            "evidence_paths",
            "evidence_fingerprints",
            "execution_authority",
            "auto_dispatch",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise MultiAgentError(
                f"unknown agent assignment fields: {sorted(unknown)}"
            )
        for field in (
            "execution_authority",
            "auto_dispatch",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        ):
            _authority_false(payload, field)
        try:
            role = AgentRole(payload.get("role"))
        except (ValueError, TypeError) as exc:
            raise MultiAgentError("agent role is invalid") from exc
        raw_paths = payload.get("evidence_paths")
        raw_fingerprints = payload.get("evidence_fingerprints")
        if not isinstance(raw_paths, list):
            raise MultiAgentError("evidence_paths must be a list")
        if not isinstance(raw_fingerprints, list):
            raise MultiAgentError("evidence_fingerprints must be a list")
        return cls(
            schema_version=payload.get("schema_version", 0),
            assignment_id=payload.get("assignment_id", ""),
            role=role,
            provider_id=payload.get("provider_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            campaign_id=payload.get("campaign_id", ""),
            task_id=payload.get("task_id", ""),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            objective=payload.get("objective", ""),
            evidence_paths=tuple(raw_paths),
            evidence_fingerprints=tuple(raw_fingerprints),
        )


@dataclass(frozen=True, slots=True)
class MultiAgentPlan:
    plan_id: str
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    assignments: tuple[AgentAssignment, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentError("unsupported multi-agent plan schema version")
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, field="plan_id"))
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

        assignments = tuple(self.assignments)
        if not assignments:
            raise MultiAgentError("multi-agent plan requires at least one assignment")
        if len(assignments) > MAX_AGENT_ASSIGNMENTS:
            raise MultiAgentError("multi-agent plan exceeds assignment budget")
        if any(not isinstance(item, AgentAssignment) for item in assignments):
            raise MultiAgentError(
                "assignments must contain only AgentAssignment values"
            )

        expected_anchor = (
            self.repository,
            self.source_sha,
            self.campaign_id,
            self.task_id,
            self.accepted_plan_fingerprint,
        )
        ids: set[str] = set()
        roles: set[AgentRole] = set()
        for assignment in assignments:
            if assignment.trust_anchor() != expected_anchor:
                raise MultiAgentError(
                    "agent assignment trust anchor does not match plan"
                )
            if assignment.assignment_id in ids:
                raise MultiAgentError(
                    f"duplicate assignment_id: {assignment.assignment_id}"
                )
            if assignment.role in roles:
                raise MultiAgentError(
                    f"duplicate agent role: {assignment.role.value}"
                )
            ids.add(assignment.assignment_id)
            roles.add(assignment.role)

        if AgentRole.IMPLEMENTER not in roles:
            raise MultiAgentError(
                "multi-agent plan requires exactly one IMPLEMENTER assignment"
            )

        normalized = tuple(
            sorted(
                assignments,
                key=lambda item: (item.role.value, item.assignment_id),
            )
        )
        object.__setattr__(self, "assignments", normalized)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.provider_id for item in self.assignments}))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "assignments": [
                assignment.canonical_dict()
                for assignment in self.assignments
            ],
            "provider_ids": list(self.provider_ids),
            "execution_authority": False,
            "auto_dispatch": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MultiAgentPlan":
        if not isinstance(payload, dict):
            raise MultiAgentError("multi-agent plan must be a JSON object")
        allowed = {
            "schema_version",
            "plan_id",
            "repository",
            "source_sha",
            "campaign_id",
            "task_id",
            "accepted_plan_fingerprint",
            "assignments",
            "provider_ids",
            "execution_authority",
            "auto_dispatch",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise MultiAgentError(
                f"unknown multi-agent plan fields: {sorted(unknown)}"
            )
        for field in (
            "execution_authority",
            "auto_dispatch",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        ):
            _authority_false(payload, field)
        raw_assignments = payload.get("assignments")
        if not isinstance(raw_assignments, list):
            raise MultiAgentError("assignments must be a list")
        assignments = tuple(
            AgentAssignment.from_dict(item)
            for item in raw_assignments
        )
        plan = cls(
            schema_version=payload.get("schema_version", 0),
            plan_id=payload.get("plan_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            campaign_id=payload.get("campaign_id", ""),
            task_id=payload.get("task_id", ""),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            assignments=assignments,
        )
        provider_ids = payload.get("provider_ids", list(plan.provider_ids))
        if provider_ids != list(plan.provider_ids):
            raise MultiAgentError("provider_ids summary does not match assignments")
        return plan
