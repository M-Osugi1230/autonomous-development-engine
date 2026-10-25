from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from ade.cycle import CycleTask
from ade.review_wait import ReviewWaitLedger, ReviewWaitRecord
from ade.task_graph import GraphTaskStatus, TaskGraph, TaskNode
from ade.task_graph_transition import (
    reconcile_waiting_review_task,
    transition_task,
)
from ade.task_scheduler import runnable_tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "trusted"))

from dag_controller import (  # noqa: E402
    park_managed_graph_for_review,
    reconcile_waiting_review,
)


def cycle_task(task_id: str) -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title=f"Task {task_id}",
        prompt=f"Implement {task_id}",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )


def cycle_task_payload(task_id: str) -> dict:
    task = cycle_task(task_id)
    return {
        "task_id": task.task_id,
        "title": task.title,
        "prompt": task.prompt,
        "starting_branch": task.starting_branch,
        "auto_create_pr": task.auto_create_pr,
        "timeout_seconds": task.timeout_seconds,
        "poll_interval_seconds": task.poll_interval_seconds,
    }


def graph_payload() -> dict:
    return {
        "schema_version": 1,
        "tasks": [
            {
                "task": cycle_task_payload("a"),
                "depends_on": [],
                "status": "RUNNING",
                "decision_id": None,
            },
            {
                "task": cycle_task_payload("b"),
                "depends_on": ["a"],
                "status": "PENDING",
                "decision_id": None,
            },
            {
                "task": cycle_task_payload("c"),
                "depends_on": [],
                "status": "PENDING",
                "decision_id": None,
            },
        ],
    }


class ReviewWaitModelTests(unittest.TestCase):
    def test_ledger_round_trip_and_idempotent_upsert(self) -> None:
        now = datetime.now(UTC).isoformat()
        record = ReviewWaitRecord(
            task_id="a",
            target_repository="owner/repo",
            pull_request_url="https://github.com/owner/repo/pull/7",
            reason="review-required",
            created_at=now,
            updated_at=now,
            depends_on=("root",),
        )
        ledger = ReviewWaitLedger().upsert(record).upsert(record)
        self.assertEqual(len(ledger.records), 1)
        restored = ReviewWaitLedger.from_dict(ledger.to_dict())
        self.assertEqual(restored, ledger)
        self.assertEqual(restored.records[0].pull_request_number, 7)

    def test_task_transition_review_wait_requires_trusted_reconcile(self) -> None:
        graph = TaskGraph(
            tasks=(TaskNode(task=cycle_task("a"), status=GraphTaskStatus.RUNNING),)
        )
        parked = transition_task(
            graph,
            task_id="a",
            target_status=GraphTaskStatus.WAITING_REVIEW,
        )
        self.assertEqual(
            parked.require("a").status,
            GraphTaskStatus.WAITING_REVIEW,
        )
        with self.assertRaises(ValueError):
            transition_task(
                parked,
                task_id="a",
                target_status=GraphTaskStatus.COMPLETED,
            )
        reconciled = reconcile_waiting_review_task(parked, task_id="a")
        self.assertEqual(
            reconciled.require("a").status,
            GraphTaskStatus.COMPLETED,
        )
        self.assertIs(
            reconcile_waiting_review_task(reconciled, task_id="a"),
            reconciled,
        )

    def test_scheduler_runs_independent_task_but_not_dependent(self) -> None:
        graph = TaskGraph(
            tasks=(
                TaskNode(
                    task=cycle_task("a"),
                    status=GraphTaskStatus.WAITING_REVIEW,
                ),
                TaskNode(task=cycle_task("b"), depends_on=("a",)),
                TaskNode(task=cycle_task("c")),
            )
        )
        self.assertEqual(
            [node.task_id for node in runnable_tasks(graph)],
            ["c"],
        )


class TrustedDagReviewWaitTests(unittest.TestCase):
    def test_independent_task_continues_while_review_waits(self) -> None:
        parked, next_task = park_managed_graph_for_review(
            graph_payload(),
            task_id="a",
        )
        statuses = {
            node["task"]["task_id"]: node["status"]
            for node in parked["tasks"]
        }
        self.assertEqual(statuses["a"], "WAITING_REVIEW")
        self.assertEqual(statuses["b"], "PENDING")
        self.assertEqual(statuses["c"], "RUNNING")
        self.assertEqual(next_task["task_id"], "c")

    def test_late_merge_reconciles_without_disrupting_active_task(self) -> None:
        parked, _ = park_managed_graph_for_review(
            graph_payload(),
            task_id="a",
        )
        reconciled, next_task = reconcile_waiting_review(
            parked,
            task_id="a",
        )
        statuses = {
            node["task"]["task_id"]: node["status"]
            for node in reconciled["tasks"]
        }
        self.assertEqual(statuses["a"], "COMPLETED")
        self.assertEqual(statuses["b"], "PENDING")
        self.assertEqual(statuses["c"], "RUNNING")
        self.assertIsNone(next_task)

    def test_duplicate_late_merge_is_idempotent(self) -> None:
        parked, _ = park_managed_graph_for_review(
            graph_payload(),
            task_id="a",
        )
        reconciled, _ = reconcile_waiting_review(parked, task_id="a")
        replayed, next_task = reconcile_waiting_review(reconciled, task_id="a")
        self.assertEqual(replayed, reconciled)
        self.assertIsNone(next_task)


if __name__ == "__main__":
    unittest.main()
