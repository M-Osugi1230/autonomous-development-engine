from __future__ import annotations
from dataclasses import dataclass
from .development_plan import DevelopmentPlan, PlannedTask

@dataclass(frozen=True, slots=True)
class GoalWorkItem:
    title: str
    outcome: str
    allowed_paths: tuple[str,...]
    acceptance: tuple[str,...]
    depends_on: tuple[int,...]=()

def plan_goal(goal:str, work_items:tuple[GoalWorkItem,...], *, id_prefix:str="goal")->DevelopmentPlan:
    if not goal.strip() or not work_items:
        raise ValueError("goal and work_items are required")
    tasks=[]
    for index,item in enumerate(work_items,1):
        if not item.title.strip() or not item.outcome.strip():
            raise ValueError("work item title and outcome are required")
        task_id=f"{id_prefix}-{index:03d}"
        deps=[]
        for dep in item.depends_on:
            if type(dep) is not int or dep < 1 or dep >= index:
                raise ValueError("work item dependencies must reference earlier items")
            deps.append(f"{id_prefix}-{dep:03d}")
        prompt=f"Goal: {goal.strip()}\nOutcome: {item.outcome.strip()}"
        tasks.append(PlannedTask(task_id,item.title.strip(),prompt,tuple(deps),item.allowed_paths,item.acceptance))
    plan=DevelopmentPlan(goal.strip(),tuple(tasks))
    plan.validate()
    return plan
