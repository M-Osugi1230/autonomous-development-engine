from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from ade.remote_execution import RemoteExecutionReceipt
from ade.review_wait import ReviewWaitLedger, ReviewWaitRecord
from ade_pr_gate import advance_queue
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


def _graph_node(graph: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    raw_tasks = graph.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise TrustedDagError("task graph tasks must be a list")
    for node in raw_tasks:
        if not isinstance(node, dict):
            raise TrustedDagError("task graph nodes must be objects")
        task = node.get("task")
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return node
    return None


def _running_graph_task(graph: dict[str, Any]) -> dict[str, Any] | None:
    running: list[dict[str, Any]] = []
    raw_tasks = graph.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise TrustedDagError("task graph tasks must be a list")
    for node in raw_tasks:
        if not isinstance(node, dict):
            raise TrustedDagError("task graph nodes must be objects")
        if node.get("status") != "RUNNING":
            continue
        task = node.get("task")
        if not isinstance(task, dict):
            raise TrustedDagError("RUNNING task graph node requires task payload")
        running.append(task)
    if len(running) > 1:
        raise TrustedDagError("task graph contains more than one RUNNING task")
    return running[0] if running else None


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


def _expected_base_branch(state: dict[str, Any]) -> str | None:
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("target_base_branch")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _validate_late_merge_identity(record: ReviewWaitRecord) -> None:
    token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "").strip()
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
    target = GitHubClient(repository=record.target_repository, token=token)
    pull_request = target.get_pull_request(record.pull_request_number)
    if pull_request.get("html_url") != record.pull_request_url:
        raise RuntimeError("review wait pull request URL changed before reconciliation")
    if not pull_request.get("merged_at"):
        raise RuntimeError("review wait pull request is not merged")
    if record.expected_base_branch is not None:
        base = pull_request.get("base")
        base_ref = base.get("ref") if isinstance(base, dict) else None
        if base_ref != record.expected_base_branch:
            raise RuntimeError(
                "review wait pull request merged into unexpected base branch"
            )


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
    guessing dependency safety. The durable ledger retains enough trusted PR
    identity to reconcile either scheduler after a later merge.
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
        expected_base_branch=_expected_base_branch(state),
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
        _, current_sha = api.get_json_file(CYCLE_TASK_PATH)
        api.put_json_file(
            CYCLE_TASK_PATH,
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task_id} during review wait",
        )
        api.dispatch("ade_next_cycle", {"task_id": next_task_id})

    return next_task_id


def _finish_legacy_reconciliation(
    api: GitHubClient,
    *,
    receipt: RemoteExecutionReceipt,
) -> str | None:
    state, _ = api.get_json_file(STATE_PATH)
    completed = state.get("completed_task_ids", [])
    if isinstance(completed, list) and receipt.task_id in completed:
        current = state.get("current_task_id")
        if isinstance(current, str) and current.strip() and current != receipt.task_id:
            return current
        return None
    return advance_queue(api, completed_task_id=receipt.task_id)


