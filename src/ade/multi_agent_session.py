from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any

from .multi_agent import AgentAssignment, MultiAgentPlan


class RoleSessionError(ValueError):
    """Trusted per-role session lifecycle validation failed."""


class RoleSessionState(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED_QUOTA = "PAUSED_QUOTA"
    COMPLETED = "COMPLETED"
    HUMAN_WAIT = "HUMAN_WAIT"
    FAILED = "FAILED"


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RoleSessionError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RoleSessionError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RoleSessionError(f"{field} must be ISO-8601") from exc
    return _utc(parsed, field)


def _fingerprint(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RoleSession:
    plan_fingerprint: str
    assignment_fingerprint: str
    assignment_id: str
    role: str
    provider_id: str
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    state: RoleSessionState = RoleSessionState.READY
    provider_session_id: str | None = None
    attempt: int = 0
    resume_after: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RoleSessionError("unsupported role session schema version")
        try:
            state = RoleSessionState(self.state)
        except (TypeError, ValueError) as exc:
            raise RoleSessionError("invalid role session state") from exc
        object.__setattr__(self, "state", state)
        if type(self.attempt) is not int or self.attempt < 0:
            raise RoleSessionError("attempt must be a non-negative integer")
        for name in ("plan_fingerprint", "assignment_fingerprint", "accepted_plan_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise RoleSessionError(f"{name} must be sha256")
        if self.provider_session_id is not None and (
            not isinstance(self.provider_session_id, str) or not self.provider_session_id.strip()
        ):
            raise RoleSessionError("provider_session_id must be non-empty or None")
        if state is RoleSessionState.PAUSED_QUOTA:
            if self.resume_after is None:
                raise RoleSessionError("PAUSED_QUOTA requires resume_after")
            _parse_time(self.resume_after, "resume_after")
        elif self.resume_after is not None:
            raise RoleSessionError(f"{state.value} cannot carry resume_after")
        if state in {RoleSessionState.RUNNING, RoleSessionState.PAUSED_QUOTA, RoleSessionState.COMPLETED} and self.provider_session_id is None:
            raise RoleSessionError(f"{state.value} requires provider_session_id")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_fingerprint": self.plan_fingerprint,
            "assignment_fingerprint": self.assignment_fingerprint,
            "assignment_id": self.assignment_id,
            "role": self.role,
            "provider_id": self.provider_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "state": self.state.value,
            "provider_session_id": self.provider_session_id,
            "attempt": self.attempt,
            "resume_after": self.resume_after,
            "execution_authority": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: object) -> "RoleSession":
        if not isinstance(payload, dict):
            raise RoleSessionError("role session must be a JSON object")
        allowed = {
            "schema_version",
            "plan_fingerprint",
            "assignment_fingerprint",
            "assignment_id",
            "role",
            "provider_id",
            "repository",
            "source_sha",
            "campaign_id",
            "task_id",
            "accepted_plan_fingerprint",
            "state",
            "provider_session_id",
            "attempt",
            "resume_after",
            "execution_authority",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise RoleSessionError(
                f"unknown role session fields: {sorted(unknown)}"
            )
        for field in (
            "execution_authority",
            "merge_authority",
            "acceptance_authority",
            "may_expand_scope",
        ):
            if payload.get(field, False) is not False:
                raise RoleSessionError(
                    f"role session cannot grant {field.replace('_', ' ')}"
                )
        return cls(
            schema_version=payload.get("schema_version", 0),
            plan_fingerprint=payload.get("plan_fingerprint", ""),
            assignment_fingerprint=payload.get(
                "assignment_fingerprint",
                "",
            ),
            assignment_id=payload.get("assignment_id", ""),
            role=payload.get("role", ""),
            provider_id=payload.get("provider_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            campaign_id=payload.get("campaign_id", ""),
            task_id=payload.get("task_id", ""),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            state=payload.get("state", ""),
            provider_session_id=payload.get("provider_session_id"),
            attempt=payload.get("attempt", 0),
            resume_after=payload.get("resume_after"),
        )


def role_session_for_assignment(plan: MultiAgentPlan, assignment: AgentAssignment) -> RoleSession:
    if assignment not in plan.assignments:
        raise RoleSessionError("assignment is not part of multi-agent plan")
    return RoleSession(
        plan_fingerprint=plan.fingerprint(),
        assignment_fingerprint=assignment.fingerprint(),
        assignment_id=assignment.assignment_id,
        role=assignment.role.value,
        provider_id=assignment.provider_id,
        repository=assignment.repository,
        source_sha=assignment.source_sha,
        campaign_id=assignment.campaign_id,
        task_id=assignment.task_id,
        accepted_plan_fingerprint=assignment.accepted_plan_fingerprint,
    )


def start_role_session(
    session: RoleSession,
    *,
    provider_id: str,
    provider_session_id: str,
) -> RoleSession:
    if session.state is not RoleSessionState.READY:
        raise RoleSessionError("only READY role sessions may create a provider session")
    if provider_id != session.provider_id:
        raise RoleSessionError("provider affinity mismatch")
    return replace(
        session,
        state=RoleSessionState.RUNNING,
        provider_session_id=provider_session_id,
        attempt=session.attempt + 1,
    )


def pause_role_session_for_quota(
    session: RoleSession,
    *,
    resume_after: str,
) -> RoleSession:
    if session.state is not RoleSessionState.RUNNING:
        raise RoleSessionError("only RUNNING role sessions may pause for quota")
    _parse_time(resume_after, "resume_after")
    return replace(
        session,
        state=RoleSessionState.PAUSED_QUOTA,
        resume_after=resume_after,
    )


def resume_role_session(
    session: RoleSession,
    *,
    provider_id: str,
    now: datetime,
) -> RoleSession:
    if session.state is not RoleSessionState.PAUSED_QUOTA:
        raise RoleSessionError("only PAUSED_QUOTA role sessions may resume")
    if provider_id != session.provider_id:
        raise RoleSessionError("provider affinity mismatch")
    assert session.resume_after is not None
    if _utc(now, "now") < _parse_time(session.resume_after, "resume_after"):
        raise RoleSessionError("resume_after has not been reached")
    return replace(session, state=RoleSessionState.RUNNING, resume_after=None)


def complete_role_session(session: RoleSession) -> RoleSession:
    if session.state is not RoleSessionState.RUNNING:
        raise RoleSessionError("only RUNNING role sessions may complete")
    return replace(session, state=RoleSessionState.COMPLETED)


def assert_no_duplicate_live_session(
    candidate: RoleSession,
    existing: tuple[RoleSession, ...],
) -> None:
    live = {RoleSessionState.RUNNING, RoleSessionState.PAUSED_QUOTA}
    for current in existing:
        if current.assignment_id == candidate.assignment_id and current.state in live:
            raise RoleSessionError("assignment already has a live provider session")
        if (
            current.plan_fingerprint == candidate.plan_fingerprint
            and current.role == candidate.role
            and current.state in live
        ):
            raise RoleSessionError("role already has a live provider session for this plan")
