from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import json
from typing import Any

from .checkpoint import MAX_ERROR_LENGTH, SECRET_PATTERNS
from .execution_lease import ExecutionLease, acquire_lease
from .multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from .provider_availability import (
    ProviderAvailabilityRecord,
    evaluate_availability,
)
from .provider_router import ProviderAvailability


class MultiAgentRuntimeError(ValueError):
    """Trusted role-session lifecycle validation failed."""


class RoleSessionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED_QUOTA = "PAUSED_QUOTA"
    HUMAN_WAIT = "HUMAN_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RoleSessionAction(StrEnum):
    START_NEW = "START_NEW"
    MONITOR = "MONITOR"
    WAIT_QUOTA = "WAIT_QUOTA"
    HUMAN_WAIT = "HUMAN_WAIT"
    BLOCKED = "BLOCKED"
    NOOP = "NOOP"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _utc(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MultiAgentRuntimeError(
            f"{field} must be timezone-aware"
        )
    return value.astimezone(UTC)


def _parse_timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MultiAgentRuntimeError(
            f"{field} must be a non-empty ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise MultiAgentRuntimeError(
            f"{field} must be a valid ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MultiAgentRuntimeError(
            f"{field} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _sanitize_error(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MultiAgentRuntimeError(
            "last_error must be non-empty text or None"
        )
    normalized = value.strip()
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise MultiAgentRuntimeError(
                "last_error contains forbidden secret patterns"
            )
    return normalized[:MAX_ERROR_LENGTH]


@dataclass(frozen=True, slots=True)
class RoleSessionCheckpoint:
    assignment_id: str
    role: AgentRole
    provider_id: str
    repository: str
    source_sha: str
    campaign_id: str
    task_id: str
    accepted_plan_fingerprint: str
    multi_agent_plan_fingerprint: str
    state: RoleSessionState
    attempt: int = 0
    provider_session_id: str | None = None
    resume_after: str | None = None
    last_error: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentRuntimeError(
                "unsupported role checkpoint schema version"
            )
        if not isinstance(self.role, AgentRole):
            raise MultiAgentRuntimeError("role must be AgentRole")
        try:
            state = RoleSessionState(self.state)
        except (ValueError, TypeError) as exc:
            raise MultiAgentRuntimeError(
                "invalid role checkpoint state"
            ) from exc
        object.__setattr__(self, "state", state)

        for field in (
            "assignment_id",
            "provider_id",
            "repository",
            "source_sha",
            "campaign_id",
            "task_id",
            "accepted_plan_fingerprint",
            "multi_agent_plan_fingerprint",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise MultiAgentRuntimeError(
                    f"{field} must be a non-empty string"
                )

        if type(self.attempt) is not int or self.attempt < 0:
            raise MultiAgentRuntimeError(
                "attempt must be a non-negative integer"
            )
        if self.provider_session_id is not None:
            if (
                not isinstance(self.provider_session_id, str)
                or not self.provider_session_id.strip()
            ):
                raise MultiAgentRuntimeError(
                    "provider_session_id must be non-empty or None"
                )
        if self.resume_after is not None:
            _parse_timestamp(self.resume_after, field="resume_after")
        object.__setattr__(
            self,
            "last_error",
            _sanitize_error(self.last_error),
        )

        if state is RoleSessionState.PENDING:
            if (
                self.provider_session_id is not None
                or self.resume_after is not None
                or self.last_error is not None
            ):
                raise MultiAgentRuntimeError(
                    "PENDING checkpoint cannot carry session/pause data"
                )
        elif state is RoleSessionState.RUNNING:
            if self.provider_session_id is None:
                raise MultiAgentRuntimeError(
                    "RUNNING checkpoint requires provider_session_id"
                )
            if self.resume_after is not None:
                raise MultiAgentRuntimeError(
                    "RUNNING checkpoint cannot carry resume_after"
                )
        elif state is RoleSessionState.PAUSED_QUOTA:
            if self.resume_after is None:
                raise MultiAgentRuntimeError(
                    "PAUSED_QUOTA checkpoint requires resume_after"
                )
        elif state is RoleSessionState.HUMAN_WAIT:
            if self.resume_after is not None:
                raise MultiAgentRuntimeError(
                    "HUMAN_WAIT checkpoint cannot carry resume_after"
                )
        elif state is RoleSessionState.COMPLETED:
            if self.provider_session_id is None:
                raise MultiAgentRuntimeError(
                    "COMPLETED checkpoint requires provider_session_id"
                )
            if self.resume_after is not None or self.last_error is not None:
                raise MultiAgentRuntimeError(
                    "COMPLETED checkpoint cannot carry failure data"
                )
        elif state is RoleSessionState.FAILED:
            if self.resume_after is not None:
                raise MultiAgentRuntimeError(
                    "FAILED checkpoint cannot carry resume_after"
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
            "multi_agent_plan_fingerprint": (
                self.multi_agent_plan_fingerprint
            ),
            "state": self.state.value,
            "attempt": self.attempt,
            "provider_session_id": self.provider_session_id,
            "resume_after": self.resume_after,
            "last_error": self.last_error,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "RoleSessionCheckpoint":
        if not isinstance(payload, dict):
            raise MultiAgentRuntimeError(
                "role checkpoint must be a JSON object"
            )
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
            "multi_agent_plan_fingerprint",
            "state",
            "attempt",
            "provider_session_id",
            "resume_after",
            "last_error",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise MultiAgentRuntimeError(
                f"unknown role checkpoint fields: {sorted(unknown)}"
            )
        try:
            role = AgentRole(payload.get("role"))
        except (ValueError, TypeError) as exc:
            raise MultiAgentRuntimeError(
                "role checkpoint role is invalid"
            ) from exc
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
            multi_agent_plan_fingerprint=payload.get(
                "multi_agent_plan_fingerprint",
                "",
            ),
            state=payload.get("state", ""),
            attempt=payload.get("attempt", -1),
            provider_session_id=payload.get("provider_session_id"),
            resume_after=payload.get("resume_after"),
            last_error=payload.get("last_error"),
        )


def pending_role_checkpoint(
    plan: MultiAgentPlan,
    assignment_id: str,
) -> RoleSessionCheckpoint:
    if not isinstance(plan, MultiAgentPlan):
        raise MultiAgentRuntimeError(
            "plan must be MultiAgentPlan"
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
        raise MultiAgentRuntimeError(
            "assignment_id is not present in MultiAgentPlan"
        )
    return RoleSessionCheckpoint(
        assignment_id=assignment.assignment_id,
        role=assignment.role,
        provider_id=assignment.provider_id,
        repository=plan.repository,
        source_sha=plan.source_sha,
        campaign_id=plan.campaign_id,
        task_id=plan.task_id,
        accepted_plan_fingerprint=plan.accepted_plan_fingerprint,
        multi_agent_plan_fingerprint=plan.fingerprint(),
        state=RoleSessionState.PENDING,
    )


def validate_role_checkpoint(
    checkpoint: RoleSessionCheckpoint,
    plan: MultiAgentPlan,
) -> AgentAssignment:
    if not isinstance(checkpoint, RoleSessionCheckpoint):
        raise MultiAgentRuntimeError(
            "checkpoint must be RoleSessionCheckpoint"
        )
    if not isinstance(plan, MultiAgentPlan):
        raise MultiAgentRuntimeError(
            "plan must be MultiAgentPlan"
        )
    if checkpoint.multi_agent_plan_fingerprint != plan.fingerprint():
        raise MultiAgentRuntimeError(
            "role checkpoint MultiAgentPlan fingerprint mismatch"
        )
    expected_anchor = (
        plan.repository,
        plan.source_sha,
        plan.campaign_id,
        plan.task_id,
        plan.accepted_plan_fingerprint,
    )
    actual_anchor = (
        checkpoint.repository,
        checkpoint.source_sha,
        checkpoint.campaign_id,
        checkpoint.task_id,
        checkpoint.accepted_plan_fingerprint,
    )
    if actual_anchor != expected_anchor:
        raise MultiAgentRuntimeError(
            "role checkpoint trust anchor mismatch"
        )
    assignment = next(
        (
            item
            for item in plan.assignments
            if item.assignment_id == checkpoint.assignment_id
        ),
        None,
    )
    if assignment is None:
        raise MultiAgentRuntimeError(
            "role checkpoint assignment is not in MultiAgentPlan"
        )
    if checkpoint.role is not assignment.role:
        raise MultiAgentRuntimeError(
            "role checkpoint role mismatch"
        )
    if checkpoint.provider_id != assignment.provider_id:
        raise MultiAgentRuntimeError(
            "role checkpoint provider affinity mismatch"
        )
    return assignment


def mark_role_running(
    checkpoint: RoleSessionCheckpoint,
    *,
    provider_session_id: str,
) -> RoleSessionCheckpoint:
    if checkpoint.state not in {
        RoleSessionState.PENDING,
        RoleSessionState.PAUSED_QUOTA,
    }:
        raise MultiAgentRuntimeError(
            "only PENDING or PAUSED_QUOTA may start a provider session"
        )
    if (
        not isinstance(provider_session_id, str)
        or not provider_session_id.strip()
    ):
        raise MultiAgentRuntimeError(
            "provider_session_id must be non-empty"
        )
    return replace(
        checkpoint,
        state=RoleSessionState.RUNNING,
        attempt=checkpoint.attempt + 1,
        provider_session_id=provider_session_id,
        resume_after=None,
        last_error=None,
    )


def pause_role_for_quota(
    checkpoint: RoleSessionCheckpoint,
    *,
    resume_after: str,
    last_error: str,
) -> RoleSessionCheckpoint:
    if checkpoint.state not in {
        RoleSessionState.PENDING,
        RoleSessionState.RUNNING,
        RoleSessionState.PAUSED_QUOTA,
    }:
        raise MultiAgentRuntimeError(
            "role cannot enter quota pause from terminal state"
        )
    _parse_timestamp(resume_after, field="resume_after")
    return replace(
        checkpoint,
        state=RoleSessionState.PAUSED_QUOTA,
        resume_after=resume_after,
        last_error=last_error,
    )


def complete_role_session(
    checkpoint: RoleSessionCheckpoint,
) -> RoleSessionCheckpoint:
    if checkpoint.state is not RoleSessionState.RUNNING:
        raise MultiAgentRuntimeError(
            "only RUNNING role session may complete"
        )
    return replace(
        checkpoint,
        state=RoleSessionState.COMPLETED,
        resume_after=None,
        last_error=None,
    )


def decide_role_session_action(
    *,
    checkpoint: RoleSessionCheckpoint,
    plan: MultiAgentPlan,
    availability: ProviderAvailabilityRecord,
    now: datetime,
) -> RoleSessionAction:
    validate_role_checkpoint(checkpoint, plan)
    if not isinstance(availability, ProviderAvailabilityRecord):
        raise MultiAgentRuntimeError(
            "availability must be ProviderAvailabilityRecord"
        )
    if availability.provider_id != checkpoint.provider_id:
        raise MultiAgentRuntimeError(
            "availability provider violates role affinity"
        )
    now_utc = _utc(now, field="now")

    if checkpoint.state is RoleSessionState.COMPLETED:
        return RoleSessionAction.NOOP
    if checkpoint.state is RoleSessionState.FAILED:
        return RoleSessionAction.BLOCKED
    if checkpoint.state is RoleSessionState.HUMAN_WAIT:
        return RoleSessionAction.HUMAN_WAIT
    if checkpoint.state is RoleSessionState.RUNNING:
        return RoleSessionAction.MONITOR
    if checkpoint.state is RoleSessionState.PAUSED_QUOTA:
        assert checkpoint.resume_after is not None
        due = _parse_timestamp(
            checkpoint.resume_after,
            field="resume_after",
        )
        if now_utc < due:
            return RoleSessionAction.WAIT_QUOTA
        if checkpoint.provider_session_id is not None:
            return RoleSessionAction.MONITOR
        return RoleSessionAction.START_NEW

    snapshot = evaluate_availability(availability, now=now_utc)
    if snapshot.availability is ProviderAvailability.AVAILABLE:
        return RoleSessionAction.START_NEW
    if snapshot.availability in {
        ProviderAvailability.QUOTA_PAUSED,
        ProviderAvailability.TEMPORARILY_UNAVAILABLE,
    }:
        return RoleSessionAction.WAIT_QUOTA
    return RoleSessionAction.BLOCKED


def role_lease_task_id(
    plan: MultiAgentPlan,
    assignment: AgentAssignment,
) -> str:
    if assignment not in plan.assignments:
        raise MultiAgentRuntimeError(
            "assignment is not present in MultiAgentPlan"
        )
    digest = _fingerprint(
        {
            "plan_fingerprint": plan.fingerprint(),
            "assignment_fingerprint": assignment.fingerprint(),
        }
    )
    return (
        f"{plan.task_id}.role.{assignment.role.value.lower()}."
        f"{digest[:12]}"
    )


@dataclass(frozen=True, slots=True)
class MultiAgentLeaseState:
    leases: tuple[ExecutionLease, ...] = ()

    def __post_init__(self) -> None:
        leases = tuple(self.leases)
        if any(not isinstance(item, ExecutionLease) for item in leases):
            raise MultiAgentRuntimeError(
                "leases must contain ExecutionLease values"
            )
        ids = [item.task_id for item in leases]
        if len(ids) != len(set(ids)):
            raise MultiAgentRuntimeError(
                "role lease task IDs must be unique"
            )
        object.__setattr__(
            self,
            "leases",
            tuple(sorted(leases, key=lambda item: item.task_id)),
        )

    def get(self, lease_task_id: str) -> ExecutionLease | None:
        return next(
            (
                item
                for item in self.leases
                if item.task_id == lease_task_id
            ),
            None,
        )

    def acquire(
        self,
        *,
        plan: MultiAgentPlan,
        assignment_id: str,
        owner_id: str,
        now: datetime,
        ttl: timedelta,
    ) -> tuple["MultiAgentLeaseState", ExecutionLease]:
        assignment = next(
            (
                item
                for item in plan.assignments
                if item.assignment_id == assignment_id
            ),
            None,
        )
        if assignment is None:
            raise MultiAgentRuntimeError(
                "assignment_id is not present in MultiAgentPlan"
            )
        lease_task_id = role_lease_task_id(plan, assignment)
        current = self.get(lease_task_id)
        lease = acquire_lease(
            task_id=lease_task_id,
            owner_id=owner_id,
            now=now,
            ttl=ttl,
            current=current,
        )
        retained = tuple(
            item
            for item in self.leases
            if item.task_id != lease_task_id
        )
        return (
            MultiAgentLeaseState(leases=retained + (lease,)),
            lease,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "leases": [
                {
                    "task_id": item.task_id,
                    "owner_id": item.owner_id,
                    "attempt": item.attempt,
                    "acquired_at": item.acquired_at.isoformat(),
                    "expires_at": item.expires_at.isoformat(),
                }
                for item in self.leases
            ],
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())
