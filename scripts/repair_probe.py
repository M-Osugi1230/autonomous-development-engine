from __future__ import annotations

import json
import sys
from typing import Any

from ade.cycle import CycleResult, CycleTask, CycleTimedOut
from ade.repair import RepairDisposition, RepairPolicy
from ade.repair_runtime import run_cycle_with_repair


class ProbeInvariantError(RuntimeError):
    """Raised when a repair probe invariant validation fails."""


class DummyProvider:
    """Dummy provider for deterministic probe execution."""


def validate_probe_execution(
    execution: Any,
    cycle_calls: int,
) -> None:
    """Validate that the repair execution satisfies all Phase 5 probe invariants."""
    if cycle_calls != 2:
        raise ProbeInvariantError(f"Expected exactly 2 cycle calls, got {cycle_calls}")

    if execution.result is None:
        raise ProbeInvariantError("Expected non-None result in repair execution")

    if execution.result.state != "COMPLETED":
        raise ProbeInvariantError(
            f"Expected state COMPLETED, got {execution.result.state}"
        )

    if len(execution.history) != 1:
        raise ProbeInvariantError(
            f"Expected exactly 1 recorded history plan, got {len(execution.history)}"
        )

    recorded_plan = execution.history[0]
    if recorded_plan.disposition is not RepairDisposition.RETRY:
        raise ProbeInvariantError(
            f"Expected RETRY disposition in history, got {recorded_plan.disposition}"
        )

    # Validate no traceback or secret leakage in history or result fields
    forbidden_tokens = (
        "traceback",
        "file \"",
        "api_key",
        "secret",
        "token",
        "bearer",
        "password",
    )

    check_strings = [
        recorded_plan.error_summary.lower(),
        str(execution.result.session_id).lower(),
        str(execution.result.state).lower(),
    ]
    if execution.result.pull_request_url:
        check_strings.append(execution.result.pull_request_url.lower())

    for s in check_strings:
        for token in forbidden_tokens:
            if token in s:
                raise ProbeInvariantError(
                    f"Forbidden secret/traceback token '{token}' detected in probe output data"
                )


def run_repair_probe() -> dict[str, Any]:
    """Execute the deterministic bounded repair probe and return compact result payload."""
    provider = DummyProvider()
    task = CycleTask(
        task_id="probe-task-1",
        title="Phase 5 Bounded Repair Probe Task",
        prompt="Execute repair probe cycle",
    )
    policy = RepairPolicy(max_retries=1, max_replans=0)

    calls = 0

    def probe_run_cycle_fn(
        p: Any,
        *,
        task: CycleTask,
        source_name: str,
    ) -> CycleResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CycleTimedOut("probe cycle timeout simulation")
        if calls == 2:
            return CycleResult(
                task_id=task.task_id,
                session_id="probe-session-101",
                session_url="https://example.com/probe-session-101",
                state="COMPLETED",
                pull_request_url="https://github.com/example/repo/pull/101",
            )
        raise RuntimeError(f"Unexpected cycle call count: {calls}")

    execution = run_cycle_with_repair(
        provider,
        task=task,
        source_name="probe-source",
        policy=policy,
        run_cycle_fn=probe_run_cycle_fn,
    )

    validate_probe_execution(execution, calls)

    assert execution.result is not None
    return {
        "status": "ok",
        "task_id": execution.result.task_id,
        "session_id": execution.result.session_id,
        "state": execution.result.state,
        "cycle_calls": calls,
        "retry_plans": len(execution.history),
        "pull_request_url": execution.result.pull_request_url,
    }


def main() -> int:
    try:
        payload = run_repair_probe()
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"Repair probe invariant failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
