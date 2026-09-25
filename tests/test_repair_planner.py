from dataclasses import FrozenInstanceError
import unittest

from ade.cycle import CycleFailed, CycleTimedOut, HumanInputRequired
from ade.providers.base import ProviderQuotaError
from ade.repair import FailureKind, RepairDisposition, RepairPolicy
from ade.repair_planner import RepairPlan, plan_repair


class TestRepairPlanner(unittest.TestCase):
    def test_repair_plan_creation_and_immutability(self) -> None:
        plan = RepairPlan(
            task_id="task-123",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: session exceeded 1800s",
        )
        self.assertEqual(plan.task_id, "task-123")
        self.assertEqual(plan.failure_kind, FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(plan.disposition, RepairDisposition.RETRY)
        self.assertEqual(plan.next_attempt, 1)
        self.assertEqual(plan.next_replan_count, 0)
        self.assertEqual(plan.error_summary, "CycleTimedOut: session exceeded 1800s")

        # Check immutability
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            plan.next_attempt = 2  # type: ignore[misc]

    def test_repair_plan_enum_coercion(self) -> None:
        plan = RepairPlan(
            task_id="task-456",
            failure_kind="PROVIDER_QUOTA",  # type: ignore[arg-type]
            disposition="PAUSE_QUOTA",  # type: ignore[arg-type]
            next_attempt=0,
            next_replan_count=0,
            error_summary="ProviderQuotaError: quota exceeded",
        )
        self.assertEqual(plan.failure_kind, FailureKind.PROVIDER_QUOTA)
        self.assertEqual(plan.disposition, RepairDisposition.PAUSE_QUOTA)

    def test_repair_plan_validation(self) -> None:
        # Invalid task_id
        for invalid_id in ["", "   ", 123, None]:
            with self.assertRaises(ValueError):
                RepairPlan(
                    task_id=invalid_id,  # type: ignore[arg-type]
                    failure_kind=FailureKind.UNKNOWN,
                    disposition=RepairDisposition.FAIL,
                    next_attempt=0,
                    next_replan_count=0,
                    error_summary="Error",
                )

        # Invalid next_attempt
        for invalid_attempt in [-1, "0", 1.5, True, False, None]:
            with self.assertRaises(ValueError):
                RepairPlan(
                    task_id="t1",
                    failure_kind=FailureKind.UNKNOWN,
                    disposition=RepairDisposition.FAIL,
                    next_attempt=invalid_attempt,  # type: ignore[arg-type]
                    next_replan_count=0,
                    error_summary="Error",
                )

        # Invalid next_replan_count
        for invalid_replan in [-1, "0", 1.5, True, False, None]:
            with self.assertRaises(ValueError):
                RepairPlan(
                    task_id="t1",
                    failure_kind=FailureKind.UNKNOWN,
                    disposition=RepairDisposition.FAIL,
                    next_attempt=0,
                    next_replan_count=invalid_replan,  # type: ignore[arg-type]
                    error_summary="Error",
                )

        # Invalid error_summary
        for invalid_summary in ["", "   ", 123, None]:
            with self.assertRaises(ValueError):
                RepairPlan(
                    task_id="t1",
                    failure_kind=FailureKind.UNKNOWN,
                    disposition=RepairDisposition.FAIL,
                    next_attempt=0,
                    next_replan_count=0,
                    error_summary=invalid_summary,  # type: ignore[arg-type]
                )

        # Invalid failure_kind or disposition
        with self.assertRaises(ValueError):
            RepairPlan(
                task_id="t1",
                failure_kind="INVALID_KIND",  # type: ignore[arg-type]
                disposition=RepairDisposition.FAIL,
                next_attempt=0,
                next_replan_count=0,
                error_summary="Error",
            )

        with self.assertRaises(ValueError):
            RepairPlan(
                task_id="t1",
                failure_kind=FailureKind.UNKNOWN,
                disposition="INVALID_DISP",  # type: ignore[arg-type]
                next_attempt=0,
                next_replan_count=0,
                error_summary="Error",
            )

    def test_plan_repair_retry(self) -> None:
        exc = CycleTimedOut("session s1 timed out")
        plan = plan_repair("task-1", exc, attempt=0, replan_count=0)

        self.assertEqual(plan.task_id, "task-1")
        self.assertEqual(plan.failure_kind, FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(plan.disposition, RepairDisposition.RETRY)
        self.assertEqual(plan.next_attempt, 1)
        self.assertEqual(plan.next_replan_count, 0)
        self.assertEqual(plan.error_summary, "CycleTimedOut: session s1 timed out")

        # Second retry
        plan2 = plan_repair("task-1", exc, attempt=1, replan_count=0)
        self.assertEqual(plan2.disposition, RepairDisposition.RETRY)
        self.assertEqual(plan2.next_attempt, 2)
        self.assertEqual(plan2.next_replan_count, 0)

    def test_plan_repair_replan(self) -> None:
        # Exceeded retries (attempt=2 >= max_retries=2)
        exc = CycleTimedOut("session s1 timed out")
        plan = plan_repair("task-1", exc, attempt=2, replan_count=0)

        self.assertEqual(plan.failure_kind, FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(plan.disposition, RepairDisposition.REPLAN)
        self.assertEqual(plan.next_attempt, 2)  # attempt unchanged
        self.assertEqual(plan.next_replan_count, 1)  # replan_count incremented

        # Validation error triggers REPLAN directly
        vexc = ValueError("invalid configuration")
        vplan = plan_repair("task-1", vexc, attempt=0, replan_count=0)
        self.assertEqual(vplan.failure_kind, FailureKind.VALIDATION_ERROR)
        self.assertEqual(vplan.disposition, RepairDisposition.REPLAN)
        self.assertEqual(vplan.next_attempt, 0)  # attempt unchanged
        self.assertEqual(vplan.next_replan_count, 1)  # replan_count incremented

    def test_plan_repair_quota_pause(self) -> None:
        exc = ProviderQuotaError("429 Too Many Requests")
        plan = plan_repair("task-1", exc, attempt=1, replan_count=0)

        self.assertEqual(plan.failure_kind, FailureKind.PROVIDER_QUOTA)
        self.assertEqual(plan.disposition, RepairDisposition.PAUSE_QUOTA)
        self.assertEqual(plan.next_attempt, 1)  # unchanged
        self.assertEqual(plan.next_replan_count, 0)  # unchanged
        self.assertEqual(plan.error_summary, "ProviderQuotaError: 429 Too Many Requests")

    def test_plan_repair_human_wait(self) -> None:
        exc = HumanInputRequired("Awaiting confirmation")
        plan = plan_repair("task-1", exc, attempt=0, replan_count=0)

        self.assertEqual(plan.failure_kind, FailureKind.HUMAN_INPUT)
        self.assertEqual(plan.disposition, RepairDisposition.HUMAN_WAIT)
        self.assertEqual(plan.next_attempt, 0)  # unchanged
        self.assertEqual(plan.next_replan_count, 0)  # unchanged

    def test_plan_repair_terminal_fail(self) -> None:
        # Exceeded retries (2) and replans (1)
        exc = CycleFailed("session failed")
        plan = plan_repair("task-1", exc, attempt=2, replan_count=1)

        self.assertEqual(plan.failure_kind, FailureKind.CYCLE_FAILED)
        self.assertEqual(plan.disposition, RepairDisposition.FAIL)
        self.assertEqual(plan.next_attempt, 2)  # unchanged
        self.assertEqual(plan.next_replan_count, 1)  # unchanged

        # Unknown exception always fails terminal
        uexc = RuntimeError("unexpected crash")
        uplan = plan_repair("task-1", uexc, attempt=0, replan_count=0)
        self.assertEqual(uplan.failure_kind, FailureKind.UNKNOWN)
        self.assertEqual(uplan.disposition, RepairDisposition.FAIL)
        self.assertEqual(uplan.next_attempt, 0)  # unchanged
        self.assertEqual(uplan.next_replan_count, 0)  # unchanged

    def test_plan_repair_custom_policy(self) -> None:
        policy = RepairPolicy(max_retries=0, max_replans=0)
        exc = CycleTimedOut("timed out")
        plan = plan_repair("task-1", exc, attempt=0, replan_count=0, policy=policy)

        self.assertEqual(plan.disposition, RepairDisposition.FAIL)
        self.assertEqual(plan.next_attempt, 0)
        self.assertEqual(plan.next_replan_count, 0)

    def test_plan_repair_error_summary_formatting(self) -> None:
        # Exception with empty message
        empty_exc = ValueError()
        plan_empty = plan_repair("task-1", empty_exc, 0, 0)
        self.assertEqual(plan_empty.error_summary, "ValueError")

        # Exception with type name already in message
        prefixed_exc = RuntimeError("RuntimeError: something went wrong")
        plan_prefixed = plan_repair("task-1", prefixed_exc, 0, 0)
        self.assertEqual(plan_prefixed.error_summary, "RuntimeError: something went wrong")

        # Exception with traceback/multi-line message
        tb_msg = "Error occurred\n  File 'app.py', line 42\n    raise Error()\nTraceback..."
        tb_exc = RuntimeError(tb_msg)
        plan_tb = plan_repair("task-1", tb_exc, 0, 0)
        self.assertEqual(plan_tb.error_summary, "RuntimeError: Error occurred")

        # Bounded error summary length
        long_msg = "x" * 500
        long_exc = Exception(long_msg)
        plan_long = plan_repair("task-1", long_exc, 0, 0)
        self.assertLessEqual(len(plan_long.error_summary), 256)
        self.assertTrue(plan_long.error_summary.startswith("Exception: xxxxx"))

    def test_plan_repair_invalid_inputs(self) -> None:
        exc = CycleFailed("failed")

        # Invalid task_id
        for invalid_id in ["", "   ", 123, None]:
            with self.assertRaises(ValueError):
                plan_repair(invalid_id, exc, 0, 0)  # type: ignore[arg-type]

        # Invalid exc
        for invalid_exc in ["not an exc", 123, None, ValueError]:
            with self.assertRaises(ValueError):
                plan_repair("t1", invalid_exc, 0, 0)  # type: ignore[arg-type]

        # Invalid attempt
        for invalid_attempt in [-1, "0", 1.5, True, False, None]:
            with self.assertRaises(ValueError):
                plan_repair("t1", exc, invalid_attempt, 0)  # type: ignore[arg-type]

        # Invalid replan_count
        for invalid_replan in [-1, "0", 1.5, True, False, None]:
            with self.assertRaises(ValueError):
                plan_repair("t1", exc, 0, invalid_replan)  # type: ignore[arg-type]

        # Invalid policy
        with self.assertRaises(ValueError):
            plan_repair("t1", exc, 0, 0, policy="invalid")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
