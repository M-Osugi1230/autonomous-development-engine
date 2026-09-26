from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_dag():
    path = TRUSTED_DIR / "dag_controller.py"
    spec = importlib.util.spec_from_file_location("trusted_dag_controller_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load trusted dag_controller.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "title": f"Task {task_id}",
        "prompt": f"Implement {task_id}",
        "starting_branch": "main",
        "auto_create_pr": True,
        "timeout_seconds": 1800,
        "poll_interval_seconds": 15,
    }


def node(
    task_id: str,
    *,
    status: str = "PENDING",
    depends_on: list[str] | None = None,
    decision_id: str | None = None,
) -> dict:
    return {
        "task": task(task_id),
        "depends_on": list(depends_on or []),
        "status": status,
        "decision_id": decision_id,
    }


class TrustedDagControllerTests(unittest.TestCase):
    def test_independent_branch_runs_while_other_branch_human_waits(self) -> None:
        module = load_dag()
        graph = {
            "schema_version": 1,
            "tasks": [
                node("current", status="RUNNING"),
                node("waiting", status="HUMAN_WAIT", decision_id="decision-1"),
                node("blocked", depends_on=["waiting"]),
                node("independent", depends_on=["current"]),
            ],
        }

        updated, selected = module.advance_managed_graph(
            graph,
            completed_task_id="current",
        )

        self.assertEqual(updated["tasks"][0]["status"], "COMPLETED")
        self.assertEqual(updated["tasks"][1]["status"], "HUMAN_WAIT")
        self.assertEqual(updated["tasks"][2]["status"], "PENDING")
        self.assertEqual(updated["tasks"][3]["status"], "RUNNING")
        self.assertEqual(selected["task_id"], "independent")

    def test_failed_dependency_blocks_descendant(self) -> None:
        module = load_dag()
        graph = {
            "schema_version": 1,
            "tasks": [
                node("current", status="RUNNING"),
                node("failed", status="FAILED"),
                node("blocked", depends_on=["failed"]),
            ],
        }

        updated, selected = module.advance_managed_graph(
            graph,
            completed_task_id="current",
        )

        self.assertIsNone(selected)
        self.assertTrue(module.graph_has_unfinished_work(updated))
        self.assertEqual(updated["tasks"][2]["status"], "PENDING")

    def test_current_task_must_be_running(self) -> None:
        module = load_dag()
        graph = {
            "schema_version": 1,
            "tasks": [node("current", status="PENDING")],
        }
        with self.assertRaises(module.TrustedDagError):
            module.advance_managed_graph(
                graph,
                completed_task_id="current",
            )

    def test_cycle_and_missing_dependency_are_rejected(self) -> None:
        module = load_dag()
        with self.assertRaises(module.TrustedDagError):
            module.validate_graph_payload(
                {
                    "schema_version": 1,
                    "tasks": [
                        node("a", depends_on=["b"]),
                        node("b", depends_on=["a"]),
                    ],
                }
            )

        with self.assertRaises(module.TrustedDagError):
            module.validate_graph_payload(
                {
                    "schema_version": 1,
                    "tasks": [node("a", depends_on=["missing"])],
                }
            )

    def test_validation_does_not_mutate_caller_payload(self) -> None:
        module = load_dag()
        graph = {
            "schema_version": 1,
            "tasks": [node("a")],
        }
        validated = module.validate_graph_payload(graph)
        validated["tasks"][0]["status"] = "FAILED"
        self.assertEqual(graph["tasks"][0]["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
