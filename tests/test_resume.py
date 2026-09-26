from datetime import datetime, timezone, timedelta
import unittest

from ade import (
    CheckpointState,
    FailureKind,
    ResumeAction,
    ResumeDecision,
    TaskCheckpoint,
    decide_resume,
)


class TestResumePolicy(unittest.TestCase):
    def test_quota_before_due(self):
        ckpt = TaskCheckpoint(
            task_id="task-q1",
            state=CheckpointState.PAUSED_QUOTA,
            attempt=1,
            replan_count=0,
            last_failure_kind=FailureKind.PROVIDER_QUOTA,
            resume_after="2026-03-30T12:00:00Z",
        )
        now = datetime(2026, 3, 30, 11, 59, 59, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.WAIT)
        self.assertIn("has not been reached yet", decision.reason)

    def test_quota_due(self):
        ckpt = TaskCheckpoint(
            task_id="task-q2",
            state=CheckpointState.PAUSED_QUOTA,
            attempt=1,
            replan_count=0,
            last_failure_kind=FailureKind.PROVIDER_QUOTA,
            resume_after="2026-03-30T12:00:00Z",
        )
        # Exactly due
        now_exact = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision_exact = decide_resume(ckpt, now_exact)
        self.assertEqual(decision_exact.action, ResumeAction.RESUME)
        self.assertIn("reached", decision_exact.reason)

        # Past due
        now_after = datetime(2026, 3, 30, 12, 0, 1, tzinfo=timezone.utc)
        decision_after = decide_resume(ckpt, now_after)
        self.assertEqual(decision_after.action, ResumeAction.RESUME)

    def test_quota_without_deadline(self):
        ckpt = TaskCheckpoint(
            task_id="task-q3",
            state=CheckpointState.PAUSED_QUOTA,
            attempt=1,
            replan_count=0,
            last_failure_kind=FailureKind.PROVIDER_QUOTA,
            resume_after=None,
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.WAIT)
        self.assertIn("no resume_after deadline set", decision.reason)

    def test_human_wait(self):
        ckpt = TaskCheckpoint(
            task_id="task-h1",
            state=CheckpointState.HUMAN_WAIT,
            attempt=0,
            replan_count=0,
            last_failure_kind=FailureKind.HUMAN_INPUT,
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.WAIT)
        self.assertIn("HUMAN_WAIT checkpoint requires manual intervention", decision.reason)

    def test_recoverable_running(self):
        # RUNNING with provider_session_id -> RESUME
        ckpt_with_session = TaskCheckpoint(
            task_id="task-r1",
            state=CheckpointState.RUNNING,
            attempt=1,
            replan_count=0,
            provider_session_id="session-123",
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision1 = decide_resume(ckpt_with_session, now)
        self.assertEqual(decision1.action, ResumeAction.RESUME)
        self.assertIn("provider session can be resumed", decision1.reason)

        # RUNNING without provider_session_id -> WAIT
        ckpt_without_session = TaskCheckpoint(
            task_id="task-r2",
            state=CheckpointState.RUNNING,
            attempt=1,
            replan_count=0,
            provider_session_id=None,
        )
        decision2 = decide_resume(ckpt_without_session, now)
        self.assertEqual(decision2.action, ResumeAction.WAIT)
        self.assertIn("without provider session cannot be auto-resumed", decision2.reason)

    def test_replan(self):
        ckpt = TaskCheckpoint(
            task_id="task-rp1",
            state=CheckpointState.REPLAN,
            attempt=2,
            replan_count=1,
            last_failure_kind=FailureKind.CYCLE_FAILED,
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.REPLAN)
        self.assertIn("requires replanning", decision.reason)

    def test_failed(self):
        ckpt = TaskCheckpoint(
            task_id="task-f1",
            state=CheckpointState.FAILED,
            attempt=3,
            replan_count=1,
            last_failure_kind=FailureKind.UNKNOWN,
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.NOOP)
        self.assertIn("Terminal state FAILED", decision.reason)

    def test_completed(self):
        ckpt = TaskCheckpoint(
            task_id="task-c1",
            state=CheckpointState.COMPLETED,
            attempt=1,
            replan_count=0,
        )
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        decision = decide_resume(ckpt, now)
        self.assertEqual(decision.action, ResumeAction.NOOP)
        self.assertIn("Terminal state COMPLETED", decision.reason)

    def test_invalid_naive_time(self):
        ckpt = TaskCheckpoint(
            task_id="task-q1",
            state=CheckpointState.PAUSED_QUOTA,
            attempt=1,
            replan_count=0,
            resume_after="2026-03-30T12:00:00Z",
        )
        # Naive datetime
        now_naive = datetime(2026, 3, 30, 12, 0, 0)
        with self.assertRaises(ValueError) as ctx:
            decide_resume(ckpt, now_naive)
        self.assertIn("now must be a timezone-aware datetime", str(ctx.exception))

    def test_invalid_inputs(self):
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)

        with self.assertRaises(ValueError) as ctx:
            decide_resume("not-a-checkpoint", now)  # type: ignore[arg-type]
        self.assertIn("checkpoint must be an instance of TaskCheckpoint", str(ctx.exception))

        ckpt = TaskCheckpoint(
            task_id="task-c1",
            state=CheckpointState.COMPLETED,
            attempt=1,
            replan_count=0,
        )
        with self.assertRaises(ValueError) as ctx:
            decide_resume(ckpt, "not-a-datetime")  # type: ignore[arg-type]
        self.assertIn("now must be a datetime instance", str(ctx.exception))

    def test_resume_decision_validation_and_immutability(self):
        decision = ResumeDecision(action=ResumeAction.RESUME, reason="Testing")
        self.assertEqual(decision.action, ResumeAction.RESUME)
        self.assertEqual(decision.reason, "Testing")

        # Immutability
        with self.assertRaises(AttributeError):
            decision.action = ResumeAction.WAIT  # type: ignore[misc]

        # String coercion for action
        decision_str = ResumeDecision(action="WAIT", reason="Testing string enum")  # type: ignore[arg-type]
        self.assertEqual(decision_str.action, ResumeAction.WAIT)

        # Invalid action
        with self.assertRaises(ValueError):
            ResumeDecision(action="INVALID", reason="Testing invalid")  # type: ignore[arg-type]

        # Invalid reason
        with self.assertRaises(ValueError):
            ResumeDecision(action=ResumeAction.RESUME, reason="   ")


if __name__ == "__main__":
    unittest.main()
