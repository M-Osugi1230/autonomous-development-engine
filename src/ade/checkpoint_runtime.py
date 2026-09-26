from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .checkpoint import SECRET_PATTERNS, CheckpointState, TaskCheckpoint
from .checkpoint_store import CheckpointStore
from .checkpoint_transition import (
    checkpoint_for_completed,
    checkpoint_for_repair_plan,
    checkpoint_for_session,
)
from .cycle import (
    CycleResult,
    CycleSession,
    CycleTask,
    monitor_cycle_session,
    start_cycle_session,
)
from .repair import RepairDisposition, RepairPolicy
from .repair_planner import RepairPlan, plan_repair


@dataclass(frozen=True, slots=True)
class CheckpointedCycleExecution:
    result: CycleResult | None = None
    checkpoint: TaskCheckpoint | None = None
    history: tuple[RepairPlan, ...] = ()

    def __post_init__(self) -> None:
        if self.result is None and self.checkpoint is None:
            raise ValueError("At least one of result or checkpoint must be provided")

        if self.result is not None and not isinstance(self.result, CycleResult):
            raise ValueError("result must be an instance of CycleResult or None")

        if self.checkpoint is not None and not isinstance(self.checkpoint, TaskCheckpoint):
            raise ValueError("checkpoint must be an instance of TaskCheckpoint or None")

        if not isinstance(self.history, (tuple, list)):
            raise ValueError("history must be a tuple or list of RepairPlan instances")

        history_tuple = tuple(self.history)
        for item in history_tuple:
            if not isinstance(item, RepairPlan):
                raise ValueError("All history items must be RepairPlan instances")

        object.__setattr__(self, "history", history_tuple)


def _sanitize_repair_plan(plan: RepairPlan) -> RepairPlan:
    summary = plan.error_summary
    if "Traceback (most recent call last)" in summary:
        summary = summary.split("Traceback (most recent call last)")[0].strip()
        if not summary:
            summary = f"{plan.failure_kind.value} failure"
    for pattern in SECRET_PATTERNS:
        summary = pattern.sub("[REDACTED]", summary)

    if not summary.strip():
        summary = f"{plan.failure_kind.value} failure"

    if summary == plan.error_summary:
        return plan

    return RepairPlan(
        task_id=plan.task_id,
        failure_kind=plan.failure_kind,
        disposition=plan.disposition,
        next_attempt=plan.next_attempt,
        next_replan_count=plan.next_replan_count,
        error_summary=summary,
    )


