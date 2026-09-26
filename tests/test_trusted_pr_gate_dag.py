from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_gate():
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        path = TRUSTED_DIR / "ade_pr_gate.py"
        spec = importlib.util.spec_from_file_location("trusted_pr_gate_dag_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load trusted ade_pr_gate.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def task(task_id: str) -> dict:
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


def graph_node(
    task_id: str,
    *,
    status: str = "PENDING",
    depends_on: list[str] | None = None,
    decision_id: str | None = None,
) -> dict:
    return {
        "task": {k: v for k, v in task(task_id).items() if k != "schema_version"},
        "depends_on": list(depends_on or []),
        "status": status,
        "decision_id": decision_id,
    }


class FakeApi:
    def __init__(self, module, *, state, queue, cycle_task, graph=None):
        self.module = module
        self.files = {
            ".autodev/state.json": [copy.deepcopy(state), "state-sha"],
            ".autodev/task-queue.json": [copy.deepcopy(queue), "queue-sha"],
            ".autodev/cycle-task.json": [copy.deepcopy(cycle_task), "cycle-sha"],
        }
        if graph is not None:
            self.files[".autodev/task-graph.json"] = [copy.deepcopy(graph), "graph-sha"]
        self.writes = []
        self.dispatches = []

    def get_json_file(self, path, *, ref="main"):
        if path not in self.files:
            raise self.module.GitHubError(
                "GitHub HTTP 404: {\"message\":\"Not Found\"}"
            )
        payload, sha = self.files[path]
        return copy.deepcopy(payload), sha

    def put_json_file(self, path, payload, *, sha, message, branch="main"):
        self.writes.append((path, copy.deepcopy(payload), sha, message, branch))
        self.files[path] = [copy.deepcopy(payload), f"{path}-new-sha"]

    def dispatch(self, event_type, payload=None):
        self.dispatches.append((event_type, copy.deepcopy(payload or {})))


def base_state(current_task_id: str) -> dict:
    return {
        "schema_version": 1,
        "project_id": "ade",
        "provider": "jules",
        "status": "READY",
        "current_task_id": current_task_id,
        "completed_task_ids": [],
        "failed_task_ids": [],
        "iteration": 0,
        "metadata": {},
        "updated_at": "2026-09-26T00:00:00+00:00",
    }


class TrustedPrGateDagTests(unittest.TestCase):
    def test_fifo_behavior_is_preserved_without_graph(self) -> None:
        module = load_gate()
        api = FakeApi(
            module,
            state=base_state("current"),
            queue={"schema_version": 1, "tasks": [task("fifo-next")]},
            cycle_task=task("current"),
        )

        selected = module.advance_queue(api, completed_task_id="current")

        self.assertEqual(selected, "fifo-next")
        self.assertEqual(api.files[".autodev/state.json"][0]["current_task_id"], "fifo-next")
        self.assertEqual(api.files[".autodev/state.json"][0]["metadata"]["scheduler"], "fifo")
        self.assertEqual(api.dispatches, [("ade_next_cycle", {"task_id": "fifo-next"})])

    def test_dag_selects_independent_task_and_removes_duplicate_fifo_entry(self) -> None:
        module = load_gate()
        graph = {
            "schema_version": 1,
            "tasks": [
                graph_node("current", status="RUNNING"),
                graph_node("waiting", status="HUMAN_WAIT", decision_id="decision-1"),
                graph_node("blocked", depends_on=["waiting"]),
                graph_node("independent", depends_on=["current"]),
            ],
        }
        api = FakeApi(
            module,
            state=base_state("current"),
            queue={
                "schema_version": 1,
                "tasks": [task("independent"), task("later-fifo")],
            },
            cycle_task=task("current"),
            graph=graph,
        )

        selected = module.advance_queue(api, completed_task_id="current")

        self.assertEqual(selected, "independent")
        updated_graph = api.files[".autodev/task-graph.json"][0]
        statuses = {
            node["task"]["task_id"]: node["status"]
            for node in updated_graph["tasks"]
        }
        self.assertEqual(statuses["current"], "COMPLETED")
        self.assertEqual(statuses["waiting"], "HUMAN_WAIT")
        self.assertEqual(statuses["blocked"], "PENDING")
        self.assertEqual(statuses["independent"], "RUNNING")
        queue_ids = [
            item["task_id"]
            for item in api.files[".autodev/task-queue.json"][0]["tasks"]
        ]
        self.assertEqual(queue_ids, ["later-fifo"])
        self.assertEqual(api.files[".autodev/state.json"][0]["metadata"]["scheduler"], "dag")

    def test_active_graph_with_only_blocked_work_does_not_fall_back_to_fifo(self) -> None:
        module = load_gate()
        graph = {
            "schema_version": 1,
            "tasks": [
                graph_node("current", status="RUNNING"),
                graph_node("waiting", status="HUMAN_WAIT", decision_id="decision-1"),
                graph_node("blocked", depends_on=["waiting"]),
            ],
        }
        api = FakeApi(
            module,
            state=base_state("current"),
            queue={"schema_version": 1, "tasks": [task("unsafe-fifo")]},
            cycle_task=task("current"),
            graph=graph,
        )

        selected = module.advance_queue(api, completed_task_id="current")

        self.assertIsNone(selected)
        state = api.files[".autodev/state.json"][0]
        self.assertEqual(state["status"], "BLOCKED")
        self.assertTrue(state["metadata"]["dag_blocked"])
        self.assertEqual(
            api.files[".autodev/task-queue.json"][0]["tasks"][0]["task_id"],
            "unsafe-fifo",
        )
        self.assertEqual(api.dispatches, [])

    def test_graph_not_managing_current_task_keeps_fifo_fallback(self) -> None:
        module = load_gate()
        graph = {
            "schema_version": 1,
            "tasks": [
                graph_node("unrelated", status="PENDING"),
            ],
        }
        api = FakeApi(
            module,
            state=base_state("current"),
            queue={"schema_version": 1, "tasks": [task("fifo-next")]},
            cycle_task=task("current"),
            graph=graph,
        )

        selected = module.advance_queue(api, completed_task_id="current")

        self.assertEqual(selected, "fifo-next")
        self.assertEqual(api.dispatches, [("ade_next_cycle", {"task_id": "fifo-next"})])

    def test_state_current_task_mismatch_is_rejected(self) -> None:
        module = load_gate()
        api = FakeApi(
            module,
            state=base_state("other"),
            queue={"schema_version": 1, "tasks": []},
            cycle_task=task("current"),
        )

        with self.assertRaises(RuntimeError):
            module.advance_queue(api, completed_task_id="current")
        self.assertEqual(api.dispatches, [])


if __name__ == "__main__":
    unittest.main()
