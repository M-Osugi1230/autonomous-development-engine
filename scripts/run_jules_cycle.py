from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ade.cycle import CycleTask
from ade.providers.jules import JulesProvider
from ade.repair_planner import plan_repair
from ade.repair_runtime import RepairExecution, map_repair_execution, run_cycle_with_repair

TASK_PATH = Path(".autodev/cycle-task.json")
RESULT_PATH = Path(".autodev/runtime/jules-session.json")


def write_result(payload: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")
    task_id = "unknown"

    try:
        raw_task = json.loads(TASK_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw_task, dict):
            raise ValueError("cycle task must be a JSON object")
        if "task_id" in raw_task and isinstance(raw_task["task_id"], str):
            task_id = raw_task["task_id"]

        task = CycleTask.from_dict(raw_task)
        task_id = task.task_id

        provider = JulesProvider()
        source = provider.find_github_source(owner, repo)
        if source is None:
            raise RuntimeError(f"{owner}/{repo} is not visible in Jules sources")

        source_name = source.get("name")
        if not isinstance(source_name, str) or not source_name:
            raise RuntimeError("Jules source does not contain a valid resource name")

        execution = run_cycle_with_repair(
            provider,
            task=task,
            source_name=source_name,
        )
    except Exception as exc:
        plan = plan_repair(
            task_id=task_id,
            exc=exc,
            attempt=0,
            replan_count=0,
        )
        execution = RepairExecution(
            result=None,
            final_plan=plan,
            history=(plan,),
        )

    payload, exit_code = map_repair_execution(execution)
    write_result(payload)

    if execution.result is not None:
        print(f"PASS: Jules session completed: {execution.result.session_id}")
        if execution.result.pull_request_url:
            print(f"Pull request: {execution.result.pull_request_url}")
        else:
            print("WARNING: session completed without a pull request URL")
    else:
        plan = execution.final_plan
        assert plan is not None
        if exit_code == 20:
            print(f"Jules quota exhausted: {plan.error_summary}", file=sys.stderr)
        elif exit_code == 21:
            print(f"{plan.error_summary}", file=sys.stderr)
        else:
            print(f"Jules cycle failed: {plan.error_summary}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
