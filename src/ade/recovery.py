from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RecoveryFailure(StrEnum):
    CI_FAILURE = "CI_FAILURE"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    TIMEOUT = "TIMEOUT"
    INVALID_IMPLEMENTATION = "INVALID_IMPLEMENTATION"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    REPAIR = "REPAIR"
    REBASE = "REBASE"
    REPLAN = "REPLAN"
    HUMAN_WAIT = "HUMAN_WAIT"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class RecoveryBudget:
    retries: int = 2
    repairs: int = 2
    rebases: int = 1
    replans: int = 1

    def __post_init__(self) -> None:
        for name in ("retries", "repairs", "rebases", "replans"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class RecoveryProgress:
    retries: int = 0
    repairs: int = 0
    rebases: int = 0
    replans: int = 0
    repeated_failures: int = 0


def choose_recovery(failure: RecoveryFailure | str, progress: RecoveryProgress, budget: RecoveryBudget | None = None) -> RecoveryAction:
    kind = RecoveryFailure(failure)
    policy = budget or RecoveryBudget()
    if progress.repeated_failures >= 3:
        return RecoveryAction.HUMAN_WAIT
    if kind is RecoveryFailure.HUMAN_REQUIRED:
        return RecoveryAction.HUMAN_WAIT
    if kind is RecoveryFailure.INFRASTRUCTURE:
        return RecoveryAction.RETRY if progress.retries < policy.retries else RecoveryAction.FAIL
    if kind is RecoveryFailure.MERGE_CONFLICT:
        return RecoveryAction.REBASE if progress.rebases < policy.rebases else RecoveryAction.REPLAN if progress.replans < policy.replans else RecoveryAction.HUMAN_WAIT
    if kind is RecoveryFailure.CI_FAILURE:
        return RecoveryAction.REPAIR if progress.repairs < policy.repairs else RecoveryAction.REPLAN if progress.replans < policy.replans else RecoveryAction.FAIL
    if kind in (RecoveryFailure.TIMEOUT, RecoveryFailure.INVALID_IMPLEMENTATION):
        return RecoveryAction.REPLAN if progress.replans < policy.replans else RecoveryAction.FAIL
    return RecoveryAction.FAIL
