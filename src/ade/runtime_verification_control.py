from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re
from typing import Any

from .campaign import AutonomousCampaign, CampaignStatus
from .models import ProjectState, ProjectStatus
from .task_graph import GraphTaskStatus, TaskGraph
from .task_graph_transition import transition_task


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RuntimeFailureBoundary:
    decision_id: str
    state: dict[str, Any]
    campaign: dict[str, Any]
    task_graph: dict[str, Any]


def runtime_failure_decision_id(
    *,
    task_id: str,
    verification_id: str,
    report_fingerprint: str,
) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be non-empty")
    if not isinstance(verification_id, str) or not verification_id.strip():
        raise ValueError("verification_id must be non-empty")
    if (
        not isinstance(report_fingerprint, str)
        or _SHA256.fullmatch(report_fingerprint) is None
    ):
        raise ValueError("report_fingerprint must be a lowercase SHA-256 digest")
    raw = f"{task_id}:{verification_id}:{report_fingerprint}"
    return "runtime-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_runtime_failure_boundary(
    *,
    state_payload: dict[str, Any],
    campaign_payload: dict[str, Any],
    graph_payload: dict[str, Any],
    task_id: str,
    verification_id: str,
    report_fingerprint: str,
) -> RuntimeFailureBoundary:
    state = ProjectState.from_dict(state_payload)
    campaign = AutonomousCampaign.from_dict(campaign_payload)
    graph = TaskGraph.from_dict(graph_payload)

    if state.current_task_id != task_id:
        raise ValueError("runtime failure task does not match current project task")
    if task_id not in campaign.task_ids:
        raise ValueError("runtime failure task is not part of active campaign")
    if task_id in campaign.completed_task_ids:
        raise ValueError("runtime failure task is already campaign-completed")

    node = graph.require(task_id)
    if node.status is not GraphTaskStatus.RUNNING:
        raise ValueError("runtime failure task must still be RUNNING")

    decision_id = runtime_failure_decision_id(
        task_id=task_id,
        verification_id=verification_id,
        report_fingerprint=report_fingerprint,
    )
    updated_graph = transition_task(
        graph,
        task_id=task_id,
        target_status=GraphTaskStatus.HUMAN_WAIT,
        decision_id=decision_id,
    )

    metadata = dict(state.metadata)
    metadata.update(
        {
            "runtime_verification_id": verification_id,
            "runtime_verification_report_fingerprint": report_fingerprint,
            "runtime_verification_decision_id": decision_id,
            "runtime_verification_status": "FAILED",
            "next_system_action": "human-decision-required",
            "next_required_human_action": (
                "Review failed runtime verification before resuming this task."
            ),
        }
    )
    updated_state = ProjectState(
        schema_version=state.schema_version,
        project_id=state.project_id,
        status=ProjectStatus.HUMAN_WAIT,
        iteration=state.iteration,
        current_task_id=state.current_task_id,
        completed_task_ids=list(state.completed_task_ids),
        failed_task_ids=list(state.failed_task_ids),
        provider=state.provider,
        updated_at=state.updated_at,
        metadata=metadata,
    )
    updated_state.validate()

    updated_campaign = replace(
        campaign,
        status=CampaignStatus.HUMAN_WAIT,
    )

    return RuntimeFailureBoundary(
        decision_id=decision_id,
        state=updated_state.to_dict(),
        campaign=updated_campaign.to_dict(),
        task_graph=updated_graph.to_dict(),
    )
