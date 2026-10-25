from __future__ import annotations

from dataclasses import replace

from .task_graph import GraphTaskStatus, TaskGraph, TaskNode


def _replace_node(graph: TaskGraph, replacement: TaskNode) -> TaskGraph:
    tasks = tuple(
        replacement if node.task_id == replacement.task_id else node
        for node in graph.tasks
    )
    return TaskGraph(tasks=tasks, schema_version=graph.schema_version)


def _dependencies_completed(graph: TaskGraph, node: TaskNode) -> bool:
    return all(
        graph.require(dependency).status is GraphTaskStatus.COMPLETED
        for dependency in node.depends_on
    )


def transition_task(
    graph: TaskGraph,
    *,
    task_id: str,
    target_status: GraphTaskStatus | str,
    decision_id: str | None = None,
) -> TaskGraph:
    """Apply a validated immutable task transition.

    HUMAN_WAIT -> PENDING is intentionally excluded; use
    resume_task_after_decision() so a matching human decision is required.
    WAITING_REVIEW -> COMPLETED is also intentionally excluded; use
    reconcile_waiting_review_task() after the trusted PR monitor observes merge.
    """
    if not isinstance(graph, TaskGraph):
        raise ValueError("graph must be a TaskGraph")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")

    try:
        target = GraphTaskStatus(target_status)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid target_status: {target_status}") from exc

    node = graph.require(task_id)
    source = node.status

    if source is GraphTaskStatus.PENDING:
        if target is not GraphTaskStatus.RUNNING:
            raise ValueError(f"illegal transition: {source.value} -> {target.value}")
        if decision_id is not None:
            raise ValueError("decision_id is not valid for PENDING -> RUNNING")
        if not _dependencies_completed(graph, node):
            raise ValueError("cannot start task before all dependencies are COMPLETED")
        replacement = replace(
            node,
            status=GraphTaskStatus.RUNNING,
            decision_id=None,
        )
        return _replace_node(graph, replacement)

    if source is GraphTaskStatus.RUNNING:
        if target is GraphTaskStatus.HUMAN_WAIT:
            if not isinstance(decision_id, str) or not decision_id.strip():
                raise ValueError("RUNNING -> HUMAN_WAIT requires decision_id")
            replacement = replace(
                node,
                status=GraphTaskStatus.HUMAN_WAIT,
                decision_id=decision_id,
            )
            return _replace_node(graph, replacement)

        if target is GraphTaskStatus.WAITING_REVIEW:
            if decision_id is not None:
                raise ValueError("decision_id is not valid for RUNNING -> WAITING_REVIEW")
            replacement = replace(
                node,
                status=GraphTaskStatus.WAITING_REVIEW,
                decision_id=None,
            )
            return _replace_node(graph, replacement)

        if target in (GraphTaskStatus.COMPLETED, GraphTaskStatus.FAILED):
            if decision_id is not None:
                raise ValueError(
                    f"decision_id is not valid for RUNNING -> {target.value}"
                )
            replacement = replace(
                node,
                status=target,
                decision_id=None,
            )
            return _replace_node(graph, replacement)

        raise ValueError(f"illegal transition: {source.value} -> {target.value}")

    if source is GraphTaskStatus.HUMAN_WAIT:
        raise ValueError(
            "HUMAN_WAIT tasks require resume_task_after_decision() with a "
            "matching decision_id"
        )

    if source is GraphTaskStatus.WAITING_REVIEW:
        raise ValueError(
            "WAITING_REVIEW tasks require reconcile_waiting_review_task() after "
            "trusted merge evidence"
        )

    raise ValueError(f"{source.value} is terminal and cannot transition")


def resume_task_after_decision(
    graph: TaskGraph,
    *,
    task_id: str,
    decision_id: str,
) -> TaskGraph:
    """Return a HUMAN_WAIT task to PENDING after explicit human resolution."""
    if not isinstance(graph, TaskGraph):
        raise ValueError("graph must be a TaskGraph")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise ValueError("decision_id must be a non-empty string")

    node = graph.require(task_id)
    if node.status is not GraphTaskStatus.HUMAN_WAIT:
        raise ValueError("task is not in HUMAN_WAIT")
    if node.decision_id != decision_id:
        raise ValueError("decision_id does not match the waiting task")

    replacement = replace(
        node,
        status=GraphTaskStatus.PENDING,
        decision_id=None,
    )
    return _replace_node(graph, replacement)


def reconcile_waiting_review_task(
    graph: TaskGraph,
    *,
    task_id: str,
) -> TaskGraph:
    """Mark a review-wait task complete after trusted merge reconciliation.

    The transition is idempotent so duplicate scheduled monitor events cannot
    complete the task twice or disturb a different task that is currently
    running.
    """
    if not isinstance(graph, TaskGraph):
        raise ValueError("graph must be a TaskGraph")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")

    node = graph.require(task_id)
    if node.status is GraphTaskStatus.COMPLETED:
        return graph
    if node.status is not GraphTaskStatus.WAITING_REVIEW:
        raise ValueError("task is not in WAITING_REVIEW")

    replacement = replace(
        node,
        status=GraphTaskStatus.COMPLETED,
        decision_id=None,
    )
    return _replace_node(graph, replacement)