def _finish_managed_reconciliation(
    api: GitHubClient,
    *,
    receipt: RemoteExecutionReceipt,
    ledger_after: ReviewWaitLedger,
    observed: str,
    graph: dict[str, Any],
    graph_sha: str,
) -> str | None:
    node = _graph_node(graph, receipt.task_id)
    if node is None:
        raise TrustedDagError(f"task graph does not contain task {receipt.task_id}")

    status = node.get("status")
    if status == "WAITING_REVIEW":
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
        graph = updated_graph
    elif status == "COMPLETED":
        next_task = _running_graph_task(graph)
    else:
        raise TrustedDagError(
            f"review wait task {receipt.task_id} has unexpected graph status {status!r}"
        )

    state, state_sha = api.get_json_file(STATE_PATH)
    completed = list(state.get("completed_task_ids", []))
    newly_completed = receipt.task_id not in completed
    if newly_completed:
        completed.append(receipt.task_id)
        state["iteration"] = int(state.get("iteration", 0)) + 1
    state["completed_task_ids"] = completed

    current_task_id = state.get("current_task_id")
    if current_task_id == receipt.task_id:
        current_task_id = None
        state["current_task_id"] = None

    queue, queue_sha = api.get_json_file(QUEUE_PATH)
    next_task_id: str | None = None
    should_dispatch = False
    if isinstance(current_task_id, str) and current_task_id.strip():
        state["status"] = "RUNNING"
        next_task_id = current_task_id
    elif next_task is not None:
        candidate = next_task.get("task_id")
        if not isinstance(candidate, str) or not candidate.strip():
            raise RuntimeError("review reconciliation successor has no task_id")
        next_task_id = candidate
        state["current_task_id"] = next_task_id
        state["status"] = "READY"
        _remove_queue_task(queue, next_task_id)
        should_dispatch = True
    elif ledger_after.records:
        state["current_task_id"] = None
        state["status"] = "HUMAN_WAIT"
    else:
        state["current_task_id"] = None
        state["status"] = "READY"

    state["updated_at"] = observed
    _update_wait_metadata(state, ledger_after)
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
            ledger=ledger_after,
            has_active_task=state.get("current_task_id") is not None,
        )
        api.put_json_file(
            CAMPAIGN_PATH,
            campaign,
            sha=campaign_sha,
            message=f"campaign: reconcile review {receipt.task_id}",
        )

    if should_dispatch and next_task is not None and next_task_id is not None:
        _, current_sha = api.get_json_file(CYCLE_TASK_PATH)
        api.put_json_file(
            CYCLE_TASK_PATH,
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task_id} after review merge",
        )
        api.dispatch("ade_next_cycle", {"task_id": next_task_id})

    return next_task_id


def reconcile_review_wait_merge(
    api: GitHubClient,
    *,
    receipt: RemoteExecutionReceipt,
    observed_at: str | None = None,
) -> tuple[bool, str | None]:
    """Complete a parked task after a late merge, idempotently and recoverably.

    The durable ledger is intentionally removed only after graph/FIFO state,
    queue, campaign, cycle-task activation, and dispatch have succeeded. If a
    write or dispatch fails mid-reconciliation, the next monitor run retains the
    trusted PR identity and can safely recover from the partially advanced
    state without creating a second task completion.
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

    _validate_late_merge_identity(record)
    ledger_after = ledger.remove(receipt.task_id)

    graph_result = _optional_json(api, TASK_GRAPH_PATH)
    managed = False
    if graph_result is not None:
        graph, graph_sha = graph_result
        managed = graph_contains_task(graph, receipt.task_id)

    if managed:
        next_task_id = _finish_managed_reconciliation(
            api,
            receipt=receipt,
            ledger_after=ledger_after,
            observed=observed,
            graph=graph,
            graph_sha=graph_sha,
        )
    else:
        next_task_id = _finish_legacy_reconciliation(api, receipt=receipt)
        state, state_sha = api.get_json_file(STATE_PATH)
        _update_wait_metadata(state, ledger_after)
        state["updated_at"] = observed
        api.put_json_file(
            STATE_PATH,
            state,
            sha=state_sha,
            message=f"state: clear review wait {receipt.task_id}",
        )
        campaign_result = _optional_json(api, CAMPAIGN_PATH)
        if campaign_result is not None:
            campaign, campaign_sha = campaign_result
            _update_campaign_status(
                campaign,
                ledger=ledger_after,
                has_active_task=state.get("current_task_id") is not None,
            )
            api.put_json_file(
                CAMPAIGN_PATH,
                campaign,
                sha=campaign_sha,
                message=f"campaign: clear review wait {receipt.task_id}",
            )

    _save_ledger(
        api,
        ledger_after,
        message=f"review: reconciled merged {receipt.task_id}",
    )
    return True, next_task_id


def load_review_waits(api: GitHubClient) -> ReviewWaitLedger:
    return _load_ledger(api)
