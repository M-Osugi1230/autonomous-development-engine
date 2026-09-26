from __future__ import annotations

import copy
import json
from typing import Any

from ade_pr_gate import advance_queue
from github_client import GitHubError


def _task(task_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "prompt": f"Implement {task_id}",
        "starting_branch": "main",
        "auto_create_pr": True,
        "timeout_seconds": 1800,
        "poll_interval_seconds": 15,
    }


def _node(
    task_id: str,
    *,
    status: str = "PENDING",
    depends_on: list[str] | None = None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    task = _task(task_id)
    task.pop("schema_version", None)
    return {
        "task": task,
        "depends_on": list(depends_on or []),
        "status": status,
        "decision_id": decision_id,
    }


def _state(current_task_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "autonomous-development-engine",
        "provider": "jules",
        "status": "READY",
        "current_task_id": current_task_id,
        "completed_task_ids": [],
        "failed_task_ids": [],
        "iteration": 0,
        "metadata": {},
        "updated_at": "2026-09-26T00:00:00+00:00",
    }


class FakeGitHub:
    def __init__(
        self,
        *,
        state: dict[str, Any],
        queue: dict[str, Any],
        cycle_task: dict[str, Any],
        graph: dict[str, Any] | None = None,
    ) -> None:
        self.files: dict[str, tuple[dict[str, Any], str]] = {
            ".autodev/state.json": (copy.deepcopy(state), "state-sha"),
            ".autodev/task-queue.json": (copy.deepcopy(queue), "queue-sha"),
            ".autodev/cycle-task.json": (copy.deepcopy(cycle_task), "cycle-sha"),
        }
        if graph is not None:
            self.files[".autodev/task-graph.json"] = (
                copy.deepcopy(graph),
                "graph-sha",
            )
        self.dispatches: list[tuple[str, dict[str, Any]]] = []

    def get_json_file(
        self,
        path: str,
        *,
        ref: str = "main",
    ) -> tuple[dict[str, Any], str]:
        del ref
        if path not in self.files:
            raise GitHubError(
                'GitHub HTTP 404: {"message":"Not Found"}'
            )
        payload, sha = self.files[path]
        return copy.deepcopy(payload), sha

    def put_json_file(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        sha: str | None,
        message: str,
        branch: str = "main",
    ) -> None:
        del sha, message, branch
        self.files[path] = (copy.deepcopy(payload), f"{path}-new-sha")

    def dispatch(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.dispatches.append(
            (event_type, copy.deepcopy(payload or {}))
        )


def _dag_scenario() -> dict[str, Any]:
    graph = {
        "schema_version": 1,
        "tasks": [
            _node("current", status="RUNNING"),
            _node(
                "waiting",
                status="HUMAN_WAIT",
                decision_id="decision-1",
            ),
            _node("blocked", depends_on=["waiting"]),
            _node("independent", depends_on=["current"]),
        ],
    }
    api = FakeGitHub(
        state=_state("current"),
        queue={
            "schema_version": 1,
            "tasks": [_task("independent"), _task("later-fifo")],
        },
        cycle_task=_task("current"),
        graph=graph,
    )

    selected = advance_queue(api, completed_task_id="current")
    if selected != "independent":
        raise AssertionError(
            "DAG scheduler did not select independent task"
        )
    if api.dispatches != [
        ("ade_next_cycle", {"task_id": "independent"})
    ]:
        raise AssertionError("DAG dispatch payload is incorrect")

    updated_graph = api.files[".autodev/task-graph.json"][0]
    statuses = {
        node["task"]["task_id"]: node["status"]
        for node in updated_graph["tasks"]
    }
    if statuses != {
        "current": "COMPLETED",
        "waiting": "HUMAN_WAIT",
        "blocked": "PENDING",
        "independent": "RUNNING",
    }:
        raise AssertionError("DAG status transitions are incorrect")

    queue_ids = [
        item["task_id"]
        for item in api.files[".autodev/task-queue.json"][0]["tasks"]
    ]
    if queue_ids != ["later-fifo"]:
        raise AssertionError("duplicate DAG task was not removed from FIFO")

    return {
        "selected": selected,
        "blocked_status": statuses["blocked"],
        "waiting_status": statuses["waiting"],
    }


def _blocked_scenario() -> dict[str, Any]:
    graph = {
        "schema_version": 1,
        "tasks": [
            _node("current", status="RUNNING"),
            _node(
                "waiting",
                status="HUMAN_WAIT",
                decision_id="decision-2",
            ),
            _node("blocked", depends_on=["waiting"]),
        ],
    }
    api = FakeGitHub(
        state=_state("current"),
        queue={
            "schema_version": 1,
            "tasks": [_task("unsafe-fifo")],
        },
        cycle_task=_task("current"),
        graph=graph,
    )

    selected = advance_queue(api, completed_task_id="current")
    if selected is not None:
        raise AssertionError(
            "blocked DAG must not fall through to FIFO"
        )
    if api.dispatches:
        raise AssertionError(
            "blocked DAG unexpectedly dispatched a task"
        )
    state = api.files[".autodev/state.json"][0]
    if state["status"] != "BLOCKED":
        raise AssertionError("blocked DAG did not persist BLOCKED state")
    queue = api.files[".autodev/task-queue.json"][0]["tasks"]
    if [item["task_id"] for item in queue] != ["unsafe-fifo"]:
        raise AssertionError("blocked DAG mutated FIFO fallback queue")

    return {
        "selected": None,
        "project_status": state["status"],
    }


def _fifo_scenario() -> dict[str, Any]:
    api = FakeGitHub(
        state=_state("current"),
        queue={
            "schema_version": 1,
            "tasks": [_task("fifo-next")],
        },
        cycle_task=_task("current"),
    )

    selected = advance_queue(api, completed_task_id="current")
    if selected != "fifo-next":
        raise AssertionError("FIFO fallback did not select next task")
    if api.dispatches != [
        ("ade_next_cycle", {"task_id": "fifo-next"})
    ]:
        raise AssertionError("FIFO fallback dispatch is incorrect")

    return {"selected": selected}


def run_probe() -> dict[str, Any]:
    dag = _dag_scenario()
    blocked = _blocked_scenario()
    fifo = _fifo_scenario()
    return {
        "ok": True,
        "dag_selected": dag["selected"],
        "blocked_descendant": dag["blocked_status"],
        "human_wait": dag["waiting_status"],
        "blocked_project_status": blocked["project_status"],
        "fifo_selected": fifo["selected"],
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = (
            str(exc).splitlines()[0].strip()
            if str(exc).strip()
            else type(exc).__name__
        )
        print(
            json.dumps(
                {"ok": False, "error": message[:256]},
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
