import unittest

from ade import CheckpointState, FailureKind, TaskCheckpoint


class TaskCheckpointTests(unittest.TestCase):
    def test_round_trip_serialization(self):
        ckpt = TaskCheckpoint(
            task_id="task-123",
            state=CheckpointState.RUNNING,
            attempt=1,
            replan_count=0,
            provider_session_id="session-xyz",
            last_failure_kind=FailureKind.CYCLE_TIMEOUT,
            last_error="Cycle timed out after 300s",
        )
        d = ckpt.to_dict()
        expected_dict = {
            "task_id": "task-123",
            "state": "RUNNING",
            "attempt": 1,
            "replan_count": 0,
            "provider_session_id": "session-xyz",
            "provider_id": None,
            "last_failure_kind": "CYCLE_TIMEOUT",
            "last_error": "Cycle timed out after 300s",
            "resume_after": None,
        }
        self.assertEqual(d, expected_dict)

        restored = TaskCheckpoint.from_dict(d)
        self.assertEqual(restored, ckpt)
        self.assertEqual(restored.to_dict(), expected_dict)

    def test_quota_pause_state(self):
        ckpt = TaskCheckpoint(
            task_id="task-quota",
            state=CheckpointState.PAUSED_QUOTA,
            attempt=2,
            replan_count=1,
            provider_session_id="session-q1",
            last_failure_kind=FailureKind.PROVIDER_QUOTA,
            last_error="Quota limit reached",
            resume_after="2026-03-30T12:00:00Z",
        )
        self.assertEqual(ckpt.state, CheckpointState.PAUSED_QUOTA)
        self.assertEqual(ckpt.resume_after, "2026-03-30T12:00:00Z")
        self.assertEqual(ckpt.last_failure_kind, FailureKind.PROVIDER_QUOTA)

        d = ckpt.to_dict()
        restored = TaskCheckpoint.from_dict(d)
        self.assertEqual(restored, ckpt)

    def test_human_wait_state(self):
        ckpt = TaskCheckpoint(
            task_id="task-human",
            state=CheckpointState.HUMAN_WAIT,
            attempt=0,
            replan_count=0,
            last_failure_kind=FailureKind.HUMAN_INPUT,
            last_error="User approval required for deployment",
        )
        self.assertEqual(ckpt.state, CheckpointState.HUMAN_WAIT)
        self.assertEqual(ckpt.last_failure_kind, FailureKind.HUMAN_INPUT)
        self.assertIsNone(ckpt.resume_after)

        restored = TaskCheckpoint.from_dict(ckpt.to_dict())
        self.assertEqual(restored, ckpt)

    def test_completed_state(self):
        ckpt = TaskCheckpoint(
            task_id="task-completed",
            state=CheckpointState.COMPLETED,
            attempt=1,
            replan_count=0,
            provider_session_id="session-done",
        )
        self.assertEqual(ckpt.state, CheckpointState.COMPLETED)
        self.assertIsNone(ckpt.last_failure_kind)
        self.assertIsNone(ckpt.last_error)
        self.assertIsNone(ckpt.resume_after)

        restored = TaskCheckpoint.from_dict(ckpt.to_dict())
        self.assertEqual(restored, ckpt)

    def test_invalid_negative_counters(self):
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.RUNNING,
                attempt=-1,
                replan_count=0,
            )
        self.assertIn("attempt must be a non-negative integer", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=-2,
            )
        self.assertIn("replan_count must be a non-negative integer", str(ctx.exception))

    def test_invalid_timestamps(self):
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.PAUSED_QUOTA,
                attempt=0,
                replan_count=0,
                resume_after="not-a-timestamp",
            )
        self.assertIn("invalid ISO-8601 resume_after timestamp", str(ctx.exception))

    def test_forbidden_inconsistent_combinations(self):
        # COMPLETED cannot have failure kind or last error or resume_after
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.COMPLETED,
                attempt=1,
                replan_count=0,
                last_failure_kind=FailureKind.CYCLE_FAILED,
            )
        self.assertIn("COMPLETED state cannot have last_failure_kind", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.COMPLETED,
                attempt=1,
                replan_count=0,
                last_error="some error",
            )
        self.assertIn("COMPLETED state cannot have last_error", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.COMPLETED,
                attempt=1,
                replan_count=0,
                resume_after="2026-03-30T12:00:00Z",
            )
        self.assertIn("COMPLETED state cannot have resume_after timestamp", str(ctx.exception))

        # RUNNING state cannot have resume_after
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=0,
                resume_after="2026-03-30T12:00:00Z",
            )
        self.assertIn("RUNNING state cannot have resume_after timestamp", str(ctx.exception))

        # PAUSED_QUOTA with inconsistent failure kind
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.PAUSED_QUOTA,
                attempt=0,
                replan_count=0,
                last_failure_kind=FailureKind.HUMAN_INPUT,
            )
        self.assertIn("PAUSED_QUOTA state cannot have failure kind", str(ctx.exception))

    def test_reject_secrets_in_last_error(self):
        with self.assertRaises(ValueError) as ctx:
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.FAILED,
                attempt=1,
                replan_count=0,
                last_error="Error with secret token ghp_" + "a" * 36,
            )
        self.assertIn("last_error contains forbidden secret patterns", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
