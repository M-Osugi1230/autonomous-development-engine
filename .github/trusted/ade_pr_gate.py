from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dag_controller import (
    TrustedDagError,
    advance_managed_graph,
    graph_contains_task,
    graph_has_unfinished_work,
)
from github_client import GitHubClient, GitHubError
from observability import record_merged_pr

FORBIDDEN_EXACT = {
    "GOAL.md",
    "SPEC.md",
    "ACCEPTANCE.md",
    "ROADMAP.md",
    "README.md",
    "pyproject.toml",
}
FORBIDDEN_PREFIXES = (
    ".github/",
    ".autodev/",
)
TASK_GRAPH_PATH = ".autodev/task-graph.json"
JULES_PROVENANCE_MARKER = "PR created automatically by Jules for task"
JULES_TASK_URL = re.compile(r"https://jules\.google\.com/task/\d+")


def load_event() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub event payload must be an object")
    return payload


def evaluate_jules_pull_request(
    *,
    repository: str,
    pull_request: dict[str, Any],
    files: list[dict[str, Any]],
) -> tuple[bool, str]:
    if pull_request.get("state") != "open":
        return False, "pull request is not open"
    if pull_request.get("draft") is True:
        return False, "draft pull requests are not auto-merged"

    head = pull_request.get("head")
    if not isinstance(head, dict):
        return False, "pull request head is missing"

    head_repo = head.get("repo")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
        return False, "head repository is not the ADE repository"

    head_ref = head.get("ref")
    if not isinstance(head_ref, str) or not head_ref.strip():
        return False, "pull request head branch is missing"
    if head_ref in {"main", "master"}:
        return False, "protected default branch cannot be auto-merged as a head"

    body = pull_request.get("body")
    if not isinstance(body, str):
        return False, "Jules provenance marker is missing"
    if JULES_PROVENANCE_MARKER not in body or JULES_TASK_URL.search(body) is None:
        return False, "Jules provenance marker or task URL is missing"

    if not files:
        return False, "pull request changes no files"

    for changed in files:
        filename = changed.get("filename")
        if not isinstance(filename, str):
            return False, "changed file has no filename")
        if filename in FORBIDDEN_EXACT:
            return False, f"forbidden file changed: {filename}"
        if filename.startswith(FORBIDDEN_PREFIXES):
            return False, f"forbidden path changed: {filename}"

    return True, "Jules provenance and change scope are allowed"


def _optional_task_graph(
    api: GitHubClient,
) -> tuple[dict[str, Any], str] | None:
    try:
        return api.get_json_file(TASK_GRAPH_PATH)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise


def _remove_queue_task(
    tasks: list[Any],
    *,
    task_id: str,
) -> list[Any]:
    result: list[Any] = []
    removed = False
    for candidate in tasks:
        if not isinstance(candidate, dict):
            raise RuntimeError("queued task must be an object")
        candidate_id = candidate.get("task_id")
        if not removed and candidate_id == task_id:
            removed = True
            continue
        result.append(candidate)
    return result


def _pop_fifo(tasks: list[Any]) -> tuple[dict[str, Any] | None, list[Any]]:
    if not tasks:
        return None, []
    candidate = tasks[0]
    if not isinstance(candidate, dict):
        raise RuntimeError("queued task must be an object")
    return candidate, list(tasks[1:])


