from __future__ import annotations
from .campaign import AutonomousCampaign, CampaignStatus
from .cycle import CycleTask
from .development_plan import DevelopmentPlan
from .task_graph import GraphTaskStatus, TaskGraph, TaskNode

def compile_plan(plan: DevelopmentPlan, *, campaign_id: str, starting_branch: str = "main") -> tuple[AutonomousCampaign, TaskGraph]:
    plan.validate()
    if not campaign_id.strip():
        raise ValueError("campaign_id is required")
    nodes=[]
    for item in plan.tasks:
        scope=", ".join(item.allowed_paths)
        acceptance="; ".join(item.acceptance)
        prompt=f"{item.prompt}\nAllowed paths: {scope}\nAcceptance: {acceptance}\nDo not modify files outside the allowed paths."
        task=CycleTask(task_id=item.task_id,title=item.title,prompt=prompt,starting_branch=starting_branch,auto_create_pr=True)
        nodes.append(TaskNode(task=task,depends_on=item.depends_on,status=GraphTaskStatus.PENDING))
    graph=TaskGraph(tasks=tuple(nodes))
    campaign=AutonomousCampaign(campaign_id=campaign_id,goal=plan.goal,task_ids=tuple(t.task_id for t in plan.tasks),status=CampaignStatus.READY,completed_task_ids=())
    return campaign, graph
