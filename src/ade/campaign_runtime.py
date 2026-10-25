from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .campaign import AutonomousCampaign, CampaignStatus
from .task_graph import GraphTaskStatus, TaskGraph


def _campaign_has_runnable_task(
    task_ids: tuple[str, ...],
    task_graph: TaskGraph,
) -> bool:
    campaign_ids = set(task_ids)
    for node in task_graph.tasks:
        if node.task_id not in campaign_ids:
            continue
        if node.status is not GraphTaskStatus.PENDING:
            continue
        if all(
            task_graph.require(dependency).status is GraphTaskStatus.COMPLETED
            for dependency in node.depends_on
        ):
            return True
    return False


def derive_campaign_status(
    campaign: AutonomousCampaign | Sequence[str],
    task_graph: TaskGraph,
) -> CampaignStatus:
    if isinstance(campaign, AutonomousCampaign):
        task_ids = campaign.task_ids
    elif isinstance(campaign, (tuple, list)):
        task_ids = tuple(campaign)
    else:
        task_ids = tuple(campaign)

    if not task_ids:
        raise ValueError("campaign task IDs must not be empty")

    campaign_nodes = []
    for task_id in task_ids:
        node = task_graph.get(task_id)
        if node is not None:
            campaign_nodes.append(node)

    if any(node.status is GraphTaskStatus.FAILED for node in campaign_nodes):
        return CampaignStatus.FAILED

    if (
        campaign_nodes
        and len(campaign_nodes) == len(task_ids)
        and all(node.status is GraphTaskStatus.COMPLETED for node in campaign_nodes)
    ):
        return CampaignStatus.COMPLETED

    if any(node.status is GraphTaskStatus.HUMAN_WAIT for node in campaign_nodes):
        return CampaignStatus.HUMAN_WAIT

    if any(node.status is GraphTaskStatus.RUNNING for node in campaign_nodes):
        return CampaignStatus.RUNNING

    if _campaign_has_runnable_task(tuple(task_ids), task_graph):
        return CampaignStatus.RUNNING

    if any(node.status is GraphTaskStatus.WAITING_REVIEW for node in campaign_nodes):
        return CampaignStatus.HUMAN_WAIT

    return CampaignStatus.RUNNING


def complete_campaign_task(
    campaign: AutonomousCampaign,
    task_id: str,
    *,
    has_next: bool,
    human_wait: bool = False,
    failed: bool = False,
) -> AutonomousCampaign:
    if task_id not in campaign.task_ids:
        raise ValueError("task is not part of campaign")
    completed = list(campaign.completed_task_ids)
    if task_id not in completed:
        completed.append(task_id)
    if failed:
        status = CampaignStatus.FAILED
    elif human_wait:
        status = CampaignStatus.HUMAN_WAIT
    elif len(completed) == len(campaign.task_ids):
        status = CampaignStatus.COMPLETED
    elif has_next:
        status = CampaignStatus.RUNNING
    else:
        status = CampaignStatus.HUMAN_WAIT
    return replace(
        campaign,
        completed_task_ids=tuple(completed),
        status=status,
    )
