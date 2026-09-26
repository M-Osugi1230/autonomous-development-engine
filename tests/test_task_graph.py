from __future__ import annotations

import copy
import unittest

from ade import CycleTask, GraphTaskStatus, TaskGraph, TaskNode


def cycle_task(task_id: str) -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title=f"Task {task_id}",
        prompt=f"Implement {task_id}",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )


class TaskNodeTests(unittest.TestCase):
    def test_round_trip_and_dependency_normalization(self) -> None:
        node = TaskNode(
            task=cycle_task("b"),
            depends_on=["a"],  # type: ignore[arg-type]
        )
        self.assertEqual(node.depends_on, ("a",))
        self.assertEqual(TaskNode.from_dict(node.to_dict()), node)

    def test_human_wait_requires_decision_and_other_states_reject_it(self) -> None:
        with self.assertRaises(ValueError):
            TaskNode(
                task=cycle_task("wait"),
                status=GraphTaskStatus.HUMAN_WAIT,
            )

        node = TaskNode(
            task=cycle_task("wait"),
            status=GraphTaskStatus.HUMAN_WAIT,
            decision_id="decision-1",
        )
        self.assertEqual(node.decision_id, "decision-1")

        with self.assertRaises(ValueError):
            TaskNode(
                task=cycle_task("pending"),
                status=GraphTaskStatus.PENDING,
                decision_id="decision-1",
            )

    def test_rejects_self_and_duplicate_dependencies(self) -> None:
        with self.assertRaises(ValueError):
            TaskNode(task=cycle_task("a"), depends_on=("a",))
        with self.assertRaises(ValueError):
            TaskNode(task=cycle_task("b"), depends_on=("a", "a"))


class TaskGraphTests(unittest.TestCase):
    def test_round_trip_preserves_declared_order(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=cycle_task("a")),
                TaskNode(task=cycle_task("b"), depends_on=("a",)),
                TaskNode(task=cycle_task("c"), depends_on=("a",)),
            )
        )
        payload = graph.to_dict()
        restored = TaskGraph.from_dict(copy.deepcopy(payload))

        self.assertEqual(restored, graph)
        self.assertEqual([node.task_id for node in restored.tasks], ["a", "b", "c"])
        self.assertEqual(restored.require("b").depends_on, ("a",))
        self.assertIsNone(restored.get("missing"))

    def test_empty_graph_is_valid(self) -> None:
        graph = TaskGraph()
        self.assertEqual(graph.tasks, ())
        self.assertEqual(TaskGraph.from_dict(graph.to_dict()), graph)

    def test_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            TaskGraph(
                tasks=(
                    TaskNode(task=cycle_task("a")),
                    TaskNode(task=cycle_task("a")),
                )
            )

    def test_rejects_missing_dependency(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            TaskGraph(
                tasks=(
                    TaskNode(task=cycle_task("b"), depends_on=("missing",)),
                )
            )
        self.assertIn("missing", str(ctx.exception))

    def test_rejects_two_node_cycle(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            TaskGraph(
                tasks=(
                    TaskNode(task=cycle_task("a"), depends_on=("b",)),
                    TaskNode(task=cycle_task("b"), depends_on=("a",)),
                )
            )
        self.assertIn("cycle", str(ctx.exception))

    def test_rejects_deep_cycle(self) -> None:
        with self.assertRaises(ValueError):
            TaskGraph(
                tasks=(
                    TaskNode(task=cycle_task("a"), depends_on=("c",)),
                    TaskNode(task=cycle_task("b"), depends_on=("a",)),
                    TaskNode(task=cycle_task("c"), depends_on=("b",)),
                )
            )

    def test_from_dict_does_not_mutate_payload(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=cycle_task("a")),
                TaskNode(task=cycle_task("b"), depends_on=("a",)),
            )
        )
        payload = graph.to_dict()
        before = copy.deepcopy(payload)
        TaskGraph.from_dict(payload)
        self.assertEqual(payload, before)

    def test_invalid_schema_and_task_payload_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TaskGraph.from_dict({"schema_version": 2, "tasks": []})
        with self.assertRaises(ValueError):
            TaskGraph.from_dict({"schema_version": 1, "tasks": {}})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
