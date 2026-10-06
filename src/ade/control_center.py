from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .mission_control import MissionControlSnapshot


ATTENTION_LIFECYCLE_ORDER: dict[str, int] = {
    "HUMAN_WAIT": 0,
    "FAILED": 0,
    "BLOCKED": 0,
    "RECOVERING": 1,
    "PAUSED_QUOTA": 1,
    "WAITING": 1,
    "PENDING": 1,
    "RUNNING": 2,
    "READY": 3,
    "COMPLETED": 4,
}


def _campaign_progress(snapshot: MissionControlSnapshot) -> tuple[int, int, int]:
    campaign = snapshot.campaign or {}
    completed_raw = campaign.get("completed_tasks")
    total_raw = campaign.get("total_tasks")

    if type(completed_raw) is int and type(total_raw) is int:
        completed = max(0, completed_raw)
        total = max(completed, total_raw)
    else:
        completed = snapshot.completed_tasks
        total = snapshot.completed_tasks + snapshot.failed_tasks + snapshot.queue_depth
        if snapshot.current_task_id is not None and total <= completed:
            total = completed + 1

    if total == 0:
        percent = 100 if snapshot.queue_exhausted else 0
    else:
        percent = round((completed / total) * 100)

    return completed, total, max(0, min(100, percent))


def _attention_rank(lifecycle_status: str, human_action_required: bool) -> int:
    if human_action_required:
        return -1
    return ATTENTION_LIFECYCLE_ORDER.get(lifecycle_status.upper(), 2)


@dataclass(frozen=True, slots=True)
class ControlCenterProjectSummary:
    project_id: str
    lifecycle_status: str
    project_status: str
    current_task_id: str | None
    state_updated_at: str | None
    completed_tasks: int
    total_tasks: int
    progress_percent: int
    queue_depth: int
    failed_tasks: int
    open_decision_count: int
    warning_count: int
    human_action_required: bool
    next_required_human_action: str | None
    next_system_action: str | None
    resume_after: str | None
    phase: str | None = None
    milestone: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Control Center project schema_version")
        for field_name in ("project_id", "lifecycle_status", "project_status"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in (
            "completed_tasks",
            "total_tasks",
            "progress_percent",
            "queue_depth",
            "failed_tasks",
            "open_decision_count",
            "warning_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.completed_tasks > self.total_tasks:
            raise ValueError("completed_tasks cannot exceed total_tasks")
        if self.progress_percent > 100:
            raise ValueError("progress_percent cannot exceed 100")
        if type(self.human_action_required) is not bool:
            raise ValueError("human_action_required must be boolean")

    @property
    def attention_rank(self) -> int:
        return _attention_rank(self.lifecycle_status, self.human_action_required)

    @classmethod
    def from_mission_control(
        cls,
        snapshot: MissionControlSnapshot,
    ) -> "ControlCenterProjectSummary":
        if not isinstance(snapshot, MissionControlSnapshot):
            raise ValueError("snapshot must be a MissionControlSnapshot")

        completed, total, percent = _campaign_progress(snapshot)
        human_action_required = bool(
            snapshot.open_decisions or snapshot.next_required_human_action
        )
        return cls(
            project_id=snapshot.project_id,
            lifecycle_status=snapshot.lifecycle_status,
            project_status=snapshot.project_status,
            current_task_id=snapshot.current_task_id,
            state_updated_at=snapshot.state_updated_at,
            completed_tasks=completed,
            total_tasks=total,
            progress_percent=percent,
            queue_depth=snapshot.queue_depth,
            failed_tasks=snapshot.failed_tasks,
            open_decision_count=len(snapshot.open_decisions),
            warning_count=len(snapshot.warnings),
            human_action_required=human_action_required,
            next_required_human_action=snapshot.next_required_human_action,
            next_system_action=snapshot.next_system_action,
            resume_after=snapshot.resume_after,
            phase=snapshot.phase,
            milestone=snapshot.milestone,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "lifecycle_status": self.lifecycle_status,
            "project_status": self.project_status,
            "current_task_id": self.current_task_id,
            "state_updated_at": self.state_updated_at,
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "progress_percent": self.progress_percent,
            "queue_depth": self.queue_depth,
            "failed_tasks": self.failed_tasks,
            "open_decision_count": self.open_decision_count,
            "warning_count": self.warning_count,
            "human_action_required": self.human_action_required,
            "next_required_human_action": self.next_required_human_action,
            "next_system_action": self.next_system_action,
            "resume_after": self.resume_after,
            "phase": self.phase,
            "milestone": self.milestone,
        }


@dataclass(frozen=True, slots=True)
class ControlCenterPortfolioSnapshot:
    projects: tuple[ControlCenterProjectSummary, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Control Center portfolio schema_version")
        projects = tuple(self.projects)
        if any(not isinstance(item, ControlCenterProjectSummary) for item in projects):
            raise ValueError("projects must contain ControlCenterProjectSummary values")
        ids = [item.project_id for item in projects]
        if len(ids) != len(set(ids)):
            raise ValueError("project_id values must be unique")
        ordered = tuple(
            sorted(
                projects,
                key=lambda item: (
                    item.attention_rank,
                    item.project_id.casefold(),
                    item.project_id,
                ),
            )
        )
        object.__setattr__(self, "projects", ordered)

    @property
    def attention_required_count(self) -> int:
        return sum(1 for project in self.projects if project.human_action_required)

    @property
    def active_count(self) -> int:
        return sum(
            1
            for project in self.projects
            if project.lifecycle_status.upper() not in {"COMPLETED"}
        )

    @classmethod
    def from_mission_control_snapshots(
        cls,
        snapshots: Iterable[MissionControlSnapshot],
    ) -> "ControlCenterPortfolioSnapshot":
        return cls(
            projects=tuple(
                ControlCenterProjectSummary.from_mission_control(snapshot)
                for snapshot in snapshots
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_count": len(self.projects),
            "active_count": self.active_count,
            "attention_required_count": self.attention_required_count,
            "projects": [project.to_dict() for project in self.projects],
        }
