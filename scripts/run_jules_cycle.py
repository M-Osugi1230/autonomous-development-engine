from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ade.cycle import (
    CycleError,
    CycleTask,
    HumanInputRequired,
    run_cycle,
)
from ade.providers.base import ProviderError, ProviderQuotaError
from ade.providers.jules import JulesProvider

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

    try:
        raw_task = json.loads(TASK_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw_task, dict):
            raise ValueError("cycle task must be a JSON object")
        task = CycleTask.from_dict(raw_task)

        provider = JulesProvider()
        source = provider.find_github_source(owner, repo)
        if source is None:
            raise RuntimeError(f"{owner}/{repo} is not visible in Jules sources")

        source_name = source.get("name")
        if not isinstance(source_name, str) or not source_name:
            raise RuntimeError("Jules source does not contain a valid resource name")

        result = run_cycle(provider, task=task, source_name=source_name)
        payload = {
            "task_id": result.task_id,
            "session_id": result.session_id,
            "session_url": result.session_url,
            "state": result.state,
            "pull_request_url": result.pull_request_url,
        }
        write_result(payload)

        print(f"PASS: Jules session completed: {result.session_id}")
        if result.pull_request_url:
            print(f"Pull request: {result.pull_request_url}")
        else:
            print("WARNING: session completed without a pull request URL")
        return 0

    except ProviderQuotaError as exc:
        write_result({"state": "PAUSED_QUOTA", "error": str(exc)})
        print(f"Jules quota exhausted: {exc}", file=sys.stderr)
        return 20
    except HumanInputRequired as exc:
        write_result({"state": "HUMAN_WAIT", "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 21
    except (CycleError, ProviderError, ValueError, RuntimeError) as exc:
        write_result({"state": "FAILED", "error": str(exc)})
        print(f"Jules cycle failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
