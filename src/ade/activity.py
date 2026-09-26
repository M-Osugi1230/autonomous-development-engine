from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .checkpoint import SECRET_PATTERNS


MAX_ACTIVITY_TEXT = 512


class ActivityKind(StrEnum):
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    QUOTA_PAUSED = "QUOTA_PAUSED"
    HUMAN_WAIT = "HUMAN_WAIT"
    DECISION_OPENED = "DECISION_OPENED"
    DECISION_RESOLVED = "DECISION_RESOLVED"
    PR_MERGED = "PR_MERGED"
    MILESTONE = "MILESTONE"
    SYSTEM = "SYSTEM"


def _safe_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if "Traceback (most recent call last)" in normalized:
        raise ValueError(f"{field_name} must not contain tracebacks")
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise ValueError(f"{field_name} contains a forbidden secret pattern")
    if len(normalized) > MAX_ACTIVITY_TEXT:
        raise ValueError(f"{field_name} exceeds {MAX_ACTIVITY_TEXT} characters")
    return normalized


def _validate_timestamp(value: str) -> str:
    normalized = _safe_text(value, field_name="occurred_at")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    return normalized


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    event_id: str
    kind: ActivityKind
    occurred_at: str
    summary: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            _safe_text(self.event_id, field_name="event_id"),
        )
        try:
            kind = ActivityKind(self.kind)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid activity kind: {self.kind}") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "occurred_at", _validate_timestamp(self.occurred_at))
        object.__setattr__(
            self,
            "summary",
            _safe_text(self.summary, field_name="summary"),
        )
        if self.task_id is not None:
            object.__setattr__(
                self,
                "task_id",
                _safe_text(self.task_id, field_name="task_id"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "occurred_at": self.occurred_at,
            "summary": self.summary,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActivityEvent":
        if not isinstance(payload, dict):
            raise ValueError("activity payload must be a JSON object")
        required = {"event_id", "kind", "occurred_at", "summary"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"missing activity keys: {sorted(missing)}")
        return cls(
            event_id=payload["event_id"],
            kind=payload["kind"],
            occurred_at=payload["occurred_at"],
            summary=payload["summary"],
            task_id=payload.get("task_id"),
        )
