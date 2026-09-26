from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from jules_client import JulesClient, JulesError, JulesQuota, JulesUnauthorized

TASK_PATH = Path(".autodev/cycle-task.json")
RESULT_PATH = Path(".autodev/runtime/jules-session.json")


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _session_id(session: dict[str, Any]) -> str:
    identifier = session.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        identifier = name.removeprefix("sessions/")
        if identifier:
            return identifier
    raise RuntimeError("Jules returned a session without an id")


def _pull_request_url(session: dict[str, Any]) -> str | None:
    outputs = session.get("outputs", [])
    if not isinstance(outputs, list):
        return None
    for output in outputs:
        if not isinstance(output, dict):
            continue
        pull_request = output.get("pullRequest")
        if not isinstance(pull_request, dict):
            continue
        url = pull_request.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _load_task() -> dict[str, Any]:
    payload = json.loads(TASK_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cycle task must be a JSON object")
    for key in ("task_id", "title", "prompt"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
    return payload


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")
    task_id = "unknown"

    try:
        task = _load_task()
        task_id = str(task["task_id"])
        timeout_seconds = int(task.get("timeout_seconds", 1800))
        poll_interval_seconds = int(task.get("poll_interval_seconds", 15))
        if timeout_seconds < 60:
            raise ValueError("timeout_seconds must be >= 60")
        if poll_interval_seconds < 5:
            raise ValueError("poll_interval_seconds must be >= 5")

        client = JulesClient()
        source = client.find_github_source(owner, repo)
        if source is None:
            raise RuntimeError(f"{owner}/{repo} is not visible in Jules sources")
        source_name = source.get("name")
        if not isinstance(source_name, str) or not source_name:
            raise RuntimeError("Jules source does not contain a valid resource name")

        session = client.create_session(
            prompt=str(task["prompt"]),
            source=source_name,
            starting_branch=str(task.get("starting_branch", "main")),
            title=str(task["title"]),
            auto_create_pr=bool(task.get("auto_create_pr", True)),
        )
        session_id = _session_id(session)
        session_url = session.get("url") if isinstance(session.get("url"), str) else None
        deadline = time.monotonic() + timeout_seconds

        while True:
            current = client.get_session(session_id)
            state = current.get("state")
            if not isinstance(state, str):
                raise RuntimeError("Jules returned a session without state")

            if state == "COMPLETED":
                payload = {
                    "task_id": task_id,
                    "session_id": session_id,
                    "session_url": session_url,
                    "state": state,
                    "pull_request_url": _pull_request_url(current),
                }
                _write_result(payload)
                print(f"PASS: Jules session completed: {session_id}")
                if payload["pull_request_url"]:
                    print(f"Pull request: {payload['pull_request_url']}")
                return 0

            if state == "FAILED":
                _write_result({"task_id": task_id, "session_id": session_id, "state": state})
                print(f"Jules session failed: {session_id}", file=sys.stderr)
                return 1

            if state == "AWAITING_USER_FEEDBACK":
                _write_result(
                    {"task_id": task_id, "session_id": session_id, "state": "HUMAN_WAIT"}
                )
                print(f"Jules session requires human input: {session_id}", file=sys.stderr)
                return 21

            if state == "PAUSED":
                _write_result(
                    {"task_id": task_id, "session_id": session_id, "state": "PAUSED"}
                )
                print(f"Jules session paused: {session_id}", file=sys.stderr)
                return 22

            if time.monotonic() >= deadline:
                _write_result(
                    {"task_id": task_id, "session_id": session_id, "state": "TIMEOUT"}
                )
                print(f"Jules session timed out: {session_id}", file=sys.stderr)
                return 1

            time.sleep(poll_interval_seconds)

    except JulesQuota as exc:
        _write_result({"task_id": task_id, "state": "PAUSED_QUOTA", "error": str(exc)[:256]})
        print(f"Jules quota exhausted: {exc}", file=sys.stderr)
        return 20
    except (JulesUnauthorized, JulesError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        _write_result({"task_id": task_id, "state": "FAILED", "error": str(exc)[:256]})
        print(f"Trusted Jules cycle failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
