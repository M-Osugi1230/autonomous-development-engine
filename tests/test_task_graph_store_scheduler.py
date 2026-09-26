from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    CycleTask,
    GraphTaskStatus,
    TaskGraph,
    TaskGraphStore,
    TaskNode,
    next_runnable_task,
    runnable_tasks,
)


def task(task_id: str) -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title=f"Task {task_id}",
        prompt=f"Implement {task_id}",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )


class TaskGraphStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "nested" / "task-graph.json"
        self.store = TaskGraphStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_file_is_explicit(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.store.load()

    def test_round_trip_creates_parent_and_replaces_atomically(self) -> None:
        first = TaskGraph(tasks=(TaskNode(task=task("a")),))
        second = TaskGraph(tasks=(TaskNode(task=task("b")),))
        self.store.save(first)
        self.assertEqual(self.store.load(), first)
        self.store.save(second)
        self.assertEqual(self.store.load(), second)
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])

    def test_invalid_json_object_and_graph_are_rejected(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{bad", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tasks": [
                        {
                            "task": {
                                "task_id": "b",
                                "title": "B",
                                "prompt": "B",
                                "timeout_seconds": 60,
                                "poll_interval_seconds": 5,
                            },
                            "depends_on": ["missing"],
                            "status": "PENDING",
                            "decision_id": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.store.load()

    def test_save_rejects_non_graph(self) -> None:
        with self.assertRaises(TypeError):
            self.store.save({})  # type: ignore[arg-type]


class TaskSchedulerTests(unittest.TestCase):
    def test_roots_are_runnable_in_declared_order(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("b")),
                TaskNode(task=task("a")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["b", "a"],
        )
        self.assertEqual(next_runnable_task(graph).task_id, "b")  # type: ignore[union-attr]

    def test_dependencies_must_be_completed(self) -> None:
        for status in (
            GraphTaskStatus.PENDING,
            GraphTaskStatus.RUNNING,
            GraphTaskStatus.HUMAN_WAIT,
            GraphTaskStatus.FAILED,
        ):
            with self.subTest(status=status):
                dependency_kwargs = {}
                if status is GraphTaskStatus.HUMAN_WAIT:
                    dependency_kwargs["decision_id"] = "decision-a"
                graph = TaskGraph(
                    tasks=(
                        TaskNode(
                            task=task("a"),
                            status=status,
                            **dependency_kwargs,
                        ),
                        TaskNode(task=task("b"), depends_on=("a",)),
                    )
                )
                runnable_ids = [node.task_id for node in runnable_tasks(graph)]
                self.assertNotIn("b", runnable_ids)
                if status is GraphTaskStatus.PENDING:
                    self.assertEqual(runnable_ids, ["a"])
                else:
                    self.assertEqual(runnable_ids, [])

        graph = TaskGraph(
            tasks=(
                TaskNode(
                    task=task("a"),
                    status=GraphTaskStatus.COMPLETED,
                ),
                TaskNode(task=task("b"), depends_on=("a",)),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["b"],
        )

    def test_human_wait_blocks_only_descendants(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(
                    task=task("a"),
                    status=GraphTaskStatus.HUMAN_WAIT,
                    decision_id="decision-a",
                ),
                TaskNode(task=task("a-child"), depends_on=("a",)),
                TaskNode(task=task("independent")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["independent"],
        )

    def test_failed_dependency_blocks_descendant_but_not_independent(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("a"), status=GraphTaskStatus.FAILED),
                TaskNode(task=task("a-child"), depends_on=("a",)),
                TaskNode(task=task("independent")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["independent"],
        )

    def test_non_pending_nodes_are_not_returned(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("run"), status=GraphTaskStatus.RUNNING),
                TaskNode(task=task("done"), status=GraphTaskStatus.COMPLETED),
                TaskNode(task=task("pending")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["pending"],
        )

    def test_limit_is_deterministic_and_validated(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("a")),
                TaskNode(task=task("b")),
                TaskNode(task=task("c")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph, limit=2)],
            ["a", "b"],
        )
        with self.assertRaises(ValueError):
            runnable_tasks(graph, limit=0)
        with self.assertRaises(ValueError):
            runnable_tasks(graph, limit=True)  # type: ignore[arg-type]

    def test_no_runnable_task_returns_none(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("done"), status=GraphTaskStatus.COMPLETED),
            )
        )
        self.assertIsNone(next_runnable_task(graph))


if __name__ == "__main__":
    unittest.main()
