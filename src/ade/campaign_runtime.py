from __future__ import annotations
from dataclasses import replace
from .campaign import AutonomousCampaign, CampaignStatus

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
