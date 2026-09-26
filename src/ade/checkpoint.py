from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from .repair import FailureKind

MAX_ERROR_LENGTH = 1024

# Common token/secret patterns to sanitize/detect if accidentally passed
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9_]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
]


class CheckpointState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED_QUOTA = "PAUSED_QUOTA"
    HUMAN_WAIT = "HUMAN_WAIT"
    REPLAN = "REPLAN"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class TaskCheckpoint:
    task_id: str
    state: CheckpointState
    attempt: int
    replan_count: int
    provider_session_id: str | None = None
    provider_id: str | None = None
    last_failure_kind: FailureKind | None = None
    last_error: str | None = None
    resume_after: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        try:
            state_enum = CheckpointState(self.state)
        except (ValueError, TypeError):
            raise ValueError(f"invalid state: {self.state}")
        object.__setattr__(self, "state", state_enum)

        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")

        if type(self.replan_count) is not int or self.replan_count < 0:
            raise ValueError("replan_count must be a non-negative integer")

        if self.provider_session_id is not None:
            if not isinstance(self.provider_session_id, str) or not self.provider_session_id.strip():
                raise ValueError("provider_session_id must be a non-empty string or None")

        if self.provider_id is not None:
            if not isinstance(self.provider_id, str) or not self.provider_id:
                raise ValueError("provider_id must be a non-empty string or None")
            if self.provider_id != self.provider_id.strip():
                raise ValueError(
                    "provider_id must not contain leading or trailing whitespace"
                )

        if self.last_failure_kind is not None:
            try:
                kind_enum = FailureKind(self.last_failure_kind)
            except (ValueError, TypeError):
                raise ValueError(f"invalid last_failure_kind: {self.last_failure_kind}")
            object.__setattr__(self, "last_failure_kind", kind_enum)

        if self.last_error is not None:
            if not isinstance(self.last_error, str):
                raise ValueError("last_error must be a string or None")
            error_str = self.last_error.strip()
            if not error_str:
                raise ValueError("last_error must not be empty or whitespace-only if provided")
            for pattern in SECRET_PATTERNS:
                if pattern.search(error_str):
                    raise ValueError("last_error contains forbidden secret patterns")
            if len(error_str) > MAX_ERROR_LENGTH:
                error_str = error_str[:MAX_ERROR_LENGTH]
            object.__setattr__(self, "last_error", error_str)

        if self.resume_after is not None:
            if not isinstance(self.resume_after, str) or not self.resume_after.strip():
                raise ValueError("resume_after must be a non-empty string or None")
            try:
                # Standard library ISO-8601 parsing
                datetime.fromisoformat(self.resume_after)
            except (ValueError, TypeError):
                raise ValueError(f"invalid ISO-8601 resume_after timestamp: {self.resume_after}")

        # Check state/field consistency constraints
        if self.state is CheckpointState.COMPLETED:
            if self.last_failure_kind is not None:
                raise ValueError("COMPLETED state cannot have last_failure_kind")
            if self.last_error is not None:
                raise ValueError("COMPLETED state cannot have last_error")
            if self.resume_after is not None:
                raise ValueError("COMPLETED state cannot have resume_after timestamp")

        if self.state is CheckpointState.RUNNING:
            if self.resume_after is not None:
                raise ValueError("RUNNING state cannot have resume_after timestamp")

        if self.state is CheckpointState.HUMAN_WAIT:
            if self.resume_after is not None:
                raise ValueError("HUMAN_WAIT state cannot have resume_after timestamp")

        if self.state is CheckpointState.REPLAN:
            if self.resume_after is not None:
                raise ValueError("REPLAN state cannot have resume_after timestamp")

        if self.state is CheckpointState.FAILED:
            if self.resume_after is not None:
                raise ValueError("FAILED state cannot have resume_after timestamp")

        if self.state is CheckpointState.PAUSED_QUOTA:
            # PAUSED_QUOTA usually comes with PROVIDER_QUOTA failure kind if specified, but if specified must match
            if self.last_failure_kind is not None and self.last_failure_kind is not FailureKind.PROVIDER_QUOTA:
                raise ValueError(f"PAUSED_QUOTA state cannot have failure kind {self.last_failure_kind}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "attempt": self.attempt,
            "replan_count": self.replan_count,
            "provider_session_id": self.provider_session_id,
            "provider_id": self.provider_id,
            "last_failure_kind": self.last_failure_kind.value if self.last_failure_kind is not None else None,
            "last_error": self.last_error,
            "resume_after": self.resume_after,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskCheckpoint:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")

        required_keys = {"task_id", "state", "attempt", "replan_count"}
        missing_keys = required_keys - set(payload.keys())
        if missing_keys:
            raise ValueError(f"missing required keys in payload: {sorted(missing_keys)}")

        return cls(
            task_id=payload["task_id"],
            state=payload["state"],
            attempt=payload["attempt"],
            replan_count=payload["replan_count"],
            provider_session_id=payload.get("provider_session_id"),
            provider_id=payload.get("provider_id"),
            last_failure_kind=payload.get("last_failure_kind"),
            last_error=payload.get("last_error"),
            resume_after=payload.get("resume_after"),
        )
