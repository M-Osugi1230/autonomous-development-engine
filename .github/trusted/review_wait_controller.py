from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ade.remote_execution import RemoteExecutionReceipt
from ade.review_wait import ReviewWaitLedger, ReviewWaitRecord
from dag_controller import (
    TrustedDagError,
    graph_contains_task,
    park_managed_graph_for_review,
    reconcile_waiting_review,
)
from github_client import GitHubClient, GitHubError


REVIEW_WAITS_PATH = ".autodev/runtime/review-waits.json"
TASK_GRAPH_PATH = ".autodev/task-graph.json"
STATE_PATH = ".autodev/state.json"
QUEUE_PATH = ".autodev/task-queue.json"
CYCLE_TASK_PATH = ".autodev/cycle-task.json"
CAMPAIGN_PATH = ".autodev/campaign.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _is_not_found(exc: GitHubError) -> bool:
    return "GitHub HTTP 404:" in str(exc)


def _load_ledger(api: GitHubClient) -> ReviewWaitLedger:
    try:
        payload, _ = api.get_json_file(REVIEW_WAITS_PATH)
    except GitHubError as exc:
        if _is_not_found(exc):
            return ReviewWaitLedger()
        raise
    return ReviewWaitLedger.from_dict(payload)


def _save_ledger(api: GitHubClient, ledger: ReviewWaitLedger, *, message: str) -> None:
    api.upsert_json_file(REVIEW_WAITS_PATH, ledger.to_dict(), message=message)


def _optional_json(
    api: GitHubClient,
    path: str,
) -> tuple[dict[str, Any], str] | None:
    try:
        return api.get_json_file(path)
    except GitHubError as exc:
        if _is_not_found(exc):
            return None
        raise


def _graph_dependencies(graph: dict[str, Any], task_id: str) -> tuple[str, ...]:
    raw_tasks = graph.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise TrustedDagError("task graph tasks must be a list")
    for node in raw_tasks:
        if not isinstance(node, dict):
            continue
        task = node.get("task")
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            continue
        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise TrustedDagError("task graph depends_on must be a list")
        return tuple(str(item) for item in dependencies)
    raise TrustedDagError(f"task graph does not contain task {task_id}")


def _remove_queue_task(queue: dict[str, Any], task_id: str) -> None:
    raw_tasks = queue.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise RuntimeError("task queue tasks must be a list")
    remaining = []
    removed = False
    for candidate in raw_tasks:
        if not isinstance(candidate, dict):
            raise RuntimeError("queued task must be an object")
        if not removed and candidate.get("task_id") == task_id:
            removed = True
            continue
        remaining.append(candidate)
    queue["tasks"] = remaining


def _update_wait_metadata(
    state: dict[str, Any],
    ledger: ReviewWaitLedger,
) -> None:
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = dict(metadata)
    metadata["waiting_review_count"] = len(ledger.records)
    metadata["waiting_review_task_ids"] = [record.task_id for record in ledger.records]
    metadata["review_wait_non_blocking"] = True
    state["metadata"] = metadata


def _update_campaign_status(
    campaign: dict[str, Any],
    *,
    ledger: ReviewWaitLedger,
    has_active_task: bool,
) -> None:
    task_ids = campaign.get("task_ids", [])
    completed = campaign.get("completed_task_ids", [])
    if isinstance(task_ids, list) and isinstance(completed, list) and len(completed) == len(task_ids):
        campaign["status"] = "COMPLETED"
    elif has_active_task:
        campaign["status"] = "RUNNING"
    elif ledger.records:
        campaign["status"] = "HUMAN_WAIT"
    else:
        campaign["status"] = "RUNNING"


def park_current_task_for_review(
    api: GitHubClient,
    *,
    receipt: RemoteExecutionReceipt,
    reason: str,
    observed_at: str | None = None,
) -> str | None:
    """Park the active PR task while preserving human review boundaries.

    For a managed DAG, the first independent runnable task is activated. For a
    legacy FIFO campaign, ADE fails safe and exposes HUMAN_WAIT rather than
    guessing dependency safety.
    """
    observed = observed_at or _utc_now()
    state, state_sha = api.get_json_file(STATE_PATH)
    if state.get("current_task_id") != receipt.task_id:
        existing = _load_ledger(api).get(receipt.task_id)
        if existing is not None:
            return None
        raise RuntimeError("project state current_task_id does not match review task")

    graph_result = _optional_json(api, TASK_GRAPH_PATH)
    dependencies: tuple[str, ...] = ()
    next_task: dict[str, Any] | None = None

    if graph_result is not None:
        graph, graph_sha = graph_result
        if graph_contains_task(graph, receipt.task_id):
            dependencies = _graph_dependencies(graph, receipt.task_id)
            updated_graph, next_task = park_managed_graph_for_review(
                graph,
                task_id=receipt.task_id,
            )
            api.put_json_file(
                TASK_GRAPH_PATH,
                updated_graph,
                sha=graph_sha,
                message=f"graph: review wait {receipt.task_id}",
            )

    ledger = _load_ledger(api)
    existing_record = ledger.get(receipt.task_id)
    created_at = existing_record.created_at if existing_record is not None else observed
    record = ReviewWaitRecord(
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        pull_request_url=receipt.pull_request_url,
        reason=reason,
        created_at=created_at,
        updated_at=observed,
        depends_on=dependencies,
    )
    ledger = ledger.upsert(record)
    _save_ledger(api, ledger, message=f"review: wait {receipt.task_id}")

    queue, queue_sha = api.get_json_file(QUEUE_PATH)
    next_task_id: str | None = None
    if next_task is not None:
        candidate = next_task.get("task_id")
        if not isinstance(candidate, str) or not candidate.strip():
            raise RuntimeError("review-wait successor has no task_id")
        next_task_id = candidate
        _remove_queue_task(queue, next_task_id)
        state["current_task_id"] = next_task_id
        state["status"] = "READY"
    else:
        state["current_task_id"] = None
        state["status"] = "HUMAN_WAIT"

    state["updated_at"] = observed
    _update_wait_metadata(state, ledger)
    api.put_json_file(
        STATE_PATH,
        state,
        sha=state_sha,
        message=f"state: review wait {receipt.task_id}",
    )
    api.put_json_file(
        QUEUE_PATH,
        queue,
        sha=queue_sha,
        message=f"queue: review wait {receipt.task_id}",
    )

    campaign_result = _optional_json(api, CAMPAIGN_PATH)
    if campaign_result is not None:
        campaign, campaign_sha = campaign_result
        _update_campaign_status(
            campaign,
            ledger=ledger,
            has_active_task=next_task_id is not None,
        )
        api.put_json_file(
            CAMPAIGN_PATH,
            campaign,
            sha=campaign_sha,
            message=f"campaign: review wait {receipt.task_id}",
        )

    if next_task is not None:
        current_task, current_sha = api.get_json_file(CYCLE_TASK_PATH)
        del current_task
        api.put_json_file(
            CYCLE_TASK_PATH,
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task_id} during review wait",
        )
        api.dispatch("ade_next_cycle", {"task_id": next_task_id})

    return next_task_id


