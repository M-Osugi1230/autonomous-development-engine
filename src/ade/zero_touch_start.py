from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .accepted_plan import AcceptedPlan
from .campaign import AutonomousCampaign, CampaignStatus
from .checkpoint import CheckpointState, TaskCheckpoint
from .cycle import CycleTask
from .execution_lease import ExecutionLease
from .models import ProjectState, ProjectStatus
from .plan_compiler import compile_plan
from .task_graph import GraphTaskStatus, TaskGraph


class StartDisposition(StrEnum):
    DISPATCH = "DISPATCH"
    NOOP = "NOOP"
    HUMAN_WAIT = "HUMAN_WAIT"
    RECOVERING = "RECOVERING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class StartDecision:
    disposition: StartDisposition
    reason: str
    campaign_id: str
    task_id: str | None
    plan_fingerprint: str

    @property
    def should_dispatch(self) -> bool:
        return self.disposition is StartDisposition.DISPATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "plan_fingerprint": self.plan_fingerprint,
        }


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _same_cycle_task(left: CycleTask, right: CycleTask) -> bool:
    return (
        left.task_id == right.task_id
        and left.title == right.title
        and " ".join(left.prompt.split()) == " ".join(right.prompt.split())
        and left.starting_branch == right.starting_branch
        and left.auto_create_pr == right.auto_create_pr
        and left.timeout_seconds == right.timeout_seconds
        and left.poll_interval_seconds == right.poll_interval_seconds
    )


def _lease_from_dict(payload: dict[str, Any]) -> ExecutionLease:
    if payload.get("schema_version") != 1:
        raise ValueError("execution lease schema_version must be 1")
    return ExecutionLease(
        task_id=str(payload["task_id"]),
        owner_id=str(payload["owner_id"]),
        attempt=int(payload["attempt"]),
        acquired_at=datetime.fromisoformat(str(payload["acquired_at"])),
        expires_at=datetime.fromisoformat(str(payload["expires_at"])),
    )


def _receipt_dispatch_time(
    payload: dict[str, Any] | None,
    *,
    campaign_id: str,
    task_id: str,
    plan_fingerprint: str,
) -> datetime | None:
    if payload is None:
        return None
    if payload.get("schema_version") != 1:
        raise ValueError("zero-touch receipt schema_version must be 1")
    if (
        payload.get("campaign_id") != campaign_id
        or payload.get("task_id") != task_id
        or payload.get("plan_fingerprint") != plan_fingerprint
        or payload.get("status") != "DISPATCHED"
    ):
        return None
    value = payload.get("dispatched_at")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("zero-touch receipt dispatched_at is required")
    parsed = datetime.fromisoformat(value)
    return _utc(parsed, field="receipt dispatched_at")


