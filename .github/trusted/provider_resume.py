from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.execution_lease_store import claim_execution
from ade.production_provider_broker import (
    broker_resume_action,
    checkpoint_attempt,
    copilot_fallback_enabled,
)
from ade.providers.base import ProviderError, ProviderUnauthorizedError
from ade.remote_execution import execution_target_from_state

from github_client import GitHubClient, GitHubError
from provider_cycle import (
    _checkpoint,
    _load_task,
    _persist_checkpoint,
    _safe_error,
    _write_result,
    monitor_existing,
    provider_for_id,
    run_new_cycle,
)

CHECKPOINT_FILE = Path(".autodev/runtime/checkpoint.json")
CHECKPOINT_PATH = ".autodev/runtime/checkpoint.json"


def _load_checkpoint() -> dict | None:
    if not CHECKPOINT_FILE.exists():
        return None
    payload = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("checkpoint must be a JSON object")
    return payload


def _fallback_available() -> bool:
    return copilot_fallback_enabled(
        token=os.environ.get("COPILOT_AGENT_TOKEN"),
        explicit_enable=os.environ.get("ADE_ENABLE_COPILOT_FALLBACK"),
    )


def _preserve_attempt_floor(
    gh: GitHubClient,
    *,
    task_id: str,
    attempt: int,
) -> None:
    if attempt <= 0:
        return
    payload, _ = gh.get_json_file(CHECKPOINT_PATH)
    if payload.get("task_id") != task_id:
        return
    current_attempt = checkpoint_attempt(payload)
    if current_attempt >= attempt:
        return
    payload["attempt"] = attempt
    _persist_checkpoint(gh, payload)


def main() -> int:
    controller_owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    controller_repo = os.environ.get(
        "ADE_GITHUB_REPO",
        "autonomous-development-engine",
    )
    gh: GitHubClient | None = None
    task_id = "unknown"
    active_attempt = 0
    retrying_provider_error = False
    try:
        checkpoint = _load_checkpoint()
        if checkpoint is None:
            print("NOOP: no persisted checkpoint")
            return 0

        task = _load_task()
        task_id = str(task["task_id"])
        if checkpoint.get("task_id") != task_id:
            print(
                "NOOP: checkpoint belongs to "
                f"{checkpoint.get('task_id')!r}, current task is {task_id!r}"
            )
            return 0

        action, session_id, provider_id = broker_resume_action(
            checkpoint,
            now=datetime.now(UTC),
            fallback_available=_fallback_available(),
        )
        active_attempt = checkpoint_attempt(checkpoint)
        retrying_provider_error = (
            action == "START_NEW"
            and checkpoint.get("state") == "FAILED"
            and checkpoint.get("last_failure_kind") == "PROVIDER_ERROR"
        )
        if retrying_provider_error:
            active_attempt += 1

        if action == "NOOP":
            print(
                f"NOOP: checkpoint state {checkpoint.get('state')} "
                "is not auto-resumable"
            )
            return 0
        if action == "WAIT":
            print(
                f"WAIT: provider resume is due at "
                f"{checkpoint.get('resume_after')}"
            )
            return 0

        gh = GitHubClient()
        state_payload, _ = gh.get_json_file(".autodev/state.json")
        target_repository = execution_target_from_state(
            state_payload,
            fallback_repository=f"{controller_owner}/{controller_repo}",
        )
        owner, repo = target_repository.split("/", 1)

        if action == "MONITOR":
            assert session_id is not None
            assert provider_id is not None
            provider = provider_for_id(
                provider_id,
                owner=owner,
                repo=repo,
            )
            print(
                f"RESUME: monitoring {provider_id} session {session_id}"
            )
            result = monitor_existing(
                provider,
                provider_id=provider_id,
                gh=gh,
                task=task,
                session_id=session_id,
                target_repository=target_repository,
            )
            _preserve_attempt_floor(
                gh,
                task_id=task_id,
                attempt=active_attempt,
            )
            return result

        if action == "START_NEW":
            run_id = os.environ.get("GITHUB_RUN_ID", "manual")
            run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
            try:
                claim_execution(
                    gh,
                    task_id=task_id,
                    owner_id=(
                        f"github-actions-provider-resume:{run_id}:{run_attempt}"
                    ),
                    now=datetime.now(UTC),
                    ttl=timedelta(minutes=50),
                )
            except RuntimeError as exc:
                if "live execution lease" in str(exc):
                    print(f"NOOP: live execution lease still owns {task_id}")
                    return 0
                raise

            if retrying_provider_error:
                print(
                    f"RESUME: retrying provider error attempt {active_attempt}"
                )
            else:
                print("RESUME: routing a new provider session")
            result = run_new_cycle(
                task=task,
                gh=gh,
                owner=owner,
                repo=repo,
                target_repository=target_repository,
            )
            _preserve_attempt_floor(
                gh,
                task_id=task_id,
                attempt=active_attempt,
            )
            return result

        raise RuntimeError(f"unhandled resume action: {action}")
    except ProviderUnauthorizedError as exc:
        _write_result(
            {
                "state": "HUMAN_WAIT",
                "error": _safe_error(exc),
            }
        )
        print(
            f"Trusted provider resume authentication failed: {_safe_error(exc)}",
            file=sys.stderr,
        )
        return 21
    except (
        ProviderError,
        GitHubError,
        ValueError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        error = _safe_error(exc)
        if (
            retrying_provider_error
            and gh is not None
            and task_id != "unknown"
        ):
            try:
                _persist_checkpoint(
                    gh,
                    _checkpoint(
                        task_id,
                        "FAILED",
                        last_failure_kind="PROVIDER_ERROR",
                        last_error=error,
                    )
                    | {"attempt": active_attempt},
                )
            except Exception as checkpoint_exc:
                print(
                    "WARNING: failed to persist provider retry checkpoint: "
                    + _safe_error(checkpoint_exc),
                    file=sys.stderr,
                )
        _write_result(
            {
                "state": "FAILED",
                "error": error,
                "attempt": active_attempt,
            }
        )
        print(
            f"Trusted provider resume failed: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
