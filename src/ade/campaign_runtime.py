from __future__ import annotations
from dataclasses import replace
from typing import Sequence
from .campaign import AutonomousCampaign, CampaignStatus
from .task_graph import GraphTaskStatus, TaskGraph

def derive_campaign_status(campaign: AutonomousCampaign | Sequence[str], task_graph: TaskGraph) -> CampaignStatus:
    if isinstance(campaign, AutonomousCampaign):
        task_ids = campaign.task_ids
    elif isinstance(campaign, (tuple, list)):
        task_ids = tuple(campaign)
    else:
        task_ids = tuple(campaign)

    if not task_ids:
        raise ValueError("campaign task IDs must not be empty")

    campaign_nodes = []
    for tid in task_ids:
        node = task_graph.get(tid)
        if node is not None:
            campaign_nodes.append(node)

    if any(node.status == GraphTaskStatus.FAILED for node in campaign_nodes):
        return CampaignStatus.FAILED

    if any(node.status == GraphTaskStatus.HUMAN_WAIT for node in campaign_nodes):
        return CampaignStatus.HUMAN_WAIT

    if campaign_nodes and all(node.status == GraphTaskStatus.COMPLETED for node in campaign_nodes) and len(campaign_nodes) == len(task_ids):
        return CampaignStatus.COMPLETED

    return CampaignStatus.RUNNING

def complete_campaign_task(campaign: AutonomousCampaign, task_id: str, *, has_next: bool, human_wait: bool=False, failed: bool=False) -> AutonomousCampaign:
    if task_id not in campaign.task_ids: raise ValueError("task is not part of campaign")
    completed=list(campaign.completed_task_ids)
    if task_id not in completed: completed.append(task_id)
    if failed: status=CampaignStatus.FAILED
    elif human_wait: status=CampaignStatus.HUMAN_WAIT
    elif len(completed)==len(campaign.task_ids): status=CampaignStatus.COMPLETED
    elif has_next: status=CampaignStatus.RUNNING
    else: status=CampaignStatus.HUMAN_WAIT
    return replace(campaign,completed_task_ids=tuple(completed),status=status)
