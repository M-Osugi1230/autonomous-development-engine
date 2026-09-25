from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ade.github_api import GitHubApi, GitHubApiError
from ade.pr_gate import evaluate_jules_pull_request


def load_event() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub event payload must be an object")
    return payload


def advance_queue(api: GitHubApi) -> str | None:
    current_task, current_sha = api.get_json_file(".autodev/cycle-task.json")
    state, state_sha = api.get_json_file(".autodev/state.json")
    queue, queue_sha = api.get_json_file(".autodev/task-queue.json")

    current_task_id = str(current_task["task_id"])
    completed = list(state.get("completed_task_ids", []))
    if current_task_id not in completed:
        completed.append(current_task_id)

    state["completed_task_ids"] = completed
    state["iteration"] = int(state.get("iteration", 0)) + 1
    state["updated_at"] = datetime.now(UTC).isoformat()

    tasks = queue.get("tasks", [])
    if not isinstance(tasks, list):
        raise RuntimeError("task queue tasks must be a list")

    next_task: dict[str, Any] | None = None
    if tasks:
        candidate = tasks.pop(0)
        if not isinstance(candidate, dict):
            raise RuntimeError("queued task must be an object")
        next_task = candidate

    queue["tasks"] = tasks

    if next_task is None:
        state["status"] = "READY"
        state["current_task_id"] = None
        metadata = dict(state.get("metadata", {}))
        metadata["queue_exhausted"] = True
        metadata["phase"] = "phase4-closed-loop"
        state["metadata"] = metadata
    else:
        state["status"] = "READY"
        state["current_task_id"] = str(next_task["task_id"])
        metadata = dict(state.get("metadata", {}))
        metadata["queue_exhausted"] = False
        metadata["phase"] = "phase4-closed-loop"
        state["metadata"] = metadata

    api.put_json_file(
        ".autodev/state.json",
        state,
        sha=state_sha,
        message=f"state: complete {current_task_id}",
    )
    api.put_json_file(
        ".autodev/task-queue.json",
        queue,
        sha=queue_sha,
        message=f"queue: advance after {current_task_id}",
    )

    if next_task is not None:
        api.put_json_file(
            ".autodev/cycle-task.json",
            next_task,
            sha=current_sha,
            message=f"task: activate {next_task['task_id']}",
        )
        api.dispatch(
            "ade_next_cycle",
            {"task_id": str(next_task["task_id"])},
        )
        return str(next_task["task_id"])

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
            print(
                "WAIT: CI is not green. Jules CI Fixer may repair its PR; "
                "ADE will reevaluate after the next CI run."
            )
            return 0

        pull_requests = workflow_run.get("pull_requests", [])
        if not isinstance(pull_requests, list) or len(pull_requests) != 1:
            print("SKIP: expected exactly one associated pull request")
            return 0

        pr_number = pull_requests[0].get("number")
        if not isinstance(pr_number, int):
            raise RuntimeError("associated pull request has no number")

        api = GitHubApi()
        pr = api.get_pull_request(pr_number)
        files = api.list_pull_request_files(pr_number)
        decision = evaluate_jules_pull_request(
            repository=api.repository,
            pull_request=pr,
            files=files,
        )
        if not decision.allowed:
            print(f"HUMAN_WAIT: PR #{pr_number}: {decision.reason}", file=sys.stderr)
            return 2

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
        next_task_id = advance_queue(api)
        if next_task_id is None:
            print("QUEUE COMPLETE: no pending autonomous tasks")
        else:
            print(f"DISPATCHED: next autonomous task {next_task_id}")
        return 0

    except (GitHubApiError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ADE PR gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
