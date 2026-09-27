from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .execution_lease import ExecutionLease, acquire_lease

LEASE_PATH = ".autodev/runtime/execution-lease.json"


class LeaseGitHub(Protocol):
    def get_json_file(self, path: str, *, ref: str = "main"): ...
    def put_json_file(self, path: str, payload: dict, *, sha: str | None, message: str, branch: str = "main") -> None: ...


def _payload(lease: ExecutionLease) -> dict:
    return {"schema_version": 1, "task_id": lease.task_id, "owner_id": lease.owner_id, "attempt": lease.attempt, "acquired_at": lease.acquired_at.isoformat(), "expires_at": lease.expires_at.isoformat()}


def _lease(payload: dict) -> ExecutionLease:
    if payload.get("schema_version") != 1: raise ValueError("execution lease schema_version must be 1")
    return ExecutionLease(task_id=payload["task_id"], owner_id=payload["owner_id"], attempt=payload["attempt"], acquired_at=datetime.fromisoformat(payload["acquired_at"]), expires_at=datetime.fromisoformat(payload["expires_at"]))


def claim_execution(gh: LeaseGitHub, *, task_id: str, owner_id: str, now: datetime, ttl: timedelta, branch: str = "main") -> ExecutionLease:
    current = None; sha = None
    try:
        payload, sha = gh.get_json_file(LEASE_PATH, ref=branch); current = _lease(payload)
    except Exception as exc:
        if "404" not in str(exc): raise
    lease = acquire_lease(task_id=task_id, owner_id=owner_id, now=now, ttl=ttl, current=current)
    if current == lease: return lease
    gh.put_json_file(LEASE_PATH, _payload(lease), sha=sha, message=f"lease: claim {task_id} attempt {lease.attempt}", branch=branch)
    return lease
