from __future__ import annotations

import unittest
from typing import Any

from ade.cycle import (
    CycleFailed,
    CycleResult,
    CycleTask,
    CycleTimedOut,
    HumanInputRequired,
)
from ade.providers.base import ProviderQuotaError
from ade.repair import FailureKind, RepairDisposition, RepairPolicy
from ade.repair_planner import RepairPlan
from ade.repair_runtime import RepairExecution, run_cycle_with_repair


class DummyProvider:
    pass


def _make_task(task_id: str = "task-101") -> CycleTask:
    return CycleTask(
        task_id=task_id,
        title="Test Task",
        prompt="Fix the bug",
    )


def _make_cycle_result(task_id: str = "task-101") -> CycleResult:
    return CycleResult(
        task_id=task_id,
        session_id="session-1",
        session_url="https://example.com/session-1",
        state="COMPLETED",
        pull_request_url="https://github.com/example/repo/pull/1",
    )


class TestRepairRuntime(unittest.TestCase):
    def test_repair_execution_validation_and_immutability(self) -> None:
        result = _make_cycle_result()
        plan = RepairPlan(
            task_id="task-101",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: timed out",
        )

        # Immediate valid creation with result
        execution_res = RepairExecution(result=result, history=())
        self.assertEqual(execution_res.result, result)
        self.assertIsNone(execution_res.final_plan)
        self.assertEqual(execution_res.history, ())

        # Immediate valid creation with final_plan
        execution_plan = RepairExecution(final_plan=plan, history=[plan])
        self.assertIsNone(execution_plan.result)
        self.assertEqual(execution_plan.final_plan, plan)
        self.assertEqual(execution_plan.history, (plan,))

        # Immutability check
        with self.assertRaises(AttributeError):
            execution_res.result = None  # type: ignore[misc]

        # Rejection when neither or both are provided
        with self.assertRaises(ValueError):
            RepairExecution()
        with self.assertRaises(ValueError):
            RepairExecution(result=result, final_plan=plan)

        # Rejection of invalid field types
        with self.assertRaises(ValueError):
            RepairExecution(result="not-a-result")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RepairExecution(final_plan="not-a-plan")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RepairExecution(result=result, history="not-a-sequence")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RepairExecution(result=result, history=["not-a-plan"])  # type: ignore[arg-type]

    def test_immediate_success(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        expected_result = _make_cycle_result()

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            self.assertIs(p, provider)
            self.assertEqual(task.task_id, "task-101")
            self.assertEqual(source_name, "test-source")
            return expected_result

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            run_cycle_fn=mock_run_cycle,
        )

        self.assertEqual(execution.result, expected_result)
        self.assertIsNone(execution.final_plan)
        self.assertEqual(execution.history, ())

    def test_timeout_then_success_after_one_retry(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        expected_result = _make_cycle_result()
        calls = 0

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CycleTimedOut("session timeout")
            return expected_result

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            run_cycle_fn=mock_run_cycle,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(execution.result, expected_result)
        self.assertIsNone(execution.final_plan)
        self.assertEqual(len(execution.history), 1)

        plan = execution.history[0]
        self.assertEqual(plan.task_id, "task-101")
        self.assertEqual(plan.failure_kind, FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(plan.disposition, RepairDisposition.RETRY)
        self.assertEqual(plan.next_attempt, 1)
        self.assertEqual(plan.next_replan_count, 0)

    def test_repeated_timeout_reaches_replan_after_bounded_retries(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        policy = RepairPolicy(max_retries=2, max_replans=1)
        calls = 0

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            nonlocal calls
            calls += 1
            raise CycleTimedOut(f"timeout call {calls}")

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            policy=policy,
            run_cycle_fn=mock_run_cycle,
        )

        # Attempt 0: fails -> plan 1 (RETRY, next_attempt=1)
        # Attempt 1: fails -> plan 2 (RETRY, next_attempt=2)
        # Attempt 2: fails -> plan 3 (REPLAN, next_replan_count=1) -> stops!
        self.assertEqual(calls, 3)
        self.assertIsNone(execution.result)
        self.assertIsNotNone(execution.final_plan)

        assert execution.final_plan is not None
        self.assertEqual(execution.final_plan.disposition, RepairDisposition.REPLAN)
        self.assertEqual(execution.final_plan.next_attempt, 2)
        self.assertEqual(execution.final_plan.next_replan_count, 1)

        self.assertEqual(len(execution.history), 3)
        self.assertEqual(execution.history[0].disposition, RepairDisposition.RETRY)
        self.assertEqual(execution.history[1].disposition, RepairDisposition.RETRY)
        self.assertEqual(execution.history[2].disposition, RepairDisposition.REPLAN)
        self.assertEqual(execution.history[2], execution.final_plan)

    def test_quota_returns_pause_quota_without_retry(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        calls = 0

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            nonlocal calls
            calls += 1
            raise ProviderQuotaError("quota exceeded")

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            run_cycle_fn=mock_run_cycle,
        )

        self.assertEqual(calls, 1)
        self.assertIsNone(execution.result)
        self.assertIsNotNone(execution.final_plan)

        assert execution.final_plan is not None
        self.assertEqual(execution.final_plan.failure_kind, FailureKind.PROVIDER_QUOTA)
        self.assertEqual(execution.final_plan.disposition, RepairDisposition.PAUSE_QUOTA)
        self.assertEqual(len(execution.history), 1)
        self.assertEqual(execution.history[0], execution.final_plan)

    def test_human_input_returns_human_wait_without_retry(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        calls = 0

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            nonlocal calls
            calls += 1
            raise HumanInputRequired("input needed")

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            run_cycle_fn=mock_run_cycle,
        )

        self.assertEqual(calls, 1)
        self.assertIsNone(execution.result)
        self.assertIsNotNone(execution.final_plan)

        assert execution.final_plan is not None
        self.assertEqual(execution.final_plan.failure_kind, FailureKind.HUMAN_INPUT)
        self.assertEqual(execution.final_plan.disposition, RepairDisposition.HUMAN_WAIT)
        self.assertEqual(len(execution.history), 1)

    def test_terminal_unknown_error_returns_fail(self) -> None:
        provider = DummyProvider()
        task = _make_task()
        calls = 0

        def mock_run_cycle(p: Any, *, task: CycleTask, source_name: str) -> CycleResult:
            nonlocal calls
            calls += 1
            raise KeyError("unexpected error")

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name="test-source",
            run_cycle_fn=mock_run_cycle,
        )

        self.assertEqual(calls, 1)
        self.assertIsNone(execution.result)
        self.assertIsNotNone(execution.final_plan)

        assert execution.final_plan is not None
        self.assertEqual(execution.final_plan.failure_kind, FailureKind.UNKNOWN)
        self.assertEqual(execution.final_plan.disposition, RepairDisposition.FAIL)
        self.assertEqual(len(execution.history), 1)

    def test_invalid_arguments_are_rejected(self) -> None:
        provider = DummyProvider()
        task = _make_task()

        # provider is None
        with self.assertRaises(ValueError):
            run_cycle_with_repair(None, task=task, source_name="src")

        # invalid task
        with self.assertRaises(ValueError):
            run_cycle_with_repair(provider, task="not-a-task", source_name="src")  # type: ignore[arg-type]

        # invalid source_name
        with self.assertRaises(ValueError):
            run_cycle_with_repair(provider, task=task, source_name="")
        with self.assertRaises(ValueError):
            run_cycle_with_repair(provider, task=task, source_name="   ")

        # invalid policy
        with self.assertRaises(ValueError):
            run_cycle_with_repair(provider, task=task, source_name="src", policy="invalid")  # type: ignore[arg-type]

        # invalid run_cycle_fn
        with self.assertRaises(ValueError):
            run_cycle_with_repair(provider, task=task, source_name="src", run_cycle_fn="not-callable")  # type: ignore[arg-type]
