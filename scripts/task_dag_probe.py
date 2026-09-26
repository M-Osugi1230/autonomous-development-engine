from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ade import (
    CycleTask,
    GraphTaskStatus,
    TaskGraph,
    TaskGraphStore,
    TaskNode,
    next_runnable_task,
    resume_task_after_decision,
    runnable_tasks,
    transition_task,
)


def _task(task_id: str) -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title=f"Task {task_id}",
        prompt=f"Implement {task_id}",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )


def _ids(graph: TaskGraph) -> list[str]:
    return [node.task_id for node in runnable_tasks(graph)]


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = TaskGraphStore(Path(temp_dir) / "task-graph.json")
        graph = TaskGraph(
            tasks=(
                TaskNode(task=_task("branch-a")),
                TaskNode(
                    task=_task("branch-a-child"),
                    depends_on=("branch-a",),
                ),
                TaskNode(task=_task("branch-b")),
            )
        )
        store.save(graph)

        loaded = store.load()
        if _ids(loaded) != ["branch-a", "branch-b"]:
            raise AssertionError("initial runnable roots are incorrect")

        loaded = transition_task(
            loaded,
            task_id="branch-a",
            target_status=GraphTaskStatus.RUNNING,
        )
        loaded = transition_task(
            loaded,
            task_id="branch-a",
            target_status=GraphTaskStatus.HUMAN_WAIT,
            decision_id="decision-a",
        )
        store.save(loaded)

        while_waiting = store.load()
        if while_waiting.require("branch-a").status is not GraphTaskStatus.HUMAN_WAIT:
            raise AssertionError("branch-a did not enter HUMAN_WAIT")
        if while_waiting.require("branch-a").decision_id != "decision-a":
            raise AssertionError("branch-a lost decision_id")
        if "branch-a-child" in _ids(while_waiting):
            raise AssertionError("dependent child escaped HUMAN_WAIT block")
        if _ids(while_waiting) != ["branch-b"]:
            raise AssertionError("independent branch did not remain runnable")

        selected = next_runnable_task(while_waiting)
        if selected is None or selected.task_id != "branch-b":
            raise AssertionError("scheduler did not select independent branch-b")
        after_b = transition_task(
            while_waiting,
            task_id="branch-b",
            target_status=GraphTaskStatus.RUNNING,
        )
        after_b = transition_task(
            after_b,
            task_id="branch-b",
            target_status=GraphTaskStatus.COMPLETED,
        )
        store.save(after_b)

        after_b_reload = store.load()
        if after_b_reload.require("branch-b").status is not GraphTaskStatus.COMPLETED:
            raise AssertionError("independent branch-b did not complete")
        if _ids(after_b_reload) != []:
            raise AssertionError("waiting descendant became runnable too early")

        resumed = resume_task_after_decision(
            after_b_reload,
            task_id="branch-a",
            decision_id="decision-a",
        )
        if _ids(resumed) != ["branch-a"]:
            raise AssertionError("resolved branch-a did not become runnable")

        resumed = transition_task(
            resumed,
            task_id="branch-a",
            target_status=GraphTaskStatus.RUNNING,
        )
        resumed = transition_task(
            resumed,
            task_id="branch-a",
            target_status=GraphTaskStatus.COMPLETED,
        )
        store.save(resumed)

        final = store.load()
        if _ids(final) != ["branch-a-child"]:
            raise AssertionError("dependent child did not unlock after branch-a completion")

        return {
            "ok": True,
            "waiting_branch": "branch-a",
            "independent_completed": (
                final.require("branch-b").status is GraphTaskStatus.COMPLETED
            ),
            "blocked_child": "branch-a-child",
            "unlocked_after_resolution": _ids(final),
            "decision_id": "decision-a",
        }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
