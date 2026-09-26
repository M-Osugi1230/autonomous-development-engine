from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from github_client import GitHubClient, GitHubError

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
            return False, "changed file has no filename"
        if filename in FORBIDDEN_EXACT:
            return False, f"forbidden file changed: {filename}"
        if filename.startswith(FORBIDDEN_PREFIXES):
            return False, f"forbidden path changed: {filename}"

    return True, "Jules provenance and change scope are allowed"


def advance_queue(api: GitHubClient) -> str | None:
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

    metadata = dict(state.get("metadata", {}))
    state["status"] = "READY"
    if next_task is None:
        state["current_task_id"] = None
        metadata["queue_exhausted"] = True
    else:
        state["current_task_id"] = str(next_task["task_id"])
        metadata["queue_exhausted"] = False
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
        api.dispatch("ade_next_cycle", {"task_id": str(next_task["task_id"])})
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
        files = api.list_pull_request_files(pr_number)
        allowed, reason = evaluate_jules_pull_request(
            repository=api.repository,
            pull_request=pr,
            files=files,
        )
        if not allowed:
            print(f"HUMAN_WAIT: PR #{pr_number}: {reason}", file=sys.stderr)
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

    except (GitHubError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ADE PR gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
