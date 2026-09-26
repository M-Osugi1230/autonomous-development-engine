from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .cycle import CycleTask


class GraphTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    HUMAN_WAIT = "HUMAN_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class TaskNode:
    task: CycleTask
    depends_on: tuple[str, ...] = ()
    status: GraphTaskStatus = GraphTaskStatus.PENDING
    decision_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task, CycleTask):
            raise ValueError("task must be a CycleTask")
        self.task.validate()

        if not isinstance(self.depends_on, tuple):
            try:
                dependencies = tuple(self.depends_on)
            except TypeError as exc:
                raise ValueError("depends_on must be an iterable of task IDs") from exc
            object.__setattr__(self, "depends_on", dependencies)

        seen: set[str] = set()
        for dependency in self.depends_on:
            if not isinstance(dependency, str) or not dependency.strip():
                raise ValueError("dependency IDs must be non-empty strings")
            if dependency == self.task.task_id:
                raise ValueError("task cannot depend on itself")
            if dependency in seen:
                raise ValueError(f"duplicate dependency: {dependency}")
            seen.add(dependency)

        try:
            status = GraphTaskStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid graph task status: {self.status}") from exc
        object.__setattr__(self, "status", status)

        if self.status is GraphTaskStatus.HUMAN_WAIT:
            if not isinstance(self.decision_id, str) or not self.decision_id.strip():
                raise ValueError("HUMAN_WAIT task requires a decision_id")
        elif self.decision_id is not None:
            raise ValueError("decision_id is only valid for HUMAN_WAIT tasks")

    @property
    def task_id(self) -> str:
        return self.task.task_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": {
                "task_id": self.task.task_id,
                "title": self.task.title,
                "prompt": self.task.prompt,
                "starting_branch": self.task.starting_branch,
                "auto_create_pr": self.task.auto_create_pr,
                "timeout_seconds": self.task.timeout_seconds,
                "poll_interval_seconds": self.task.poll_interval_seconds,
            },
            "depends_on": list(self.depends_on),
            "status": self.status.value,
            "decision_id": self.decision_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskNode":
        if not isinstance(payload, dict):
            raise ValueError("task node payload must be a JSON object")
        task_payload = payload.get("task")
        if not isinstance(task_payload, dict):
            raise ValueError("task node requires a task object")
        depends_on = payload.get("depends_on", [])
        if not isinstance(depends_on, (list, tuple)):
            raise ValueError("depends_on must be a list")
        return cls(
            task=CycleTask.from_dict(task_payload),
            depends_on=tuple(depends_on),
            status=payload.get("status", GraphTaskStatus.PENDING.value),
            decision_id=payload.get("decision_id"),
        )


@dataclass(frozen=True, slots=True)
class TaskGraph:
    tasks: tuple[TaskNode, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"unsupported task graph schema_version: {self.schema_version}")

        if not isinstance(self.tasks, tuple):
            try:
                normalized = tuple(self.tasks)
            except TypeError as exc:
                raise ValueError("tasks must be an iterable of TaskNode values") from exc
            object.__setattr__(self, "tasks", normalized)

        by_id: dict[str, TaskNode] = {}
        for node in self.tasks:
            if not isinstance(node, TaskNode):
                raise ValueError("tasks must contain only TaskNode values")
            if node.task_id in by_id:
                raise ValueError(f"duplicate task_id: {node.task_id}")
            by_id[node.task_id] = node

        for node in self.tasks:
            for dependency in node.depends_on:
                if dependency not in by_id:
                    raise ValueError(
                        f"task {node.task_id} depends on missing task {dependency}"
                    )

        self._validate_acyclic(by_id)

    @staticmethod
    def _validate_acyclic(by_id: dict[str, TaskNode]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError(f"task graph contains a cycle at {task_id}")
            visiting.add(task_id)
            for dependency in by_id[task_id].depends_on:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in by_id:
            visit(task_id)

    def get(self, task_id: str) -> TaskNode | None:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        for node in self.tasks:
            if node.task_id == task_id:
                return node
        return None

    def require(self, task_id: str) -> TaskNode:
        node = self.get(task_id)
        if node is None:
            raise KeyError(f"task_id not found: {task_id}")
        return node

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tasks": [node.to_dict() for node in self.tasks],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskGraph":
        if not isinstance(payload, dict):
            raise ValueError("task graph payload must be a JSON object")
        schema_version = payload.get("schema_version")
        if schema_version != 1:
            raise ValueError(f"unsupported task graph schema_version: {schema_version}")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError("task graph tasks must be a list")
        return cls(
            tasks=tuple(TaskNode.from_dict(item) for item in raw_tasks),
            schema_version=schema_version,
        )
