from __future__ import annotations

from typing import Any

from .checkpoint import CheckpointState, TaskCheckpoint
from .cycle import CycleResult, CycleSession
from .repair import RepairDisposition
from .repair_planner import RepairPlan

_DISPOSITION_MAP: dict[RepairDisposition, CheckpointState] = {
    RepairDisposition.PAUSE_QUOTA: CheckpointState.PAUSED_QUOTA,
    RepairDisposition.HUMAN_WAIT: CheckpointState.HUMAN_WAIT,
    RepairDisposition.REPLAN: CheckpointState.REPLAN,
    RepairDisposition.FAIL: CheckpointState.FAILED,
}


def checkpoint_for_session(
    session: CycleSession,
    *,
    attempt: int = 0,
    replan_count: int = 0,
    task_id: str | None = None,
) -> TaskCheckpoint:
    if not isinstance(session, CycleSession):
        raise ValueError("session must be an instance of CycleSession")

    if task_id is not None and task_id != session.task_id:
        raise ValueError(f"task_id mismatch: expected '{session.task_id}', got '{task_id}'")

    return TaskCheckpoint(
        task_id=session.task_id,
        state=CheckpointState.RUNNING,
        attempt=attempt,
        replan_count=replan_count,
        provider_session_id=session.session_id,
    )


def checkpoint_for_completed(
    result: CycleResult,
    *,
    attempt: int = 0,
    replan_count: int = 0,
    task_id: str | None = None,
) -> TaskCheckpoint:
    if not isinstance(result, CycleResult):
        raise ValueError("result must be an instance of CycleResult")

    if task_id is not None and task_id != result.task_id:
        raise ValueError(f"task_id mismatch: expected '{result.task_id}', got '{task_id}'")

    return TaskCheckpoint(
        task_id=result.task_id,
        state=CheckpointState.COMPLETED,
        attempt=attempt,
        replan_count=replan_count,
        provider_session_id=result.session_id,
    )


def checkpoint_for_repair_plan(
    plan: RepairPlan,
    *,
    provider_session_id: str | None = None,
    resume_after: str | None = None,
    task_id: str | None = None,
) -> TaskCheckpoint:
    if not isinstance(plan, RepairPlan):
        raise ValueError("plan must be an instance of RepairPlan")

    if task_id is not None and task_id != plan.task_id:
        raise ValueError(f"task_id mismatch: expected '{plan.task_id}', got '{task_id}'")

    if plan.disposition is RepairDisposition.RETRY:
        raise ValueError(
            f"RETRY disposition is non-terminal and cannot transition to checkpoint: {plan.disposition}"
        )

    target_state = _DISPOSITION_MAP.get(plan.disposition)
    if target_state is None:
        raise ValueError(f"unhandled or invalid repair disposition: {plan.disposition}")

    return TaskCheckpoint(
        task_id=plan.task_id,
        state=target_state,
        attempt=plan.next_attempt,
        replan_count=plan.next_replan_count,
        provider_session_id=provider_session_id,
        last_failure_kind=plan.failure_kind,
        last_error=plan.error_summary,
        resume_after=resume_after,
    )


# Aliases for flexible import / functional naming conventions
checkpoint_from_session = checkpoint_for_session
checkpoint_from_completed = checkpoint_for_completed
checkpoint_from_repair_plan = checkpoint_for_repair_plan
