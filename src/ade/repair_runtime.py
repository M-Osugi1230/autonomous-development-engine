from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .cycle import CycleResult, CycleTask, run_cycle
from .repair import RepairDisposition, RepairPolicy
from .repair_planner import RepairPlan, plan_repair


@dataclass(frozen=True, slots=True)
class RepairExecution:
    result: CycleResult | None = None
    final_plan: RepairPlan | None = None
    history: tuple[RepairPlan, ...] = ()

    def __post_init__(self) -> None:
        if (self.result is None and self.final_plan is None) or (
            self.result is not None and self.final_plan is not None
        ):
            raise ValueError("Exactly one of result or final_plan must be provided")

        if self.result is not None and not isinstance(self.result, CycleResult):
            raise ValueError("result must be an instance of CycleResult or None")

        if self.final_plan is not None and not isinstance(self.final_plan, RepairPlan):
            raise ValueError("final_plan must be an instance of RepairPlan or None")

        if not isinstance(self.history, (tuple, list)):
            raise ValueError("history must be a tuple or list of RepairPlan instances")

        history_tuple = tuple(self.history)
        for item in history_tuple:
            if not isinstance(item, RepairPlan):
                raise ValueError("All history items must be RepairPlan instances")

        object.__setattr__(self, "history", history_tuple)


def run_cycle_with_repair(
    provider: Any,
    *,
    task: CycleTask,
    source_name: str,
    policy: RepairPolicy | None = None,
    run_cycle_fn: Callable[..., CycleResult] = run_cycle,
) -> RepairExecution:
    if provider is None:
        raise ValueError("provider must not be None")

    if not isinstance(task, CycleTask):
        raise ValueError("task must be an instance of CycleTask")
    task.validate()

    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("source_name must be a non-empty string")

    if policy is None:
        resolved_policy = RepairPolicy()
    elif isinstance(policy, RepairPolicy):
        resolved_policy = policy
    else:
        raise ValueError("policy must be an instance of RepairPolicy or None")

    if not callable(run_cycle_fn):
        raise ValueError("run_cycle_fn must be callable")

    attempt = 0
    replan_count = 0
    history: list[RepairPlan] = []

    while True:
        try:
            cycle_result = run_cycle_fn(provider, task=task, source_name=source_name)
            return RepairExecution(
                result=cycle_result,
                final_plan=None,
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
            history.append(plan)
            if plan.disposition is RepairDisposition.RETRY:
                attempt = plan.next_attempt
                replan_count = plan.next_replan_count
            else:
                return RepairExecution(
                    result=None,
                    final_plan=plan,
                    history=tuple(history),
                )
