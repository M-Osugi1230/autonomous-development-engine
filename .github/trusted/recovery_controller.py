from __future__ import annotations

import hashlib
from typing import Any

from ade.recovery import RecoveryAction, RecoveryFailure
from ade.recovery_runtime import RecoveryRecord, advance_recovery
from github_client import GitHubClient, GitHubError

RECOVERY_PATH = ".autodev/runtime/recovery.json"


def safe_fingerprint(kind: RecoveryFailure | str, detail: str) -> str:
    normalized = " ".join(detail.strip().split())[:512]
    return hashlib.sha256(f"{RecoveryFailure(kind).value}:{normalized}".encode()).hexdigest()


def load_recovery(api: GitHubClient) -> tuple[RecoveryRecord | None, str | None]:
    try:
        payload, sha = api.get_json_file(RECOVERY_PATH)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None, None
        raise
    return RecoveryRecord.from_dict(payload), sha


def plan_and_persist(api: GitHubClient, *, task_id: str, failure: RecoveryFailure | str, detail: str) -> RecoveryRecord:
    previous, sha = load_recovery(api)
    if previous is not None and previous.task_id != task_id:
        previous = None
    record = advance_recovery(task_id, failure, safe_fingerprint(failure, detail), previous)
    api.put_json_file(RECOVERY_PATH, record.to_dict(), sha=sha, message=f"recovery: {task_id} {record.action.value.lower()}")
    return record


def apply_project_status(api: GitHubClient, record: RecoveryRecord) -> None:
    state, sha = api.get_json_file(".autodev/state.json")
    if state.get("current_task_id") != record.task_id:
        raise RuntimeError("recovery task does not match current project task")
    metadata = dict(state.get("metadata", {}))
    metadata["recovery_action"] = record.action.value
    metadata["recovery_failure"] = record.failure.value
    if record.action is RecoveryAction.HUMAN_WAIT:
        state["status"] = "HUMAN_WAIT"
    elif record.action is RecoveryAction.FAIL:
        state["status"] = "FAILED"
    else:
        state["status"] = "READY"
    state["metadata"] = metadata
    api.put_json_file(".autodev/state.json", state, sha=sha, message=f"state: recovery {record.action.value.lower()}")
