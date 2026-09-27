from __future__ import annotations

from typing import Any

from .recovery import RecoveryAction, RecoveryFailure
from .recovery_runtime import RecoveryRecord


def summarize_recovery(record: RecoveryRecord | dict[str, Any]) -> dict[str, Any]:
    """Summarize a RecoveryRecord into a secret-free dictionary.

    Returns a dictionary containing task_id, failure, action, retry/repair/rebase/replan counts,
    and repeated_failures.
    """
    if isinstance(record, dict):
        record = RecoveryRecord.from_dict(record)
    elif not isinstance(record, RecoveryRecord):
        raise TypeError(f"Expected RecoveryRecord or dict, got {type(record).__name__}")

    failure_str = record.failure.value if isinstance(record.failure, RecoveryFailure) else str(record.failure)
    action_str = record.action.value if isinstance(record.action, RecoveryAction) else str(record.action)

    return {
        "task_id": record.task_id,
        "failure": failure_str,
        "action": action_str,
        "retries": record.progress.retries,
        "repairs": record.progress.repairs,
        "rebases": record.progress.rebases,
        "replans": record.progress.replans,
        "repeated_failures": record.progress.repeated_failures,
    }


summarize_recovery_record = summarize_recovery
