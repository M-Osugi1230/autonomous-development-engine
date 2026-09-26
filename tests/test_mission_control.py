from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    CheckpointState,
    CheckpointStore,
    DecisionPriority,
    DecisionRecord,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    DecisionStore,
    MissionControlSnapshot,
    TaskCheckpoint,
    build_mission_control_snapshot,
)


class MissionControlSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.autodev = self.root / ".autodev"
        (self.autodev / "runtime").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: object) -> None:
        path = self.autodev / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_base_fixture(self) -> None:
        self.write_json(
            "state.json",
            {
                "schema_version": 1,
                "project_id": "ade-test",
                "status": "RUNNING",
                "iteration": 5,
                "current_task_id": "task-5",
                "completed_task_ids": ["task-1", "task-2", "task-3", "task-4"],
                "failed_task_ids": ["task-failed"],
                "provider": "jules",
                "updated_at": "2026-09-26T01:00:00+00:00",
                "metadata": {
                    "phase": "phase8 bearer abc.def-ghi",
                    "milestone": "read-only-snapshot",
                    "queue_exhausted": False,
                    "unrelated_private_metadata": "must-not-render",
                },
            },
        )
        self.write_json(
            "task-queue.json",
            {
                "schema_version": 1,
                "tasks": [{"task_id": "task-6"}, {"task_id": "task-7"}],
            },
        )
        self.write_json(
            "failures.json",
            {
                "schema_version": 1,
                "failures": [{"task_id": "task-failed", "detail": "not rendered"}],
            },
        )
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": 2,
                "cycles_completed": 1,
                "repair_attempts": 1,
                "human_interrupts": 1,
                "quota_pauses": 1,
            },
        )

        CheckpointStore(self.autodev / "runtime" / "checkpoint.json").save(
            TaskCheckpoint(
                task_id="task-5",
                state=CheckpointState.RUNNING,
                attempt=1,
                replan_count=0,
                provider_session_id="provider-session-must-not-render",
                last_error="safe diagnostic that should still not render",
            )
        )

        store = DecisionStore(self.autodev / "decisions.json")
        open_request = DecisionRequest(
            decision_id="decision-open",
            question="Approve the irreversible migration?",
            options=("approve", "reject"),
            priority=DecisionPriority.P0,
            blocking_task_id="task-5",
            context={"private": "decision-context-must-not-render"},
        )
        resolved_request = DecisionRequest(
            decision_id="decision-resolved",
            question="Choose a style?",
            options=("compact", "detailed"),
            priority=DecisionPriority.P2,
            blocking_task_id="task-4",
            context={"private": "resolved-context-must-not-render"},
        )
        store.save(
            [
                DecisionRecord(request=open_request),
                DecisionRecord(
                    request=resolved_request,
                    status=DecisionStatus.RESOLVED,
                    response=DecisionResponse(
                        decision_id="decision-resolved",
                        text="Use compact.",
                        selected_option="compact",
                    ),
                ),
            ]
        )

    def test_snapshot_aggregates_only_safe_read_only_fields(self) -> None:
        self.write_base_fixture()

        snapshot = build_mission_control_snapshot(self.root)
        self.assertIsInstance(snapshot, MissionControlSnapshot)
        self.assertEqual(snapshot.project_id, "ade-test")
        self.assertEqual(snapshot.project_status, "RUNNING")
        self.assertEqual(snapshot.iteration, 5)
        self.assertEqual(snapshot.current_task_id, "task-5")
        self.assertEqual(snapshot.completed_tasks, 4)
        self.assertEqual(snapshot.failed_tasks, 1)
        self.assertEqual(snapshot.failure_ledger_count, 1)
        self.assertEqual(snapshot.queue_depth, 2)
        self.assertFalse(snapshot.queue_exhausted)
        self.assertEqual(snapshot.milestone, "read-only-snapshot")
        self.assertEqual(snapshot.phase, "phase8 [REDACTED]")

        self.assertIsNotNone(snapshot.checkpoint)
        assert snapshot.checkpoint is not None
        self.assertEqual(snapshot.checkpoint.task_id, "task-5")
        self.assertEqual(snapshot.checkpoint.state, "RUNNING")
        self.assertTrue(snapshot.checkpoint.provider_session_present)

        self.assertEqual(len(snapshot.open_decisions), 1)
        self.assertEqual(snapshot.open_decisions[0].decision_id, "decision-open")
        self.assertEqual(
            snapshot.open_decisions[0].question,
            "Approve the irreversible migration?",
        )

        serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
        self.assertNotIn("provider-session-must-not-render", serialized)
        self.assertNotIn("safe diagnostic that should still not render", serialized)
        self.assertNotIn("decision-context-must-not-render", serialized)
        self.assertNotIn("resolved-context-must-not-render", serialized)
        self.assertNotIn("must-not-render", serialized)

    def test_stale_metrics_warning_is_derived_from_state(self) -> None:
        self.write_base_fixture()

        snapshot = build_mission_control_snapshot(self.root)

        self.assertIn(
            "telemetry metrics lag project iteration",
            snapshot.warnings,
        )
        self.assertNotIn(
            "failure ledger count differs from state failed task count",
            snapshot.warnings,
        )

    def test_absent_checkpoint_is_supported(self) -> None:
        self.write_base_fixture()
        (self.autodev / "runtime" / "checkpoint.json").unlink()

        snapshot = build_mission_control_snapshot(self.root)

        self.assertIsNone(snapshot.checkpoint)

    def test_human_wait_without_open_decision_emits_warning(self) -> None:
        self.write_base_fixture()
        state = json.loads((self.autodev / "state.json").read_text(encoding="utf-8"))
        state["status"] = "HUMAN_WAIT"
        self.write_json("state.json", state)
        DecisionStore(self.autodev / "decisions.json").save([])

        snapshot = build_mission_control_snapshot(self.root)

        self.assertIn(
            "project is HUMAN_WAIT but no open human decision exists",
            snapshot.warnings,
        )

    def test_nonterminal_checkpoint_without_current_task_emits_warning(self) -> None:
        self.write_base_fixture()
        state = json.loads((self.autodev / "state.json").read_text(encoding="utf-8"))
        state["status"] = "READY"
        state["current_task_id"] = None
        self.write_json("state.json", state)

        snapshot = build_mission_control_snapshot(self.root)

        self.assertIn(
            "non-terminal checkpoint exists without a current task",
            snapshot.warnings,
        )

    def test_malformed_ledgers_are_rejected(self) -> None:
        self.write_base_fixture()
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": -1,
                "cycles_completed": 1,
                "repair_attempts": 0,
                "human_interrupts": 0,
                "quota_pauses": 0,
            },
        )
        with self.assertRaises(ValueError):
            build_mission_control_snapshot(self.root)

        self.write_base_fixture()
        self.write_json(
            "task-queue.json",
            {"schema_version": 2, "tasks": []},
        )
        with self.assertRaises(ValueError):
            build_mission_control_snapshot(self.root)


if __name__ == "__main__":
    unittest.main()
