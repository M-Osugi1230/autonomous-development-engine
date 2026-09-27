from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .recovery import RecoveryAction, RecoveryBudget, RecoveryFailure, RecoveryProgress, choose_recovery


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    task_id: str
    failure: RecoveryFailure
    action: RecoveryAction
    progress: RecoveryProgress
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "task_id": self.task_id,
            "failure": self.failure.value,
            "action": self.action.value,
            "fingerprint": self.fingerprint,
            "progress": {
                "retries": self.progress.retries,
                "repairs": self.progress.repairs,
                "rebases": self.progress.rebases,
                "replans": self.progress.replans,
                "repeated_failures": self.progress.repeated_failures,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecoveryRecord":
        progress = payload["progress"]
        return cls(
            task_id=str(payload["task_id"]),
            failure=RecoveryFailure(payload["failure"]),
            action=RecoveryAction(payload["action"]),
            fingerprint=str(payload["fingerprint"]),
            progress=RecoveryProgress(**progress),
        )


def advance_recovery(task_id: str, failure: RecoveryFailure | str, fingerprint: str, previous: RecoveryRecord | None = None, budget: RecoveryBudget | None = None) -> RecoveryRecord:
    if not task_id.strip() or not fingerprint.strip():
        raise ValueError("task_id and fingerprint must be non-empty")
    kind = RecoveryFailure(failure)
    prior = previous.progress if previous is not None else RecoveryProgress()
    repeated = prior.repeated_failures + 1 if previous is not None and previous.fingerprint == fingerprint else 1
    progress = RecoveryProgress(
        retries=prior.retries,
        repairs=prior.repairs,
        rebases=prior.rebases,
        replans=prior.replans,
        repeated_failures=repeated,
    )
    action = choose_recovery(kind, progress, budget)
    if action is RecoveryAction.RETRY:
        progress = RecoveryProgress(progress.retries + 1, progress.repairs, progress.rebases, progress.replans, repeated)
    elif action is RecoveryAction.REPAIR:
        progress = RecoveryProgress(progress.retries, progress.repairs + 1, progress.rebases, progress.replans, repeated)
    elif action is RecoveryAction.REBASE:
        progress = RecoveryProgress(progress.retries, progress.repairs, progress.rebases + 1, progress.replans, repeated)
    elif action is RecoveryAction.REPLAN:
        progress = RecoveryProgress(progress.retries, progress.repairs, progress.rebases, progress.replans + 1, repeated)
    return RecoveryRecord(task_id, kind, action, progress, fingerprint)
