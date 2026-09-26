from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from github_client import GitHubClient, GitHubError
from jules_client import (
    JulesClient,
    JulesError,
    JulesPrecondition,
    JulesQuota,
    JulesUnauthorized,
)

TASK_PATH = Path(".autodev/cycle-task.json")
RESULT_PATH = Path(".autodev/runtime/jules-session.json")
CHECKPOINT_PATH = ".autodev/runtime/checkpoint.json"
STATE_PATH = ".autodev/state.json"
QUOTA_RETRY_DELAY = timedelta(hours=1)


def _safe_error(exc: BaseException) -> str:
    value = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    for env_name in ("JULES_API_KEY", "GITHUB_TOKEN"):
        secret = os.environ.get(env_name)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:256]


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _checkpoint(
    task_id: str,
    state: str,
    *,
    session_id: str | None = None,
    last_failure_kind: str | None = None,
    last_error: str | None = None,
    resume_after: str | None = None,
) -> dict[str, Any]:
    return {
        "attempt": 0,
        "last_error": last_error,
        "last_failure_kind": last_failure_kind,
        "provider_session_id": session_id,
        "replan_count": 0,
        "resume_after": resume_after,
        "state": state,
        "task_id": task_id,
    }


def _persist_checkpoint(gh: GitHubClient, payload: dict[str, Any]) -> None:
    gh.upsert_json_file(
        CHECKPOINT_PATH,
        payload,
        message=f"checkpoint: {payload['task_id']} {payload['state']}",
    )


