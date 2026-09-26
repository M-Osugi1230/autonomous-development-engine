from __future__ import annotations

import unittest

from ade import (
    CycleTask,
    GraphTaskStatus,
    TaskGraph,
    TaskNode,
    resume_task_after_decision,
    transition_task,
)


def task(task_id: str) -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title=f"Task {task_id}",
        prompt=f"Implement {task_id}",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )


class TaskGraphTransitionTests(unittest.TestCase):
    def test_pending_to_running_requires_completed_dependencies(self) -> None:
        blocked = TaskGraph(
            tasks=(
                TaskNode(task=task("a")),
                TaskNode(task=task("b"), depends_on=("a",)),
            )
        )
        with self.assertRaises(ValueError):
            transition_task(
                blocked,
                task_id="b",
                target_status=GraphTaskStatus.RUNNING,
            )

        ready = TaskGraph(
            tasks=(
                TaskNode(task=task("a"), status=GraphTaskStatus.COMPLETED),
                TaskNode(task=task("b"), depends_on=("a",)),
            )
        )
        transitioned = transition_task(
            ready,
            task_id="b",
            target_status=GraphTaskStatus.RUNNING,
        )
        self.assertEqual(
            transitioned.require("b").status,
            GraphTaskStatus.RUNNING,
        )
        self.assertEqual(ready.require("b").status, GraphTaskStatus.PENDING)

    def test_running_can_complete_or_fail(self) -> None:
        for target in (
            GraphTaskStatus.COMPLETED,
            GraphTaskStatus.FAILED,
        ):
            with self.subTest(target=target):
                graph = TaskGraph(
                    tasks=(
                        TaskNode(
                            task=task("a"),
                            status=GraphTaskStatus.RUNNING,
                        ),
                    )
                )
                transitioned = transition_task(
                    graph,
                    task_id="a",
                    target_status=target,
                )
                self.assertEqual(transitioned.require("a").status, target)

    def test_running_to_human_wait_requires_decision_id(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(
                    task=task("a"),
                    status=GraphTaskStatus.RUNNING,
                ),
            )
        )
        with self.assertRaises(ValueError):
            transition_task(
                graph,
                task_id="a",
                target_status=GraphTaskStatus.HUMAN_WAIT,
            )

        waiting = transition_task(
            graph,
            task_id="a",
            target_status=GraphTaskStatus.HUMAN_WAIT,
            decision_id="decision-a",
        )
        node = waiting.require("a")
        self.assertEqual(node.status, GraphTaskStatus.HUMAN_WAIT)
        self.assertEqual(node.decision_id, "decision-a")

    def test_human_wait_requires_explicit_matching_resolution(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(
                    task=task("a"),
                    status=GraphTaskStatus.HUMAN_WAIT,
                    decision_id="decision-a",
                ),
            )
        )
        with self.assertRaises(ValueError):
            transition_task(
                graph,
                task_id="a",
                target_status=GraphTaskStatus.PENDING,
            )
        with self.assertRaises(ValueError):
            resume_task_after_decision(
                graph,
                task_id="a",
                decision_id="wrong",
            )

        resumed = resume_task_after_decision(
            graph,
            task_id="a",
            decision_id="decision-a",
        )
        node = resumed.require("a")
        self.assertEqual(node.status, GraphTaskStatus.PENDING)
        self.assertIsNone(node.decision_id)

    def test_terminal_tasks_cannot_reopen(self) -> None:
        for source in (
            GraphTaskStatus.COMPLETED,
            GraphTaskStatus.FAILED,
        ):
            with self.subTest(source=source):
                graph = TaskGraph(
                    tasks=(TaskNode(task=task("a"), status=source),)
                )
                with self.assertRaises(ValueError):
                    transition_task(
                        graph,
                        task_id="a",
                        target_status=GraphTaskStatus.RUNNING,
                    )

    def test_running_rejects_pending_and_decision_id_on_terminal_transition(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("a"), status=GraphTaskStatus.RUNNING),
            )
        )
        with self.assertRaises(ValueError):
            transition_task(
                graph,
                task_id="a",
                target_status=GraphTaskStatus.PENDING,
            )
        with self.assertRaises(ValueError):
            transition_task(
                graph,
                task_id="a",
                target_status=GraphTaskStatus.COMPLETED,
                decision_id="decision-a",
            )

    def test_transition_preserves_declared_order_and_other_nodes(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(task=task("a"), status=GraphTaskStatus.COMPLETED),
                TaskNode(task=task("b"), depends_on=("a",)),
                TaskNode(task=task("c")),
            )
        )
        transitioned = transition_task(
            graph,
            task_id="b",
            target_status=GraphTaskStatus.RUNNING,
        )
        self.assertEqual(
            [node.task_id for node in transitioned.tasks],
            ["a", "b", "c"],
        )
        self.assertEqual(transitioned.require("c"), graph.require("c"))

    def test_invalid_inputs_and_unknown_task_are_rejected(self) -> None:
        graph = TaskGraph(tasks=(TaskNode(task=task("a")),))
        with self.assertRaises(KeyError):
            transition_task(
                graph,
                task_id="missing",
                target_status=GraphTaskStatus.RUNNING,
            )
        with self.assertRaises(ValueError):
            transition_task(
                graph,
                task_id="a",
                target_status="INVALID",
            )
        with self.assertRaises(ValueError):
            resume_task_after_decision(
                graph,
                task_id="a",
                decision_id="decision-a",
            )


if __name__ == "__main__":
    unittest.main()
