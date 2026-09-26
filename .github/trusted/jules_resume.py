from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from github_client import GitHubClient, GitHubError
from jules_client import JulesClient, JulesError, JulesUnauthorized
from jules_cycle import _load_task, _safe_error, monitor_existing, run_new_cycle

CHECKPOINT_FILE = Path(".autodev/runtime/checkpoint.json")


def _load_checkpoint() -> dict[str, Any] | None:
    if not CHECKPOINT_FILE.exists():
        return None
    payload = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("checkpoint must be a JSON object")
    return payload


def _parse_due(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resume_after must be a non-empty ISO-8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("resume_after must be timezone-aware")
    return parsed.astimezone(UTC)


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")

    try:
        checkpoint = _load_checkpoint()
        if checkpoint is None:
            print("NOOP: no persisted checkpoint")
            return 0

        task = _load_task()
        task_id = str(task["task_id"])
        checkpoint_task_id = checkpoint.get("task_id")
        if checkpoint_task_id != task_id:
            print(
                f"NOOP: checkpoint belongs to {checkpoint_task_id!r}, current task is {task_id!r}"
            )
            return 0

        state = checkpoint.get("state")
        if not isinstance(state, str):
            raise ValueError("checkpoint state must be a string")

        if state in {"COMPLETED", "FAILED", "HUMAN_WAIT", "REPLAN"}:
            print(f"NOOP: checkpoint state {state} is not auto-resumable")
            return 0

        client = JulesClient()
        gh = GitHubClient()
        session_id = checkpoint.get("provider_session_id")
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id.strip()
        ):
            raise ValueError("provider_session_id must be a non-empty string or null")

        if state == "RUNNING":
            if not session_id:
                raise ValueError("RUNNING checkpoint requires provider_session_id")
            print(f"RESUME: monitoring existing Jules session {session_id}")
            return monitor_existing(
                client,
                gh,
                task=task,
                session_id=session_id,
            )

        if state == "PAUSED_QUOTA":
            due = _parse_due(checkpoint.get("resume_after"))
            if due is None:
                print("WAIT: quota checkpoint has no resume_after")
                return 0
            now = datetime.now(UTC)
            if now < due:
                print(f"WAIT: quota resume is due at {due.isoformat()}")
                return 0
            if session_id:
                print(f"RESUME: quota window elapsed; monitoring session {session_id}")
                return monitor_existing(
                    client,
                    gh,
                    task=task,
                    session_id=session_id,
                )
            print("RESUME: quota window elapsed; starting a new Jules session")
            return run_new_cycle(
                task=task,
                client=client,
                gh=gh,
                owner=owner,
                repo=repo,
            )

        raise ValueError(f"unsupported checkpoint state: {state}")

    except (
        JulesUnauthorized,
        JulesError,
        GitHubError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Trusted resume failed: {_safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
