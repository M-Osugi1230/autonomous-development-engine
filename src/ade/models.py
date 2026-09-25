from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ProjectStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED_QUOTA = "PAUSED_QUOTA"
    HUMAN_WAIT = "HUMAN_WAIT"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    HUMAN_WAIT = "HUMAN_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class ProjectState:
    schema_version: int
    project_id: str
    status: ProjectStatus
    iteration: int = 0
    current_task_id: str | None = None
    completed_task_ids: list[str] = field(default_factory=list)
    failed_task_ids: list[str] = field(default_factory=list)
    provider: str = "jules"
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        if self.iteration < 0:
            raise ValueError("iteration must be >= 0")
        overlap = set(self.completed_task_ids) & set(self.failed_task_ids)
        if overlap:
            raise ValueError(f"task ids cannot be both completed and failed: {sorted(overlap)}")
        if self.status is ProjectStatus.RUNNING and not self.current_task_id:
            raise ValueError("RUNNING state requires current_task_id")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectState":
        state = cls(
            schema_version=int(payload["schema_version"]),
            project_id=str(payload["project_id"]),
            status=ProjectStatus(payload["status"]),
            iteration=int(payload.get("iteration", 0)),
            current_task_id=payload.get("current_task_id"),
            completed_task_ids=list(payload.get("completed_task_ids", [])),
            failed_task_ids=list(payload.get("failed_task_ids", [])),
            provider=str(payload.get("provider", "jules")),
            updated_at=payload.get("updated_at"),
            metadata=dict(payload.get("metadata", {})),
        )
        state.validate()
        return state