def evaluate_zero_touch_start(
    *,
    accepted_plan_payload: dict[str, Any],
    campaign_payload: dict[str, Any],
    graph_payload: dict[str, Any],
    state_payload: dict[str, Any],
    cycle_task_payload: dict[str, Any],
    now: datetime,
    lease_payload: dict[str, Any] | None = None,
    checkpoint_payload: dict[str, Any] | None = None,
    receipt_payload: dict[str, Any] | None = None,
    redispatch_after: timedelta = timedelta(minutes=10),
) -> StartDecision:
    now = _utc(now, field="now")
    if not isinstance(redispatch_after, timedelta) or redispatch_after <= timedelta(0):
        raise ValueError("redispatch_after must be positive")

    accepted = AcceptedPlan.from_dict(accepted_plan_payload)
    if accepted.status != "ACCEPTED":
        raise ValueError("zero-touch start requires AcceptedPlan status ACCEPTED")

    campaign = AutonomousCampaign.from_dict(campaign_payload)
    graph = TaskGraph.from_dict(graph_payload)
    state = ProjectState.from_dict(state_payload)
    cycle_task = CycleTask.from_dict(cycle_task_payload)

    expected_campaign, expected_graph = compile_plan(
        accepted.plan,
        campaign_id=campaign.campaign_id,
    )
    if campaign.goal != expected_campaign.goal or campaign.task_ids != expected_campaign.task_ids:
        raise ValueError("campaign does not reconcile with AcceptedPlan")
    if tuple(node.task_id for node in graph.tasks) != expected_campaign.task_ids:
        raise ValueError("task graph IDs do not reconcile with AcceptedPlan")
    for live, expected in zip(graph.tasks, expected_graph.tasks, strict=True):
        if live.depends_on != expected.depends_on or not _same_cycle_task(live.task, expected.task):
            raise ValueError(f"task graph drift for {live.task_id}")

    fingerprint = accepted.fingerprint
    base = {
        "campaign_id": campaign.campaign_id,
        "plan_fingerprint": fingerprint,
    }

    if campaign.status is CampaignStatus.COMPLETED or state.status is ProjectStatus.COMPLETE:
        return StartDecision(StartDisposition.NOOP, "campaign-completed", task_id=None, **base)
    if campaign.status is CampaignStatus.HUMAN_WAIT or state.status is ProjectStatus.HUMAN_WAIT:
        return StartDecision(StartDisposition.HUMAN_WAIT, "human-wait", task_id=state.current_task_id, **base)
    if campaign.status is CampaignStatus.FAILED or state.status in {ProjectStatus.FAILED, ProjectStatus.BLOCKED}:
        return StartDecision(StartDisposition.BLOCKED, "failed-or-blocked", task_id=state.current_task_id, **base)
    if state.status is ProjectStatus.PAUSED_QUOTA:
        return StartDecision(StartDisposition.RECOVERING, "quota-paused", task_id=state.current_task_id, **base)
    if campaign.status not in {CampaignStatus.READY, CampaignStatus.RUNNING}:
        return StartDecision(StartDisposition.BLOCKED, "campaign-not-startable", task_id=state.current_task_id, **base)

    if any(node.status is GraphTaskStatus.HUMAN_WAIT for node in graph.tasks):
        return StartDecision(StartDisposition.HUMAN_WAIT, "graph-human-wait", task_id=state.current_task_id, **base)
    if any(node.status is GraphTaskStatus.FAILED for node in graph.tasks):
        return StartDecision(StartDisposition.BLOCKED, "graph-failed", task_id=state.current_task_id, **base)

    task_id = state.current_task_id
    if not isinstance(task_id, str) or not task_id.strip():
        return StartDecision(StartDisposition.BLOCKED, "no-current-task", task_id=None, **base)

    current = graph.get(task_id)
    if current is None:
        raise ValueError("project current task is not present in task graph")
    if current.status is not GraphTaskStatus.RUNNING:
        return StartDecision(StartDisposition.BLOCKED, "current-task-not-running", task_id=task_id, **base)
    if not _same_cycle_task(cycle_task, current.task):
        raise ValueError("cycle task does not match current task graph node")

    if checkpoint_payload is not None:
        checkpoint = TaskCheckpoint.from_dict(checkpoint_payload)
        if checkpoint.task_id == task_id:
            if checkpoint.state is CheckpointState.HUMAN_WAIT:
                return StartDecision(StartDisposition.HUMAN_WAIT, "checkpoint-human-wait", task_id=task_id, **base)
            if checkpoint.state in {
                CheckpointState.RUNNING,
                CheckpointState.PAUSED_QUOTA,
                CheckpointState.REPLAN,
            }:
                return StartDecision(StartDisposition.RECOVERING, "checkpoint-recovery-owned", task_id=task_id, **base)
            if checkpoint.state is CheckpointState.COMPLETED:
                return StartDecision(StartDisposition.NOOP, "provider-work-completed", task_id=task_id, **base)
            if checkpoint.state is CheckpointState.FAILED:
                return StartDecision(StartDisposition.BLOCKED, "checkpoint-failed", task_id=task_id, **base)

    if lease_payload is not None:
        lease = _lease_from_dict(lease_payload)
        if lease.is_live(now):
            if lease.task_id == task_id:
                return StartDecision(StartDisposition.NOOP, "active-execution-lease", task_id=task_id, **base)
            return StartDecision(StartDisposition.BLOCKED, "different-live-execution-lease", task_id=task_id, **base)

    last_dispatch = _receipt_dispatch_time(
        receipt_payload,
        campaign_id=campaign.campaign_id,
        task_id=task_id,
        plan_fingerprint=fingerprint,
    )
    if last_dispatch is not None and now < last_dispatch + redispatch_after:
        return StartDecision(StartDisposition.NOOP, "recent-zero-touch-dispatch", task_id=task_id, **base)

    return StartDecision(StartDisposition.DISPATCH, "eligible-zero-touch-start", task_id=task_id, **base)
