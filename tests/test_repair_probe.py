from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ade.cycle import CycleResult
from ade.repair import FailureKind, RepairDisposition
from ade.repair_planner import RepairPlan
from ade.repair_runtime import RepairExecution

# Dynamically import scripts/repair_probe.py
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "repair_probe.py"
SPEC = importlib.util.spec_from_file_location("repair_probe_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
REPAIR_PROBE_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REPAIR_PROBE_MODULE
SPEC.loader.exec_module(REPAIR_PROBE_MODULE)


class RepairProbeTests(unittest.TestCase):
    def test_run_repair_probe_happy_path(self) -> None:
        result = REPAIR_PROBE_MODULE.run_repair_probe()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cycle_calls"], 2)
        self.assertEqual(result["retry_plans"], 1)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["task_id"], "probe-task-1")
        self.assertEqual(result["session_id"], "probe-session-101")
        self.assertEqual(
            result["pull_request_url"], "https://github.com/example/repo/pull/101"
        )

    def test_validate_probe_execution_cycle_calls_invariant(self) -> None:
        result = CycleResult(
            task_id="t1",
            session_id="s1",
            session_url=None,
            state="COMPLETED",
            pull_request_url=None,
        )
        plan = RepairPlan(
            task_id="t1",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: timeout",
        )
        execution = RepairExecution(result=result, history=(plan,))

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=1)
        self.assertIn("Expected exactly 2 cycle calls", str(ctx.exception))

    def test_validate_probe_execution_none_result(self) -> None:
        plan = RepairPlan(
            task_id="t1",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: timeout",
        )
        execution = RepairExecution(final_plan=plan, history=(plan,))

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=2)
        self.assertIn("Expected non-None result", str(ctx.exception))

    def test_validate_probe_execution_non_completed_state(self) -> None:
        result = CycleResult(
            task_id="t1",
            session_id="s1",
            session_url=None,
            state="FAILED",
            pull_request_url=None,
        )
        plan = RepairPlan(
            task_id="t1",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="CycleTimedOut: timeout",
        )
        execution = RepairExecution(result=result, history=(plan,))

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=2)
        self.assertIn("Expected state COMPLETED", str(ctx.exception))

    def test_validate_probe_execution_history_count_invariant(self) -> None:
        result = CycleResult(
            task_id="t1",
            session_id="s1",
            session_url=None,
            state="COMPLETED",
            pull_request_url=None,
        )
        execution = RepairExecution(result=result, history=())

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=2)
        self.assertIn("Expected exactly 1 recorded history plan", str(ctx.exception))

    def test_validate_probe_execution_history_disposition_invariant(self) -> None:
        result = CycleResult(
            task_id="t1",
            session_id="s1",
            session_url=None,
            state="COMPLETED",
            pull_request_url=None,
        )
        plan = RepairPlan(
            task_id="t1",
            failure_kind=FailureKind.UNKNOWN,
            disposition=RepairDisposition.FAIL,
            next_attempt=0,
            next_replan_count=0,
            error_summary="Unknown error",
        )
        execution = RepairExecution(result=result, history=(plan,))

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=2)
        self.assertIn("Expected RETRY disposition", str(ctx.exception))

    def test_validate_probe_execution_forbidden_data_leak(self) -> None:
        result = CycleResult(
            task_id="t1",
            session_id="s1",
            session_url=None,
            state="COMPLETED",
            pull_request_url=None,
        )
        plan = RepairPlan(
            task_id="t1",
            failure_kind=FailureKind.CYCLE_TIMEOUT,
            disposition=RepairDisposition.RETRY,
            next_attempt=1,
            next_replan_count=0,
            error_summary="Traceback (most recent call last): File 'main.py'",
        )
        execution = RepairExecution(result=result, history=(plan,))

        with self.assertRaises(REPAIR_PROBE_MODULE.ProbeInvariantError) as ctx:
            REPAIR_PROBE_MODULE.validate_probe_execution(execution, cycle_calls=2)
        self.assertIn("Forbidden secret/traceback token", str(ctx.exception))

    def test_main_success_exit(self) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = REPAIR_PROBE_MODULE.main()

        self.assertEqual(exit_code, 0)
        output = stdout_buf.getvalue().strip()
        parsed = json.loads(output)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["state"], "COMPLETED")
        self.assertEqual(parsed["cycle_calls"], 2)

    def test_main_failure_exit(self) -> None:
        stderr_buf = io.StringIO()
        with patch(
            "repair_probe_script.run_repair_probe",
            side_effect=REPAIR_PROBE_MODULE.ProbeInvariantError("mocked invariant failure"),
        ), patch("sys.stderr", stderr_buf):
            exit_code = REPAIR_PROBE_MODULE.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("Repair probe invariant failure: mocked invariant failure", stderr_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
