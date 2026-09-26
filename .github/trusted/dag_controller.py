from __future__ import annotations

from copy import deepcopy
from typing import Any


ALLOWED_STATUSES = {
    "PENDING",
    "RUNNING",
    "HUMAN_WAIT",
    "COMPLETED",
    "FAILED",
}


class TrustedDagError(ValueError):
    pass


def _task_id(node: dict[str, Any]) -> str:
    task = node.get("task")
    if not isinstance(task, dict):
        raise TrustedDagError("task graph node requires a task object")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise TrustedDagError("task graph node requires a non-empty task_id")
    return task_id


def validate_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TrustedDagError("task graph must be a JSON object")
    if payload.get("schema_version") != 1:
        raise TrustedDagError("task graph schema_version must be 1")

    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise TrustedDagError("task graph tasks must be a list")

    graph = deepcopy(payload)
    tasks = graph["tasks"]

    by_id: dict[str, dict[str, Any]] = {}
    for node in tasks:
        if not isinstance(node, dict):
            raise TrustedDagError("task graph nodes must be JSON objects")

        task_id = _task_id(node)
        if task_id in by_id:
            raise TrustedDagError(f"duplicate task_id: {task_id}")

        task = node["task"]
        for field in ("title", "prompt", "starting_branch"):
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                raise TrustedDagError(
                    f"task {task_id} requires non-empty {field}"
                )

        auto_create_pr = task.get("auto_create_pr", True)
        if type(auto_create_pr) is not bool:
            raise TrustedDagError(
                f"task {task_id} auto_create_pr must be boolean"
            )

        timeout_seconds = task.get("timeout_seconds", 1800)
        poll_interval_seconds = task.get("poll_interval_seconds", 15)
        if type(timeout_seconds) is not int or timeout_seconds < 60:
            raise TrustedDagError(
                f"task {task_id} timeout_seconds must be >= 60"
            )
        if type(poll_interval_seconds) is not int or poll_interval_seconds < 5:
            raise TrustedDagError(
                f"task {task_id} poll_interval_seconds must be >= 5"
            )

        depends_on = node.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise TrustedDagError(
                f"task {task_id} depends_on must be a list"
            )
        seen_dependencies: set[str] = set()
        for dependency in depends_on:
            if not isinstance(dependency, str) or not dependency.strip():
                raise TrustedDagError(
                    f"task {task_id} dependency IDs must be non-empty strings"
                )
            if dependency == task_id:
                raise TrustedDagError(
                    f"task {task_id} cannot depend on itself"
                )
            if dependency in seen_dependencies:
                raise TrustedDagError(
                    f"task {task_id} has duplicate dependency {dependency}"
                )
            seen_dependencies.add(dependency)

        status = node.get("status", "PENDING")
        if status not in ALLOWED_STATUSES:
            raise TrustedDagError(
                f"task {task_id} has invalid status {status!r}"
            )
        node["status"] = status

        decision_id = node.get("decision_id")
        if status == "HUMAN_WAIT":
            if not isinstance(decision_id, str) or not decision_id.strip():
                raise TrustedDagError(
                    f"HUMAN_WAIT task {task_id} requires decision_id"
                )
        elif decision_id is not None:
            raise TrustedDagError(
                f"decision_id is only valid for HUMAN_WAIT task {task_id}"
            )

        by_id[task_id] = node

    for task_id, node in by_id.items():
        for dependency in node.get("depends_on", []):
            if dependency not in by_id:
                raise TrustedDagError(
                    f"task {task_id} depends on missing task {dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise TrustedDagError(
                f"task graph contains a cycle at {task_id}"
            )
        visiting.add(task_id)
        for dependency in by_id[task_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)

    return graph


def graph_contains_task(payload: dict[str, Any], task_id: str) -> bool:
    graph = validate_graph_payload(payload)
    if not isinstance(task_id, str) or not task_id.strip():
        raise TrustedDagError("task_id must be a non-empty string")
    return any(_task_id(node) == task_id for node in graph["tasks"])


def _runnable_nodes(
    graph: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks = graph["tasks"]
    by_id = {_task_id(node): node for node in tasks}
    runnable: list[dict[str, Any]] = []
    for node in tasks:
        if node["status"] != "PENDING":
            continue
        if all(
            by_id[dependency]["status"] == "COMPLETED"
            for dependency in node.get("depends_on", [])
        ):
            runnable.append(node)
    return runnable


def advance_managed_graph(
    payload: dict[str, Any],
    *,
    completed_task_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    graph = validate_graph_payload(payload)
    if not isinstance(completed_task_id, str) or not completed_task_id.strip():
        raise TrustedDagError("completed_task_id must be a non-empty string")

    current: dict[str, Any] | None = None
    for node in graph["tasks"]:
        if _task_id(node) == completed_task_id:
            current = node
            break
    if current is None:
        raise TrustedDagError(
            f"task graph does not contain current task {completed_task_id}"
        )
    if current["status"] != "RUNNING":
        raise TrustedDagError(
            f"current task {completed_task_id} must be RUNNING before completion"
        )

    current["status"] = "COMPLETED"
    current["decision_id"] = None

    runnable = _runnable_nodes(graph)
    if not runnable:
        return graph, None

    selected = runnable[0]
    selected["status"] = "RUNNING"
    selected["decision_id"] = None
    task = deepcopy(selected["task"])
    task.setdefault("schema_version", 1)
    return graph, task


def graph_has_unfinished_work(payload: dict[str, Any]) -> bool:
    graph = validate_graph_payload(payload)
    return any(
        node["status"] not in {"COMPLETED", "FAILED"}
        for node in graph["tasks"]
    )