def run_checkpointed_cycle(
    provider: Any,
    *,
    task: CycleTask,
    source_name: str,
    store: CheckpointStore,
    policy: RepairPolicy | None = None,
    existing_checkpoint: TaskCheckpoint | None = None,
    load_existing_checkpoint: bool = True,
    provider_id: str | None = None,
    start_fn: Callable[..., CycleSession] = start_cycle_session,
    monitor_fn: Callable[..., CycleResult] = monitor_cycle_session,
) -> CheckpointedCycleExecution:
    if provider is None:
        raise ValueError("provider must not be None")

    if not isinstance(task, CycleTask):
        raise ValueError("task must be an instance of CycleTask")
    task.validate()

    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("source_name must be a non-empty string")

    if store is None or not hasattr(store, "save"):
        raise ValueError("store must be an instance of CheckpointStore")

    if policy is None:
        resolved_policy = RepairPolicy()
    elif isinstance(policy, RepairPolicy):
        resolved_policy = policy
    else:
        raise ValueError("policy must be an instance of RepairPolicy or None")

    if existing_checkpoint is not None and not isinstance(existing_checkpoint, TaskCheckpoint):
        raise ValueError("existing_checkpoint must be an instance of TaskCheckpoint or None")

    if type(load_existing_checkpoint) is not bool:
        raise ValueError("load_existing_checkpoint must be a boolean")

    if provider_id is not None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string or None")
        if provider_id != provider_id.strip():
            raise ValueError("provider_id must not contain leading or trailing whitespace")

    if not callable(start_fn):
        raise ValueError("start_fn must be callable")

    if not callable(monitor_fn):
        raise ValueError("monitor_fn must be callable")

    if existing_checkpoint is None and load_existing_checkpoint:
        try:
            existing_checkpoint = store.load()
        except (FileNotFoundError, ValueError):
            existing_checkpoint = None

    session: CycleSession | None = None
    attempt = 0
    replan_count = 0

    if existing_checkpoint is not None:
        if existing_checkpoint.task_id != task.task_id:
            raise ValueError(
                f"checkpoint task_id '{existing_checkpoint.task_id}' does not match task task_id '{task.task_id}'"
            )
        if (
            provider_id is not None
            and existing_checkpoint.provider_id is not None
            and existing_checkpoint.provider_id != provider_id
        ):
            raise ValueError(
                f"checkpoint provider_id '{existing_checkpoint.provider_id}' does not match provider_id '{provider_id}'"
            )

        if existing_checkpoint.state in (
            CheckpointState.HUMAN_WAIT,
            CheckpointState.FAILED,
            CheckpointState.COMPLETED,
        ):
            raise ValueError(
                f"Cannot resume checkpoint in {existing_checkpoint.state.value} state"
            )

        attempt = existing_checkpoint.attempt
        replan_count = existing_checkpoint.replan_count

        if (
            existing_checkpoint.state is CheckpointState.RUNNING
            and existing_checkpoint.provider_session_id
        ):
            session = CycleSession(
                task_id=task.task_id,
                session_id=existing_checkpoint.provider_session_id,
            )

    history: list[RepairPlan] = []

    while True:
        if session is None:
            try:
                session = start_fn(provider, task=task, source_name=source_name)
            except Exception as exc:
                plan = plan_repair(
                    task_id=task.task_id,
                    exc=exc,
                    attempt=attempt,
                    replan_count=replan_count,
                    policy=resolved_policy,
                )
                plan = _sanitize_repair_plan(plan)
                history.append(plan)
                if plan.disposition is RepairDisposition.RETRY:
                    attempt = plan.next_attempt
                    replan_count = plan.next_replan_count
                    running_chk = TaskCheckpoint(
                        task_id=task.task_id,
                        state=CheckpointState.RUNNING,
                        attempt=attempt,
                        replan_count=replan_count,
                        provider_session_id=None,
                        provider_id=provider_id,
                    )
                    store.save(running_chk)
                    session = None
                    continue
                else:
                    terminal_chk = checkpoint_for_repair_plan(
                        plan,
                        provider_session_id=None,
                        task_id=task.task_id,
                    )
                    if provider_id is not None:
                        terminal_chk = TaskCheckpoint(
                            task_id=terminal_chk.task_id,
                            state=terminal_chk.state,
                            attempt=terminal_chk.attempt,
                            replan_count=terminal_chk.replan_count,
                            provider_session_id=terminal_chk.provider_session_id,
                            provider_id=provider_id,
                            last_failure_kind=terminal_chk.last_failure_kind,
                            last_error=terminal_chk.last_error,
                            resume_after=terminal_chk.resume_after,
                        )
                    store.save(terminal_chk)
                    return CheckpointedCycleExecution(
                        result=None,
                        checkpoint=terminal_chk,
                        history=tuple(history),
                    )

            running_chk = checkpoint_for_session(
                session,
                attempt=attempt,
                replan_count=replan_count,
                task_id=task.task_id,
            )
            if provider_id is not None:
                running_chk = TaskCheckpoint(
                    task_id=running_chk.task_id,
                    state=running_chk.state,
                    attempt=running_chk.attempt,
                    replan_count=running_chk.replan_count,
                    provider_session_id=running_chk.provider_session_id,
                    provider_id=provider_id,
                )
            store.save(running_chk)

        try:
            result = monitor_fn(provider, task=task, session=session)
            completed_chk = checkpoint_for_completed(
                result,
                attempt=attempt,
                replan_count=replan_count,
                task_id=task.task_id,
            )
            if provider_id is not None:
                completed_chk = TaskCheckpoint(
                    task_id=completed_chk.task_id,
                    state=completed_chk.state,
                    attempt=completed_chk.attempt,
                    replan_count=completed_chk.replan_count,
                    provider_session_id=completed_chk.provider_session_id,
                    provider_id=provider_id,
                )
            store.save(completed_chk)
            return CheckpointedCycleExecution(
                result=result,
                checkpoint=completed_chk,
                history=tuple(history),
            )
        except Exception as exc:
            plan = plan_repair(
                task_id=task.task_id,
                exc=exc,
                attempt=attempt,
                replan_count=replan_count,
                policy=resolved_policy,
            )
            plan = _sanitize_repair_plan(plan)
            history.append(plan)
            if plan.disposition is RepairDisposition.RETRY:
                attempt = plan.next_attempt
                replan_count = plan.next_replan_count
                session = None
                running_chk = TaskCheckpoint(
                    task_id=task.task_id,
                    state=CheckpointState.RUNNING,
                    attempt=attempt,
                    replan_count=replan_count,
                    provider_session_id=None,
                )
                store.save(running_chk)
                continue
            else:
                terminal_chk = checkpoint_for_repair_plan(
                    plan,
                    provider_session_id=session.session_id if session else None,
                    task_id=task.task_id,
                )
                if provider_id is not None:
                    terminal_chk = TaskCheckpoint(
                        task_id=terminal_chk.task_id,
                        state=terminal_chk.state,
                        attempt=terminal_chk.attempt,
                        replan_count=terminal_chk.replan_count,
                        provider_session_id=terminal_chk.provider_session_id,
                        provider_id=provider_id,
                        last_failure_kind=terminal_chk.last_failure_kind,
                        last_error=terminal_chk.last_error,
                        resume_after=terminal_chk.resume_after,
                    )
                store.save(terminal_chk)
                return CheckpointedCycleExecution(
                    result=None,
                    checkpoint=terminal_chk,
                    history=tuple(history),
                )
