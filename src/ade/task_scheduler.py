from __future__ import annotations

from .task_graph import GraphTaskStatus, TaskGraph, TaskNode


def runnable_tasks(
    graph: TaskGraph,
    *,
    limit: int | None = None,
) -> tuple[TaskNode, ...]:
    """Return deterministic runnable PENDING tasks in declared graph order."""
    if not isinstance(graph, TaskGraph):
        raise ValueError("graph must be a TaskGraph")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer or None")

    by_id = {node.task_id: node for node in graph.tasks}
    runnable: list[TaskNode] = []

    for node in graph.tasks:
        if node.status is not GraphTaskStatus.PENDING:
            continue
        if all(
            by_id[dependency].status is GraphTaskStatus.COMPLETED
            for dependency in node.depends_on
        ):
            runnable.append(node)
            if limit is not None and len(runnable) >= limit:
                break

    return tuple(runnable)


def next_runnable_task(graph: TaskGraph) -> TaskNode | None:
    tasks = runnable_tasks(graph, limit=1)
    return tasks[0] if tasks else None
