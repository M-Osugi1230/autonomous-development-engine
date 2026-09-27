from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    task_id: str
    owner_id: str
    attempt: int
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("owner_id must be a non-empty string")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        acquired = _utc(self.acquired_at, "acquired_at")
        expires = _utc(self.expires_at, "expires_at")
        if expires <= acquired:
            raise ValueError("expires_at must be after acquired_at")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "expires_at", expires)

    def is_live(self, now: datetime) -> bool:
        return _utc(now, "now") < self.expires_at


def acquire_lease(*, task_id: str, owner_id: str, now: datetime, ttl: timedelta, current: ExecutionLease | None = None) -> ExecutionLease:
    now = _utc(now, "now")
    if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if current is not None:
        if current.task_id != task_id:
            return ExecutionLease(
                task_id=task_id,
                owner_id=owner_id,
                attempt=1,
                acquired_at=now,
                expires_at=now + ttl,
            )
        if current.is_live(now):
            if current.owner_id == owner_id:
                return current
            raise RuntimeError("task already has a live execution lease")
        attempt = current.attempt + 1
    else:
        attempt = 1
    return ExecutionLease(task_id=task_id, owner_id=owner_id, attempt=attempt, acquired_at=now, expires_at=now + ttl)


def renew_lease(lease: ExecutionLease, *, owner_id: str, now: datetime, ttl: timedelta) -> ExecutionLease:
    now = _utc(now, "now")
    if owner_id != lease.owner_id:
        raise RuntimeError("only the current lease owner may renew")
    if not lease.is_live(now):
        raise RuntimeError("expired lease cannot be renewed")
    if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    return replace(lease, expires_at=now + ttl)


def release_lease(lease: ExecutionLease, *, owner_id: str) -> None:
    if owner_id != lease.owner_id:
        raise RuntimeError("only the current lease owner may release")
