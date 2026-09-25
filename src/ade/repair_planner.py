from __future__ import annotations

from dataclasses import dataclass

from .repair import (
    FailureKind,
    RepairDisposition,
    RepairPolicy,
    classify_failure,
    decide_repair,
)

MAX_ERROR_SUMMARY_LENGTH = 256


@dataclass(frozen=True, slots=True)
class RepairPlan:
    task_id: str
    failure_kind: FailureKind
    disposition: RepairDisposition
    next_attempt: int
    next_replan_count: int
    error_summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        if type(self.next_attempt) is not int or self.next_attempt < 0:
            raise ValueError("next_attempt must be a non-negative integer")

        if type(self.next_replan_count) is not int or self.next_replan_count < 0:
            raise ValueError("next_replan_count must be a non-negative integer")

        if not isinstance(self.error_summary, str) or not self.error_summary.strip():
            raise ValueError("error_summary must be a non-empty string")

        try:
            kind_enum = FailureKind(self.failure_kind)
        except (ValueError, TypeError):
            raise ValueError(f"invalid failure_kind: {self.failure_kind}")
        object.__setattr__(self, "failure_kind", kind_enum)

        try:
            disp_enum = RepairDisposition(self.disposition)
        except (ValueError, TypeError):
            raise ValueError(f"invalid disposition: {self.disposition}")
        object.__setattr__(self, "disposition", disp_enum)


def _build_error_summary(exc: BaseException) -> str:
    msg = str(exc).strip()
    if msg:
        lines = [line.strip() for line in msg.splitlines() if line.strip()]
        if lines:
            first_line = lines[0]
            prefix = f"{type(exc).__name__}:"
            if first_line.startswith(prefix):
                summary = first_line
            else:
                summary = f"{type(exc).__name__}: {first_line}"
        else:
            summary = type(exc).__name__
    else:
        summary = type(exc).__name__

    if len(summary) > MAX_ERROR_SUMMARY_LENGTH:
        summary = summary[:MAX_ERROR_SUMMARY_LENGTH]

    return summary


def plan_repair(
    task_id: str,
    exc: BaseException,
    attempt: int,
    replan_count: int,
    policy: RepairPolicy | None = None,
) -> RepairPlan:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")

    if not isinstance(exc, BaseException):
        raise ValueError("exc must be an instance of BaseException")

    if type(attempt) is not int or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")

    if type(replan_count) is not int or replan_count < 0:
        raise ValueError("replan_count must be a non-negative integer")

    failure_kind = classify_failure(exc)
    disposition = decide_repair(
        failure_kind=failure_kind,
        attempt=attempt,
        replan_count=replan_count,
        policy=policy,
    )

    next_attempt = attempt
    next_replan_count = replan_count

    if disposition is RepairDisposition.RETRY:
        next_attempt = attempt + 1
    elif disposition is RepairDisposition.REPLAN:
        next_replan_count = replan_count + 1

    error_summary = _build_error_summary(exc)

    return RepairPlan(
        task_id=task_id,
        failure_kind=failure_kind,
        disposition=disposition,
        next_attempt=next_attempt,
        next_replan_count=next_replan_count,
        error_summary=error_summary,
    )
