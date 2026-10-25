from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from ade.cycle import CycleTask
from ade.remote_execution import RemoteExecutionReceipt
from ade.review_wait import ReviewWaitLedger, ReviewWaitRecord
from ade.task_graph import GraphTaskStatus, TaskGraph, TaskNode
from ade.task_graph_transition import (
    reconcile_waiting_review_task,
    transition_task,
)
from ade.task_scheduler import runnable_tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "trusted"))

import review_wait_controller  # noqa: E402
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


class FakeReviewApi:
    def __init__(self, *, record: ReviewWaitRecord) -> None:
        self.files = {
            review_wait_controller.REVIEW_WAITS_PATH: ReviewWaitLedger(
                records=(record,)
            ).to_dict(),
            review_wait_controller.STATE_PATH: {
                "schema_version": 1,
                "project_id": "test-project",
                "status": "HUMAN_WAIT",
                "iteration": 0,
                "current_task_id": None,
                "completed_task_ids": [],
                "failed_task_ids": [],
                "metadata": {
                    "waiting_review_count": 1,
                    "waiting_review_task_ids": [record.task_id],
                },
            },
            review_wait_controller.QUEUE_PATH: {
                "schema_version": 1,
                "tasks": [{"task_id": "next-task"}],
            },
            review_wait_controller.CAMPAIGN_PATH: {
                "schema_version": 1,
                "task_ids": [record.task_id, "next-task"],
                "completed_task_ids": [],
                "status": "HUMAN_WAIT",
            },
        }
        self.writes: list[str] = []

    def get_json_file(self, path: str):
        if path not in self.files:
            raise AssertionError(f"unexpected get_json_file path: {path}")
        return self.files[path], f"sha-{path}"

    def put_json_file(self, path: str, payload: dict, *, sha: str, message: str):
        del sha, message
        self.files[path] = payload
        self.writes.append(path)

    def upsert_json_file(self, path: str, payload: dict, *, message: str):
        del message
        self.files[path] = payload
        self.writes.append(path)

    def dispatch(self, event_type: str, payload: dict):
        raise AssertionError(f"unexpected dispatch {event_type}: {payload}")


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
            expected_base_branch="main",
        )
        ledger = ReviewWaitLedger().upsert(record).upsert(record)
        self.assertEqual(len(ledger.records), 1)
        restored = ReviewWaitLedger.from_dict(ledger.to_dict())
        self.assertEqual(restored, ledger)
        self.assertEqual(restored.records[0].pull_request_number, 7)
        self.assertEqual(restored.records[0].expected_base_branch, "main")

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


class ReviewWaitControllerRegressionTests(unittest.TestCase):
    def record(self) -> ReviewWaitRecord:
        now = datetime.now(UTC).isoformat()
        return ReviewWaitRecord(
            task_id="legacy-task",
            target_repository="owner/repo",
            pull_request_url="https://github.com/owner/repo/pull/9",
            reason="target-pull-request-not-merged-yet",
            created_at=now,
            updated_at=now,
            expected_base_branch="main",
        )

    def receipt(self) -> RemoteExecutionReceipt:
        return RemoteExecutionReceipt(
            task_id="legacy-task",
            target_repository="owner/repo",
            pull_request_url="https://github.com/owner/repo/pull/9",
            recorded_at=datetime.now(UTC).isoformat(),
            status="PR_CREATED",
        )

    def test_legacy_fifo_late_merge_can_complete_and_clear_wait(self) -> None:
        api = FakeReviewApi(record=self.record())

        def fake_advance(fake_api, *, completed_task_id):
            self.assertIs(fake_api, api)
            self.assertEqual(completed_task_id, "legacy-task")
            state = api.files[review_wait_controller.STATE_PATH]
            state["completed_task_ids"] = ["legacy-task"]
            state["current_task_id"] = "next-task"
            state["status"] = "READY"
            state["iteration"] = 1
            campaign = api.files[review_wait_controller.CAMPAIGN_PATH]
            campaign["completed_task_ids"] = ["legacy-task"]
            campaign["status"] = "RUNNING"
            return "next-task"

        with (
            patch.object(review_wait_controller, "_validate_late_merge_identity"),
            patch.object(review_wait_controller, "_optional_json") as optional_json,
            patch.object(review_wait_controller, "advance_queue", side_effect=fake_advance),
        ):
            optional_json.side_effect = lambda _api, path: (
                None
                if path == review_wait_controller.TASK_GRAPH_PATH
                else (
                    api.files[path],
                    f"sha-{path}",
                )
            )
            changed, next_task = review_wait_controller.reconcile_review_wait_merge(
                api,
                receipt=self.receipt(),
            )

        self.assertTrue(changed)
        self.assertEqual(next_task, "next-task")
        ledger = ReviewWaitLedger.from_dict(
            api.files[review_wait_controller.REVIEW_WAITS_PATH]
        )
        self.assertEqual(ledger.records, ())
        state = api.files[review_wait_controller.STATE_PATH]
        self.assertEqual(state["completed_task_ids"], ["legacy-task"])
        self.assertEqual(state["current_task_id"], "next-task")
        self.assertEqual(state["metadata"]["waiting_review_count"], 0)

    def test_reconciliation_failure_retains_durable_wait_record(self) -> None:
        api = FakeReviewApi(record=self.record())
        with (
            patch.object(review_wait_controller, "_validate_late_merge_identity"),
            patch.object(review_wait_controller, "_optional_json", return_value=None),
            patch.object(
                review_wait_controller,
                "advance_queue",
                side_effect=RuntimeError("injected state transition failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                review_wait_controller.reconcile_review_wait_merge(
                    api,
                    receipt=self.receipt(),
                )

        ledger = ReviewWaitLedger.from_dict(
            api.files[review_wait_controller.REVIEW_WAITS_PATH]
        )
        self.assertEqual([record.task_id for record in ledger.records], ["legacy-task"])


if __name__ == "__main__":
    unittest.main()