def advance_queue(
    api: GitHubClient,
    *,
    completed_task_id: str | None = None,
) -> str | None:
    current_task, current_sha = api.get_json_file(".autodev/cycle-task.json")
    state, state_sha = api.get_json_file(".autodev/state.json")
    queue, queue_sha = api.get_json_file(".autodev/task-queue.json")

    state_current = state.get("current_task_id")
    if completed_task_id is None:
        completed_task_id = (
            state_current
            if isinstance(state_current, str) and state_current.strip()
            else current_task.get("task_id")
        )
    if not isinstance(completed_task_id, str) or not completed_task_id.strip():
        raise RuntimeError("completed task id is missing")

    if (
        isinstance(state_current, str)
        and state_current.strip()
        and state_current != completed_task_id
    ):
        raise RuntimeError(
            "project state current_task_id does not match completed task"
        )

    completed = list(state.get("completed_task_ids", []))
    if completed_task_id not in completed:
        completed.append(completed_task_id)

    state["completed_task_ids"] = completed
    state["iteration"] = int(state.get("iteration", 0)) + 1
    state["updated_at"] = datetime.now(UTC).isoformat()

    tasks = queue.get("tasks", [])
    if not isinstance(tasks, list):
        raise RuntimeError("task queue tasks must be a list")
    remaining_queue = list(tasks)

    next_task: dict[str, Any] | None = None
    scheduler = "fifo"
    dag_blocked = False
    graph_result = _optional_task_graph(api)

    if graph_result is not None:
        graph, graph_sha = graph_result
        if graph_contains_task(graph, completed_task_id):
            scheduler = "dag"
            updated_graph, next_task = advance_managed_graph(
                graph,
                completed_task_id=completed_task_id,
            )
            if next_task is not None:
                next_task_id = next_task.get("task_id")
                if not isinstance(next_task_id, str) or not next_task_id.strip():
                    raise TrustedDagError(
                        "selected DAG task has no valid task_id"
                    )
                remaining_queue = _remove_queue_task(
                    remaining_queue,
                    task_id=next_task_id,
                )
            elif graph_has_unfinished_work(updated_graph):
                dag_blocked = True
            else:
                next_task, remaining_queue = _pop_fifo(remaining_queue)
                if next_task is not None:
                    scheduler = "fifo"

            api.put_json_file(
                TASK_GRAPH_PATH,
                updated_graph,
                sha=graph_sha,
                message=f"graph: complete {completed_task_id}",
            )

    if scheduler == "fifo" and graph_result is None:
        next_task, remaining_queue = _pop_fifo(remaining_queue)
    elif (
        scheduler == "fifo"
        and graph_result is not None
        and next_task is None
        and not dag_blocked
    ):
        # The graph exists but does not manage the current task.
        graph, _ = graph_result
        if not graph_contains_task(graph, completed_task_id):
            next_task, remaining_queue = _pop_fifo(remaining_queue)

    queue["tasks"] = remaining_queue

    metadata = dict(state.get("metadata", {}))
    metadata["scheduler"] = scheduler
    metadata["dag_blocked"] = dag_blocked

    if next_task is None:
        state["current_task_id"] = None
        if dag_blocked:
            state["status"] = "BLOCKED"
            metadata["queue_exhausted"] = False
        else:
            state["status"] = "READY"
            metadata["queue_exhausted"] = not bool(remaining_queue)
    else:
        next_task_id = next_task.get("task_id")
        if not isinstance(next_task_id, str) or not next_task_id.strip():
            raise RuntimeError("next task has no valid task_id")
        state["status"] = "READY"
        state["current_task_id"] = next_task_id
        metadata["queue_exhausted"] = False

    state["metadata"] = metadata

    api.put_json_file(
        ".autodev/state.json",
        state,
        sha=state_sha,
        message=f"state: complete {completed_task_id}",
    )
    api.put_json_file(
        ".autodev/task-queue.json",
        queue,
        sha=queue_sha,
        message=f"queue: advance after {completed_task_id}",
    )

    if next_task is not None:
        next_task_id = str(next_task["task_id"])
        api.put_json_file(
            ".autodev/cycle-task.json",
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task_id}",
        )
        api.dispatch("ade_next_cycle", {"task_id": next_task_id})
        return next_task_id

    return None


def main() -> int:
    try:
        event = load_event()
        workflow_run = event.get("workflow_run")
        if not isinstance(workflow_run, dict):
            print("SKIP: event has no workflow_run")
            return 0
        if workflow_run.get("event") != "pull_request":
            print("SKIP: CI run was not triggered by a pull request")
            return 0
        if workflow_run.get("conclusion") != "success":
            print("WAIT: CI is not green; no merge attempted")
            return 0

        pull_requests = workflow_run.get("pull_requests", [])
        if not isinstance(pull_requests, list) or len(pull_requests) != 1:
            print("SKIP: expected exactly one associated pull request")
            return 0
        pr_number = pull_requests[0].get("number")
        if not isinstance(pr_number, int):
            raise RuntimeError("associated pull request has no number")

        api = GitHubClient()
        pr = api.get_pull_request(pr_number)

        if pr.get("state") != "open":
            if pr.get("merged_at"):
                print(f"SKIP: PR #{pr_number} is already merged")
                return 0
            print(f"SKIP: PR #{pr_number} is already closed")
            return 0

        files = api.list_pull_request_files(pr_number)
        allowed, reason = evaluate_jules_pull_request(
            repository=api.repository,
            pull_request=pr,
            files=files,
        )
        if not allowed:
            print(f"HUMAN_WAIT: PR #{pr_number}: {reason}", file=sys.stderr)
            return 2

        state, _ = api.get_json_file(".autodev/state.json")
        current_task_id = state.get("current_task_id")
        if not isinstance(current_task_id, str) or not current_task_id.strip():
            raise RuntimeError("project state has no valid current_task_id")

        head = pr.get("head", {})
        expected_sha = head.get("sha")
        if not isinstance(expected_sha, str) or not expected_sha:
            raise RuntimeError("pull request head SHA is missing")

        merge_result = api.merge_pull_request(pr_number, expected_sha=expected_sha)
        if merge_result.get("merged") is not True:
            raise RuntimeError(
                f"GitHub did not merge PR #{pr_number}: {merge_result.get('message')}"
            )

        print(f"MERGED: Jules PR #{pr_number}")
        next_task_id = advance_queue(
            api,
            completed_task_id=current_task_id,
        )

        try:
            pr_url = pr.get("html_url")
            if not isinstance(pr_url, str) or not pr_url:
                raise ValueError("pull request html_url is missing")
            record_merged_pr(
                api,
                pr_number=pr_number,
                pr_url=pr_url,
                task_id=current_task_id,
                head_sha=expected_sha,
                occurred_at=datetime.now(UTC).isoformat(),
            )
        except (GitHubError, ValueError) as observability_exc:
            print(
                f"WARNING: observability update failed: {observability_exc}",
                file=sys.stderr,
            )

        if next_task_id is None:
            print("NO DISPATCH: no safe runnable autonomous task")
        else:
            print(f"DISPATCHED: next autonomous task {next_task_id}")
        return 0

    except (
        GitHubError,
        TrustedDagError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ADE PR gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
