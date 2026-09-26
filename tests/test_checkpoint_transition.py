import unittest

from ade import (
    CheckpointState,
    CycleResult,
    CycleSession,
    FailureKind,
    RepairDisposition,
    RepairPlan,
    TaskCheckpoint,
    checkpoint_for_completed,
    checkpoint_for_repair_plan,
    checkpoint_for_session,
    checkpoint_from_completed,
    checkpoint_from_repair_plan,
    checkpoint_from_session,
)


class CheckpointTransitionTests(unittest.TestCase):
    def test_checkpoint_for_running_session(self):
        session = CycleSession(
            task_id="task-100",
            session_id="sess-001",
            session_url="https://example.com/session/sess-001",
        )
        ckpt = checkpoint_for_session(session, attempt=1, replan_count=2)
        self.assertIsInstance(ckpt, TaskCheckpoint)
        self.assertEqual(ckpt.task_id, "task-100")
        self.assertEqual(ckpt.state, CheckpointState.RUNNING)
        self.assertEqual(ckpt.attempt, 1)
        self.assertEqual(ckpt.replan_count, 2)
        self.assertEqual(ckpt.provider_session_id, "sess-001")
        self.assertIsNone(ckpt.last_failure_kind)
        self.assertIsNone(ckpt.last_error)
        self.assertIsNone(ckpt.resume_after)

        # Check alias
        ckpt_alias = checkpoint_from_session(session, attempt=1, replan_count=2)
        self.assertEqual(ckpt_alias, ckpt)

    def test_checkpoint_for_completed_result(self):
        result = CycleResult(
            task_id="task-200",
            session_id="sess-002",
            session_url="https://example.com/session/sess-002",
            state="COMPLETED",
            pull_request_url="https://github.com/org/repo/pull/1",
        )
        ckpt = checkpoint_for_completed(result, attempt=3, replan_count=0)
        self.assertIsInstance(ckpt, TaskCheckpoint)
        self.assertEqual(ckpt.task_id, "task-200")
        self.assertEqual(ckpt.state, CheckpointState.COMPLETED)
        self.assertEqual(ckpt.attempt, 3)
        self.assertEqual(ckpt.replan_count, 0)
        self.assertEqual(ckpt.provider_session_id, "sess-002")
        self.assertIsNone(ckpt.last_failure_kind)
        self.assertIsNone(ckpt.last_error)
        self.assertIsNone(ckpt.resume_after)

        # Check alias
        ckpt_alias = checkpoint_from_completed(result, attempt=3, replan_count=0)
        self.assertEqual(ckpt_alias, ckpt)

    def test_checkpoint_for_repair_plan_pause_quota_with_and_without_session_id(self):
        plan = RepairPlan(
            task_id="task-quota",
            failure_kind=FailureKind.PROVIDER_QUOTA,
            disposition=RepairDisposition.PAUSE_QUOTA,
            next_attempt=2,
            next_replan_count=1,
            error_summary="ProviderQuotaError: Rate limit exceeded",
        )

        # Without provider session id
        ckpt_no_sess = checkpoint_for_repair_plan(
            plan,
            resume_after="2026-03-30T14:00:00Z",
        )
        self.assertEqual(ckpt_no_sess.task_id, "task-quota")
        self.assertEqual(ckpt_no_sess.state, CheckpointState.PAUSED_QUOTA)
        self.assertEqual(ckpt_no_sess.attempt, 2)
        self.assertEqual(ckpt_no_sess.replan_count, 1)
        self.assertIsNone(ckpt_no_sess.provider_session_id)
        self.assertEqual(ckpt_no_sess.last_failure_kind, FailureKind.PROVIDER_QUOTA)
        self.assertEqual(ckpt_no_sess.last_error, "ProviderQuotaError: Rate limit exceeded")
        self.assertEqual(ckpt_no_sess.resume_after, "2026-03-30T14:00:00Z")

        # With provider session id
        ckpt_with_sess = checkpoint_for_repair_plan(
            plan,
            provider_session_id="sess-quota-123",
            resume_after="2026-03-30T14:00:00Z",
        )
        self.assertEqual(ckpt_with_sess.provider_session_id, "sess-quota-123")
        self.assertEqual(ckpt_with_sess.state, CheckpointState.PAUSED_QUOTA)

    def test_checkpoint_for_repair_plan_human_wait(self):
        plan = RepairPlan(
            task_id="task-human",
            failure_kind=FailureKind.HUMAN_INPUT,
            disposition=RepairDisposition.HUMAN_WAIT,
            next_attempt=1,
            next_replan_count=0,
            error_summary="HumanInputRequired: User input requested",
        )
        ckpt = checkpoint_for_repair_plan(plan, provider_session_id="sess-human-1")
        self.assertEqual(ckpt.task_id, "task-human")
        self.assertEqual(ckpt.state, CheckpointState.HUMAN_WAIT)
        self.assertEqual(ckpt.attempt, 1)
        self.assertEqual(ckpt.replan_count, 0)
        self.assertEqual(ckpt.provider_session_id, "sess-human-1")
        self.assertEqual(ckpt.last_failure_kind, FailureKind.HUMAN_INPUT)
        self.assertEqual(ckpt.last_error, "HumanInputRequired: User input requested")
        self.assertIsNone(ckpt.resume_after)

    def test_checkpoint_for_repair_plan_replan(self):
        plan = RepairPlan(
            task_id="task-replan",
            failure_kind=FailureKind.CYCLE_FAILED,
            disposition=RepairDisposition.REPLAN,
            next_attempt=2,
            next_replan_count=1,
            error_summary="CycleFailed: Task failed after max retries",
        )
        ckpt = checkpoint_for_repair_plan(plan)
        self.assertEqual(ckpt.task_id, "task-replan")
        self.assertEqual(ckpt.state, CheckpointState.REPLAN)
        self.assertEqual(ckpt.attempt, 2)
        self.assertEqual(ckpt.replan_count, 1)
        self.assertEqual(ckpt.last_failure_kind, FailureKind.CYCLE_FAILED)
        self.assertEqual(ckpt.last_error, "CycleFailed: Task failed after max retries")

    def test_checkpoint_for_repair_plan_fail(self):
        plan = RepairPlan(
            task_id="task-fail",
            failure_kind=FailureKind.UNKNOWN,
            disposition=RepairDisposition.FAIL,
            next_attempt=2,
            next_replan_count=1,
            error_summary="RuntimeError: Fatal error",
        )
        ckpt = checkpoint_for_repair_plan(plan)
        self.assertEqual(ckpt.task_id, "task-fail")
        self.assertEqual(ckpt.state, CheckpointState.FAILED)
        self.assertEqual(ckpt.attempt, 2)
        self.assertEqual(ckpt.replan_count, 1)
        self.assertEqual(ckpt.last_failure_kind, FailureKind.UNKNOWN)
        self.assertEqual(ckpt.last_error, "RuntimeError: Fatal error")

    def test_retry_disposition_is_rejected(self):
        plan = RepairPlan(
            task_id="task-retry",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: Timeout after 300s",
        )
        with self.assertRaises(ValueError) as ctx:
            checkpoint_for_repair_plan(plan)
        self.assertIn("RETRY disposition is non-terminal", str(ctx.exception))

    def test_task_id_mismatch_rejection(self):
        session = CycleSession(task_id="task-A", session_id="sess-A")
        with self.assertRaises(ValueError) as ctx:
            checkpoint_for_session(session, task_id="task-B")
        self.assertIn("task_id mismatch", str(ctx.exception))

        result = CycleResult(
            task_id="task-A",
            session_id="sess-A",
            session_url=None,
            state="COMPLETED",
            pull_request_url=None,
        )
        with self.assertRaises(ValueError) as ctx:
            checkpoint_for_completed(result, task_id="task-B")
        self.assertIn("task_id mismatch", str(ctx.exception))

        plan = RepairPlan(
            task_id="task-A",
            failure_kind=FailureKind.HUMAN_INPUT,
            disposition=RepairDisposition.HUMAN_WAIT,
            next_attempt=0,
            next_replan_count=0,
            error_summary="Needs approval",
        )
        with self.assertRaises(ValueError) as ctx:
            checkpoint_for_repair_plan(plan, task_id="task-B")
        self.assertIn("task_id mismatch", str(ctx.exception))

    def test_input_immutability(self):
        session = CycleSession(task_id="task-immut", session_id="sess-immut")
        session_dict_before = session.to_dict()
        checkpoint_for_session(session)
        self.assertEqual(session.to_dict(), session_dict_before)

        plan = RepairPlan(
            task_id="task-plan-immut",
            failure_kind=FailureKind.HUMAN_INPUT,
            disposition=RepairDisposition.HUMAN_WAIT,
            next_attempt=0,
            next_replan_count=0,
            error_summary="Needs approval",
        )
        kind_before = plan.failure_kind
        disp_before = plan.disposition
        checkpoint_for_repair_plan(plan)
        self.assertEqual(plan.failure_kind, kind_before)
        self.assertEqual(plan.disposition, disp_before)


if __name__ == "__main__":
    unittest.main()
