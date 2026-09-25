from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .cycle import CycleFailed, CycleTimedOut, HumanInputRequired
from .providers.base import ProviderError, ProviderQuotaError


class FailureKind(StrEnum):
    PROVIDER_QUOTA = "PROVIDER_QUOTA"
    HUMAN_INPUT = "HUMAN_INPUT"
    CYCLE_TIMEOUT = "CYCLE_TIMEOUT"
    CYCLE_FAILED = "CYCLE_FAILED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN = "UNKNOWN"


class RepairDisposition(StrEnum):
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    PAUSE_QUOTA = "PAUSE_QUOTA"
    HUMAN_WAIT = "HUMAN_WAIT"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    max_retries: int = 2
    max_replans: int = 1

    def __post_init__(self) -> None:
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if type(self.max_replans) is not int or self.max_replans < 0:
            raise ValueError("max_replans must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class RepairState:
    task_id: str
    attempt: int
    replan_count: int
    last_failure_kind: FailureKind
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if type(self.replan_count) is not int or self.replan_count < 0:
            raise ValueError("replan_count must be a non-negative integer")

        try:
            kind_enum = FailureKind(self.last_failure_kind)
        except (ValueError, TypeError):
            raise ValueError(f"invalid last_failure_kind: {self.last_failure_kind}")
        object.__setattr__(self, "last_failure_kind", kind_enum)

        if self.last_error is not None and not isinstance(self.last_error, str):
            raise ValueError("last_error must be a string or None")


def decide_repair(
    failure_kind: FailureKind | str,
    attempt: int,
    replan_count: int,
    policy: RepairPolicy | None = None,
) -> RepairDisposition:
    if policy is None:
        policy = RepairPolicy()
    elif not isinstance(policy, RepairPolicy):
        raise ValueError("policy must be an instance of RepairPolicy")

    if type(attempt) is not int or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")
    if type(replan_count) is not int or replan_count < 0:
        raise ValueError("replan_count must be a non-negative integer")

    try:
        kind = FailureKind(failure_kind)
    except (ValueError, TypeError):
        kind = FailureKind.UNKNOWN

    if kind is FailureKind.PROVIDER_QUOTA:
        return RepairDisposition.PAUSE_QUOTA

    if kind is FailureKind.HUMAN_INPUT:
        return RepairDisposition.HUMAN_WAIT

    if kind in (FailureKind.CYCLE_TIMEOUT, FailureKind.CYCLE_FAILED, FailureKind.PROVIDER_ERROR):
        if attempt < policy.max_retries:
            return RepairDisposition.RETRY
        if replan_count < policy.max_replans:
            return RepairDisposition.REPLAN
        return RepairDisposition.FAIL

    if kind is FailureKind.VALIDATION_ERROR:
        if replan_count < policy.max_replans:
            return RepairDisposition.REPLAN
        return RepairDisposition.FAIL

    return RepairDisposition.FAIL


def classify_failure(exc: BaseException) -> FailureKind:
    if isinstance(exc, ProviderQuotaError):
        return FailureKind.PROVIDER_QUOTA
    if isinstance(exc, HumanInputRequired):
        return FailureKind.HUMAN_INPUT
    if isinstance(exc, CycleTimedOut):
        return FailureKind.CYCLE_TIMEOUT
    if isinstance(exc, CycleFailed):
        return FailureKind.CYCLE_FAILED
    if isinstance(exc, ProviderError):
        return FailureKind.PROVIDER_ERROR
    if isinstance(exc, ValueError):
        return FailureKind.VALIDATION_ERROR
    return FailureKind.UNKNOWN