def _set_project_status(
    gh: GitHubClient,
    *,
    task_id: str,
    status: str,
    metadata_updates: dict[str, Any] | None = None,
    clear_pause_metadata: bool = False,
) -> None:
    state, state_sha = gh.get_json_file(STATE_PATH)
    current_task_id = state.get("current_task_id")
    if current_task_id != task_id:
        raise RuntimeError(
            f"project state current_task_id {current_task_id!r} does not match {task_id!r}"
        )

    state["status"] = status
    state["updated_at"] = datetime.now(UTC).isoformat()
    metadata = dict(state.get("metadata", {}))
    if clear_pause_metadata:
        metadata.pop("pause_reason", None)
        metadata.pop("resume_after", None)
    if metadata_updates:
        metadata.update(metadata_updates)
    state["metadata"] = metadata

    gh.put_json_file(
        STATE_PATH,
        state,
        sha=state_sha,
        message=f"state: {task_id} {status.lower()}",
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


def _parse_session_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _infer_rolling_quota_resume_after(
    client: JulesClient,
    *,
    now: datetime,
    daily_limit: int,
) -> datetime | None:
    if daily_limit < 1:
        raise ValueError("daily_limit must be positive")
    cutoff = now - timedelta(hours=24)
    create_times: list[datetime] = []
    for session in client.list_sessions(page_size=100, max_pages=10):
        created = _parse_session_time(session.get("createTime"))
        if created is not None and created >= cutoff:
            create_times.append(created)

    if len(create_times) < daily_limit:
        return None

    create_times.sort()
    release_index = len(create_times) - daily_limit
    return create_times[release_index] + timedelta(hours=24, minutes=2)


def _quota_pause(
    gh: GitHubClient,
    *,
    task_id: str,
    session_id: str | None,
    exc: BaseException,
    resume_at: datetime | None = None,
) -> int:
    resume_dt = resume_at or (datetime.now(UTC) + QUOTA_RETRY_DELAY)
    resume_after = resume_dt.astimezone(UTC).isoformat()
    error = _safe_error(exc)
    payload = _checkpoint(
        task_id,
        "PAUSED_QUOTA",
        session_id=session_id,
        last_failure_kind="PROVIDER_QUOTA",
        last_error=error,
        resume_after=resume_after,
    )
    _persist_checkpoint(gh, payload)
    _set_project_status(
        gh,
        task_id=task_id,
        status="PAUSED_QUOTA",
        metadata_updates={
            "pause_reason": "jules-rolling-quota",
            "resume_after": resume_after,
        },
    )
    _write_result({**payload, "state": "PAUSED_QUOTA"})
    print(f"Jules quota exhausted; resume after {resume_after}", file=sys.stderr)
    return 20


def _handle_precondition(
    client: JulesClient,
    gh: GitHubClient,
    *,
    task_id: str,
    session_id: str | None,
    exc: JulesPrecondition,
) -> int:
    raw_limit = os.environ.get("ADE_JULES_DAILY_TASK_LIMIT", "15")
    try:
        daily_limit = int(raw_limit)
    except ValueError:
        daily_limit = 15

    try:
        resume_at = _infer_rolling_quota_resume_after(
            client,
            now=datetime.now(UTC),
            daily_limit=daily_limit,
        )
    except (JulesError, ValueError):
        resume_at = None

    if resume_at is not None:
        return _quota_pause(
            gh,
            task_id=task_id,
            session_id=session_id,
            exc=exc,
            resume_at=resume_at,
        )

    error = _safe_error(exc)
    checkpoint = _checkpoint(
        task_id,
        "REPLAN",
        session_id=session_id,
        last_failure_kind="PROVIDER_ERROR",
        last_error=error,
    )
    _persist_checkpoint(gh, checkpoint)
    _set_project_status(
        gh,
        task_id=task_id,
        status="BLOCKED",
        metadata_updates={"pause_reason": "provider-precondition"},
    )
    _write_result({"task_id": task_id, "state": "REPLAN", "error": error})
    print(f"Jules precondition requires replan: {error}", file=sys.stderr)
    return 22


def monitor_existing(
    client: JulesClient,
    gh: GitHubClient,
    *,
    task: dict[str, Any],
    session_id: str,
    session_url: str | None = None,
) -> int:
    task_id = str(task["task_id"])
    _set_project_status(
        gh,
        task_id=task_id,
        status="RUNNING",
        clear_pause_metadata=True,
    )
    timeout_seconds = int(task.get("timeout_seconds", 1800))
    poll_interval_seconds = int(task.get("poll_interval_seconds", 15))
    if timeout_seconds < 60:
        raise ValueError("timeout_seconds must be >= 60")
    if poll_interval_seconds < 5:
        raise ValueError("poll_interval_seconds must be >= 5")

    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            current = client.get_session(session_id)
            state = current.get("state")
            if not isinstance(state, str):
                raise RuntimeError("Jules returned a session without state")

            if state == "COMPLETED":
                checkpoint = _checkpoint(task_id, "COMPLETED", session_id=session_id)
                _persist_checkpoint(gh, checkpoint)
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
                error = f"Jules session failed: {session_id}"
                checkpoint = _checkpoint(
                    task_id,
                    "FAILED",
                    session_id=session_id,
                    last_failure_kind="CYCLE_FAILED",
                    last_error=error,
                )
                _persist_checkpoint(gh, checkpoint)
                _set_project_status(
                    gh,
                    task_id=task_id,
                    status="FAILED",
                    metadata_updates={"pause_reason": "provider-cycle-failed"},
                )
                _write_result(checkpoint)
                print(error, file=sys.stderr)
                return 1

            if state == "AWAITING_USER_FEEDBACK":
                checkpoint = _checkpoint(
                    task_id,
                    "HUMAN_WAIT",
                    session_id=session_id,
                    last_failure_kind="HUMAN_INPUT",
                    last_error="Jules session requires human input",
                )
                _persist_checkpoint(gh, checkpoint)
                _set_project_status(
                    gh,
                    task_id=task_id,
                    status="HUMAN_WAIT",
                    metadata_updates={"pause_reason": "human-input-required"},
                )
                _write_result(checkpoint)
                print(f"Jules session requires human input: {session_id}", file=sys.stderr)
                return 21

            if state == "PAUSED":
                checkpoint = _checkpoint(
                    task_id,
                    "REPLAN",
                    session_id=session_id,
                    last_failure_kind="PROVIDER_ERROR",
                    last_error="Jules session entered PAUSED state",
                )
                _persist_checkpoint(gh, checkpoint)
                _set_project_status(
                    gh,
                    task_id=task_id,
                    status="BLOCKED",
                    metadata_updates={"pause_reason": "provider-replan"},
                )
                _write_result(checkpoint)
                print(f"Jules session paused: {session_id}", file=sys.stderr)
                return 22

            if time.monotonic() >= deadline:
                checkpoint = _checkpoint(
                    task_id,
                    "RUNNING",
                    session_id=session_id,
                    last_failure_kind="CYCLE_TIMEOUT",
                    last_error="monitor timeout; provider session may still be active",
                )
                _persist_checkpoint(gh, checkpoint)
                _write_result(checkpoint)
                print(
                    f"DEFERRED: Jules session still running after monitor timeout: {session_id}"
                )
                return 0

            time.sleep(poll_interval_seconds)
    except JulesQuota as exc:
        return _quota_pause(gh, task_id=task_id, session_id=session_id, exc=exc)


def run_new_cycle(
    *,
    task: dict[str, Any],
    client: JulesClient,
    gh: GitHubClient,
    owner: str,
    repo: str,
) -> int:
    task_id = str(task["task_id"])
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
    _persist_checkpoint(
        gh,
        _checkpoint(task_id, "RUNNING", session_id=session_id),
    )
    return monitor_existing(
        client,
        gh,
        task=task,
        session_id=session_id,
        session_url=session_url,
    )


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")
    task_id = "unknown"
    session_id: str | None = None

    try:
        task = _load_task()
        task_id = str(task["task_id"])
        client = JulesClient()
        gh = GitHubClient()
        return run_new_cycle(task=task, client=client, gh=gh, owner=owner, repo=repo)

    except JulesQuota as exc:
        try:
            gh
        except UnboundLocalError:
            print("Jules quota exhausted before GitHub checkpoint client initialized", file=sys.stderr)
            return 20
        return _quota_pause(gh, task_id=task_id, session_id=session_id, exc=exc)
    except JulesPrecondition as exc:
        try:
            client
            gh
        except UnboundLocalError:
            error = _safe_error(exc)
            _write_result({"task_id": task_id, "state": "REPLAN", "error": error})
            print(f"Jules precondition before quota inspection: {error}", file=sys.stderr)
            return 22
        return _handle_precondition(
            client,
            gh,
            task_id=task_id,
            session_id=session_id,
            exc=exc,
        )
    except (
        JulesUnauthorized,
        JulesError,
        GitHubError,
        ValueError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        error = _safe_error(exc)
        try:
            gh
        except UnboundLocalError:
            gh = None
        if gh is not None and task_id != "unknown":
            try:
                checkpoint = _checkpoint(
                    task_id,
                    "FAILED",
                    session_id=session_id,
                    last_failure_kind="PROVIDER_ERROR",
                    last_error=error,
                )
                _persist_checkpoint(gh, checkpoint)
            except Exception as checkpoint_exc:
                print(
                    f"WARNING: failed to persist checkpoint: {_safe_error(checkpoint_exc)}",
                    file=sys.stderr,
                )
        _write_result({"task_id": task_id, "state": "FAILED", "error": error})
        print(f"Trusted Jules cycle failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
