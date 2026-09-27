from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from .repair import FailureKind, RepairDisposition, RepairPolicy, decide_repair

class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    REPAIR_TASK = "REPAIR_TASK"
    REBASE_REPLAN = "REBASE_REPLAN"
    WAIT = "WAIT"
    HUMAN_WAIT = "HUMAN_WAIT"
    FAIL = "FAIL"

@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    failure_kind: FailureKind
    action: RecoveryAction
    attempt: int
    replan_count: int

def decide_recovery_action(failure_kind: FailureKind | str, *, attempt: int, replan_count: int, policy: RepairPolicy | None = None) -> RecoveryDecision:
    kind = FailureKind(failure_kind)
    disposition = decide_repair(kind, attempt, replan_count, policy)
    if disposition is RepairDisposition.RETRY:
        action = RecoveryAction.RETRY
    elif disposition is RepairDisposition.PAUSE_QUOTA:
        action = RecoveryAction.WAIT
    elif disposition is RepairDisposition.HUMAN_WAIT:
        action = RecoveryAction.HUMAN_WAIT
    elif disposition is RepairDisposition.REPLAN:
        action = RecoveryAction.REBASE_REPLAN if kind is FailureKind.MERGE_CONFLICT else RecoveryAction.REPAIR_TASK
    else:
        action = RecoveryAction.FAIL
    return RecoveryDecision(kind, action, attempt, replan_count)