def reconcile_review_wait_merge(
    api: GitHubClient,
    *,
    receipt: RemoteExecutionReceipt,
    observed_at: str | None = None,
) -> tuple[bool, str | None]:
    """Complete a parked task after a late merge, idempotently.

    If another task is already RUNNING, it remains the active task. A newly
    unblocked task is activated only when the graph has no active RUNNING task.
    """
    observed = observed_at or _utc_now()
    ledger = _load_ledger(api)
    record = ledger.get(receipt.task_id)
    if record is None:
        return False, None
    if (
        record.target_repository != receipt.target_repository
        or record.pull_request_url != receipt.pull_request_url
    ):
        raise RuntimeError("review wait receipt does not match durable record")

    graph, graph_sha = api.get_json_file(TASK_GRAPH_PATH)
    updated_graph, next_task = reconcile_waiting_review(
        graph,
        task_id=receipt.task_id,
    )
    api.put_json_file(
        TASK_GRAPH_PATH,
        updated_graph,
        sha=graph_sha,
        message=f"graph: reconcile review {receipt.task_id}",
    )

    ledger = ledger.remove(receipt.task_id)
    _save_ledger(api, ledger, message=f"review: merged {receipt.task_id}")

    state, state_sha = api.get_json_file(STATE_PATH)
    completed = list(state.get("completed_task_ids", []))
    if receipt.task_id not in completed:
        completed.append(receipt.task_id)
        state["iteration"] = int(state.get("iteration", 0)) + 1
    state["completed_task_ids"] = completed

    current_task_id = state.get("current_task_id")
    if current_task_id == receipt.task_id:
        current_task_id = None
        state["current_task_id"] = None

    queue, queue_sha = api.get_json_file(QUEUE_PATH)
    next_task_id: str | None = None
    if current_task_id is None and next_task is not None:
        candidate = next_task.get("task_id")
        if not isinstance(candidate, str) or not candidate.strip():
            raise RuntimeError("review reconciliation successor has no task_id")
        next_task_id = candidate
        state["current_task_id"] = next_task_id
        state["status"] = "READY"
        _remove_queue_task(queue, next_task_id)
    elif current_task_id is not None:
        state["status"] = "RUNNING"
    elif ledger.records:
        state["status"] = "HUMAN_WAIT"
    else:
        state["status"] = "READY"

    state["updated_at"] = observed
    _update_wait_metadata(state, ledger)
    api.put_json_file(
        STATE_PATH,
        state,
        sha=state_sha,
        message=f"state: reconcile review {receipt.task_id}",
    )
    api.put_json_file(
        QUEUE_PATH,
        queue,
        sha=queue_sha,
        message=f"queue: reconcile review {receipt.task_id}",
    )

    campaign_result = _optional_json(api, CAMPAIGN_PATH)
    if campaign_result is not None:
        campaign, campaign_sha = campaign_result
        campaign_tasks = campaign.get("task_ids", [])
        if isinstance(campaign_tasks, list) and receipt.task_id in campaign_tasks:
            campaign_completed = list(campaign.get("completed_task_ids", []))
            if receipt.task_id not in campaign_completed:
                campaign_completed.append(receipt.task_id)
            campaign["completed_task_ids"] = campaign_completed
        _update_campaign_status(
            campaign,
            ledger=ledger,
            has_active_task=state.get("current_task_id") is not None,
        )
        api.put_json_file(
            CAMPAIGN_PATH,
            campaign,
            sha=campaign_sha,
            message=f"campaign: reconcile review {receipt.task_id}",
        )

    if next_task is not None and next_task_id is not None:
        _, current_sha = api.get_json_file(CYCLE_TASK_PATH)
        api.put_json_file(
            CYCLE_TASK_PATH,
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task_id} after review merge",
        )
        api.dispatch("ade_next_cycle", {"task_id": next_task_id})

    return True, next_task_id


def load_review_waits(api: GitHubClient) -> ReviewWaitLedger:
    return _load_ledger(api)
