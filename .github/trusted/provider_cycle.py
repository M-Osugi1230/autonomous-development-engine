from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.execution_lease_store import claim_execution
from ade.production_provider_broker import (
    BrokerAvailability,
    COPILOT_PROVIDER_ID,
    JULES_PROVIDER_ID,
    checkpoint_provider_id,
    copilot_fallback_enabled,
    provider_descriptors,
    route_implementation_provider,
)
from ade.provider_registry import ProviderRegistry
from ade.provider_router import RoutingOutcome
from ade.providers.base import (
    ProviderError,
    ProviderQuotaError,
    ProviderUnauthorizedError,
)
from ade.providers.github_copilot import GitHubCopilotProvider
from ade.providers.jules import JulesProvider
from ade.remote_execution import (
    RemoteExecutionReceipt,
    execution_target_from_state,
    receipt_binds_pull_request,
)

from github_client import GitHubClient, GitHubError
from jules_client import JulesClient
from quota_scheduler_runtime import assess_jules_admission, tagged_title

TASK_PATH = Path(".autodev/cycle-task.json")
RESULT_PATH = Path(".autodev/runtime/jules-session.json")
CHECKPOINT_PATH = ".autodev/runtime/checkpoint.json"
STATE_PATH = ".autodev/state.json"
REMOTE_EXECUTION_PATH = ".autodev/runtime/remote-execution.json"
PROVIDER_RETRY_DELAY = timedelta(hours=1)


def _safe_error(exc: BaseException) -> str:
    value = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    for env_name in (
        "JULES_API_KEY",
        "GITHUB_TOKEN",
        "COPILOT_AGENT_TOKEN",
    ):
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
    provider_id: str | None = None,
    session_id: str | None = None,
    last_failure_kind: str | None = None,
    last_error: str | None = None,
    resume_after: str | None = None,
) -> dict[str, Any]:
    payload = {
        "attempt": 0,
        "last_error": last_error,
        "last_failure_kind": last_failure_kind,
        "provider_session_id": session_id,
        "replan_count": 0,
        "resume_after": resume_after,
        "state": state,
        "task_id": task_id,
    }
    if provider_id is not None:
        payload["provider_id"] = provider_id
    return payload


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
        for key in (
            "pause_reason",
            "resume_after",
            "quota_admission_reason",
            "quota_remaining",
        ):
            metadata.pop(key, None)
    if metadata_updates:
        metadata.update(metadata_updates)
    state["metadata"] = metadata
    gh.put_json_file(
        STATE_PATH,
        state,
        sha=state_sha,
        message=f"state: {task_id} {status.lower()}",
    )


def _persist_remote_execution(
    gh: GitHubClient,
    *,
    task_id: str,
    target_repository: str,
    pull_request_url: str,
    provider_id: str,
) -> None:
    try:
        existing, _ = gh.get_json_file(REMOTE_EXECUTION_PATH)
    except GitHubError as exc:
        if "GitHub HTTP 404:" not in str(exc):
            raise
        existing = None

    if receipt_binds_pull_request(
        existing,
        task_id=task_id,
        target_repository=target_repository,
        pull_request_url=pull_request_url,
    ):
        return

    receipt = RemoteExecutionReceipt(
        task_id=task_id,
        target_repository=target_repository,
        pull_request_url=pull_request_url,
        recorded_at=datetime.now(UTC).isoformat(),
    )
    gh.upsert_json_file(
        REMOTE_EXECUTION_PATH,
        receipt.to_dict(),
        message=f"remote: PR created for {task_id}",
    )
    try:
        gh.dispatch(
            "ade_remote_pr_monitor",
            {
                "task_id": task_id,
                "target_repository": target_repository,
                "pull_request_url": pull_request_url,
                "source": "provider-cycle",
                "provider": provider_id,
            },
        )
    except (GitHubError, ValueError) as exc:
        print(
            "WARNING: immediate Remote PR Monitor dispatch failed; "
            "scheduled watchdog remains armed: " + _safe_error(exc),
            file=sys.stderr,
        )


def _load_task() -> dict[str, Any]:
    payload = json.loads(TASK_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cycle task must be a JSON object")
    for key in ("task_id", "title", "prompt"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
    return payload


def _session_id(session: dict[str, Any]) -> str:
    identifier = session.get("id")
    if isinstance(identifier, str) and identifier.strip():
        return identifier.strip()
    name = session.get("name")
    if isinstance(name, str):
        for prefix in ("sessions/", "tasks/"):
            if name.startswith(prefix):
                identifier = name.removeprefix(prefix)
                if identifier and "/" not in identifier:
                    return identifier
    raise RuntimeError("provider returned a session without an id")


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


def copilot_is_enabled() -> bool:
    return copilot_fallback_enabled(
        token=os.environ.get("COPILOT_AGENT_TOKEN"),
        explicit_enable=os.environ.get("ADE_ENABLE_COPILOT_FALLBACK"),
    )


def provider_for_id(
    provider_id: str,
    *,
    owner: str,
    repo: str,
):
    if provider_id == JULES_PROVIDER_ID:
        return JulesProvider()
    if provider_id == COPILOT_PROVIDER_ID:
        token = os.environ.get("COPILOT_AGENT_TOKEN", "").strip()
        if not token:
            raise ProviderUnauthorizedError(
                "COPILOT_AGENT_TOKEN is required to resume GitHub Copilot provider"
            )
        return GitHubCopilotProvider(
            token=token,
            owner=owner,
            repo=repo,
        )
    raise ValueError(f"unsupported provider_id: {provider_id}")


def _registry(
    *,
    owner: str,
    repo: str,
    include_copilot: bool,
) -> ProviderRegistry:
    descriptors = {
        item.provider_id: item
        for item in provider_descriptors()
    }
    pairs = [
        (
            descriptors[JULES_PROVIDER_ID],
            provider_for_id(JULES_PROVIDER_ID, owner=owner, repo=repo),
        )
    ]
    if include_copilot:
        pairs.append(
            (
                descriptors[COPILOT_PROVIDER_ID],
                provider_for_id(COPILOT_PROVIDER_ID, owner=owner, repo=repo),
            )
        )
    return ProviderRegistry.from_pairs(pairs)


def _source_name(
    provider_id: str,
    provider,
    *,
    owner: str,
    repo: str,
) -> str:
    if provider_id == JULES_PROVIDER_ID:
        source = provider.find_github_source(owner, repo)
        if source is None:
            raise RuntimeError(f"{owner}/{repo} is not visible in Jules sources")
        source_name = source.get("name")
        if not isinstance(source_name, str) or not source_name:
            raise RuntimeError("Jules source does not contain a valid resource name")
        return source_name
    if provider_id == COPILOT_PROVIDER_ID:
        return provider.source_name
    raise ValueError(f"unsupported provider_id: {provider_id}")


def _pause_without_session(
    gh: GitHubClient,
    *,
    task_id: str,
    reason: str,
    resume_after: str | None,
    quota_admission: dict[str, Any] | None = None,
) -> int:
    due = resume_after or (
        datetime.now(UTC) + PROVIDER_RETRY_DELAY
    ).isoformat()
    checkpoint = _checkpoint(
        task_id,
        "PAUSED_QUOTA",
        last_failure_kind="PROVIDER_QUOTA",
        last_error=reason,
        resume_after=due,
    )
    _persist_checkpoint(gh, checkpoint)
    metadata = {
        "pause_reason": "provider-capacity",
        "resume_after": due,
        "next_system_action": "resume-after-provider-quota",
        "next_required_human_action": None,
    }
    if quota_admission is not None:
        metadata["quota_admission_reason"] = quota_admission.get("reason")
        metadata["quota_remaining"] = quota_admission.get("remaining")
    _set_project_status(
        gh,
        task_id=task_id,
        status="PAUSED_QUOTA",
        metadata_updates=metadata,
    )
    _write_result(
        {
            **checkpoint,
            "state": "PAUSED_QUOTA",
            "quota_admission": quota_admission,
        }
    )
    print(
        f"Provider broker deferred {task_id}: {reason}; resume after {due}",
        file=sys.stderr,
    )
    return 20


def _pause_existing_session(
    gh: GitHubClient,
    *,
    task_id: str,
    provider_id: str,
    session_id: str,
    error: str,
) -> int:
    due = (datetime.now(UTC) + PROVIDER_RETRY_DELAY).isoformat()
    checkpoint = _checkpoint(
        task_id,
        "PAUSED_QUOTA",
        provider_id=provider_id,
        session_id=session_id,
        last_failure_kind="PROVIDER_QUOTA",
        last_error=error,
        resume_after=due,
    )
    _persist_checkpoint(gh, checkpoint)
    _set_project_status(
        gh,
        task_id=task_id,
        status="PAUSED_QUOTA",
        metadata_updates={
            "pause_reason": f"{provider_id}-quota",
            "resume_after": due,
            "next_system_action": "resume-provider-session",
            "next_required_human_action": None,
            "implementation_provider": provider_id,
        },
    )
    _write_result(checkpoint)
    return 20


def _human_wait(
    gh: GitHubClient,
    *,
    task_id: str,
    provider_id: str | None,
    session_id: str | None,
    error: str,
) -> int:
    checkpoint = _checkpoint(
        task_id,
        "HUMAN_WAIT",
        provider_id=provider_id,
        session_id=session_id,
        last_failure_kind="HUMAN_INPUT",
        last_error=error,
    )
    _persist_checkpoint(gh, checkpoint)
    _set_project_status(
        gh,
        task_id=task_id,
        status="HUMAN_WAIT",
        metadata_updates={
            "pause_reason": "provider-human-input",
            "next_required_human_action": error,
            "implementation_provider": provider_id,
        },
    )
    _write_result(checkpoint)
    return 21


def monitor_existing(
    provider,
    *,
    provider_id: str,
    gh: GitHubClient,
    task: dict[str, Any],
    session_id: str,
    target_repository: str,
    session_url: str | None = None,
) -> int:
    task_id = str(task["task_id"])
    _set_project_status(
        gh,
        task_id=task_id,
        status="RUNNING",
        metadata_updates={
            "next_system_action": "monitor-provider-session",
            "next_required_human_action": None,
            "implementation_provider": provider_id,
        },
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
            current = provider.get_session(session_id)
            state = current.get("state")
            if not isinstance(state, str):
                raise RuntimeError("provider returned a session without state")

            observed_pull_request_url = _pull_request_url(current)
            if (
                target_repository != gh.repository
                and observed_pull_request_url is not None
            ):
                _persist_remote_execution(
                    gh,
                    task_id=task_id,
                    target_repository=target_repository,
                    pull_request_url=observed_pull_request_url,
                    provider_id=provider_id,
                )

            if state == "COMPLETED":
                pull_request_url = observed_pull_request_url
                if target_repository != gh.repository and pull_request_url is None:
                    raise RuntimeError(
                        "external provider session completed without a pull request"
                    )
                checkpoint = _checkpoint(
                    task_id,
                    "COMPLETED",
                    provider_id=provider_id,
                    session_id=session_id,
                )
                _persist_checkpoint(gh, checkpoint)
                _write_result(
                    {
                        **checkpoint,
                        "session_url": session_url,
                        "target_repository": target_repository,
                        "pull_request_url": pull_request_url,
                    }
                )
                print(
                    f"PASS: {provider_id} session completed: {session_id}"
                )
                return 0

            if state == "FAILED":
                error = f"{provider_id} session failed: {session_id}"
                checkpoint = _checkpoint(
                    task_id,
                    "FAILED",
                    provider_id=provider_id,
                    session_id=session_id,
                    last_failure_kind="CYCLE_FAILED",
                    last_error=error,
                )
                _persist_checkpoint(gh, checkpoint)
                _set_project_status(
                    gh,
                    task_id=task_id,
                    status="FAILED",
                    metadata_updates={
                        "pause_reason": "provider-cycle-failed",
                        "implementation_provider": provider_id,
                    },
                )
                _write_result(checkpoint)
                return 1

            if state == "AWAITING_USER_FEEDBACK":
                return _human_wait(
                    gh,
                    task_id=task_id,
                    provider_id=provider_id,
                    session_id=session_id,
                    error=f"{provider_id} session requires human input",
                )

            if state == "PAUSED":
                error = f"{provider_id} session entered PAUSED state"
                checkpoint = _checkpoint(
                    task_id,
                    "REPLAN",
                    provider_id=provider_id,
                    session_id=session_id,
                    last_failure_kind="PROVIDER_ERROR",
                    last_error=error,
                )
                _persist_checkpoint(gh, checkpoint)
                _set_project_status(
                    gh,
                    task_id=task_id,
                    status="BLOCKED",
                    metadata_updates={
                        "pause_reason": "provider-replan",
                        "implementation_provider": provider_id,
                    },
                )
                _write_result(checkpoint)
                return 22

            if time.monotonic() >= deadline:
                checkpoint = _checkpoint(
                    task_id,
                    "RUNNING",
                    provider_id=provider_id,
                    session_id=session_id,
                    last_failure_kind="CYCLE_TIMEOUT",
                    last_error="monitor timeout; provider session may still be active",
                )
                _persist_checkpoint(gh, checkpoint)
                _write_result(checkpoint)
                print(
                    f"DEFERRED: {provider_id} session still running after monitor timeout: "
                    f"{session_id}"
                )
                return 0

            time.sleep(poll_interval_seconds)
    except ProviderQuotaError as exc:
        return _pause_existing_session(
            gh,
            task_id=task_id,
            provider_id=provider_id,
            session_id=session_id,
            error=_safe_error(exc),
        )
    except ProviderUnauthorizedError as exc:
        return _human_wait(
            gh,
            task_id=task_id,
            provider_id=provider_id,
            session_id=session_id,
            error=f"{provider_id} authentication requires attention: {_safe_error(exc)}",
        )


def _start_with_provider(
    *,
    provider_id: str,
    registry: ProviderRegistry,
    task: dict[str, Any],
    owner: str,
    repo: str,
) -> tuple[Any, str, str | None]:
    registration = registry.require(provider_id)
    provider = registration.provider
    source_name = _source_name(
        provider_id,
        provider,
        owner=owner,
        repo=repo,
    )
    session = provider.create_session(
        prompt=str(task["prompt"]),
        source=source_name,
        starting_branch=str(task.get("starting_branch", "main")),
        title=tagged_title(
            str(task["title"]),
            purpose="implementation",
        ),
        auto_create_pr=bool(task.get("auto_create_pr", True)),
        require_plan_approval=False,
    )
    session_id = _session_id(session)
    session_url = (
        session.get("url")
        if isinstance(session.get("url"), str)
        else None
    )
    return provider, session_id, session_url


def run_new_cycle(
    *,
    task: dict[str, Any],
    gh: GitHubClient,
    owner: str,
    repo: str,
    target_repository: str,
) -> int:
    task_id = str(task["task_id"])
    quota_client = JulesClient()
    admission = assess_jules_admission(
        client=quota_client,
        gh=gh,
        purpose="implementation",
    )
    copilot_enabled = copilot_is_enabled()
    registry = _registry(
        owner=owner,
        repo=repo,
        include_copilot=copilot_enabled,
    )
    decision = route_implementation_provider(
        registry,
        availability=BrokerAvailability(
            jules_available=admission.allowed,
            copilot_available=copilot_enabled,
            jules_reason=None if admission.allowed else admission.reason,
            copilot_reason=(
                None
                if copilot_enabled
                else "COPILOT fallback requires token and explicit cost opt-in"
            ),
        ),
    )

    if decision.outcome is RoutingOutcome.NO_PROVIDER:
        return _pause_without_session(
            gh,
            task_id=task_id,
            reason=decision.reason,
            resume_after=admission.resume_after,
            quota_admission=admission.to_dict(),
        )

    provider_id = decision.selected_provider_id
    assert provider_id is not None

    try:
        provider, session_id, session_url = _start_with_provider(
            provider_id=provider_id,
            registry=registry,
            task=task,
            owner=owner,
            repo=repo,
        )
    except ProviderQuotaError as exc:
        # A race can exhaust Jules between quota admission and session creation.
        # Reroute only before a session exists.
        if provider_id == JULES_PROVIDER_ID and copilot_enabled:
            fallback_decision = route_implementation_provider(
                registry,
                availability=BrokerAvailability(
                    jules_available=False,
                    copilot_available=True,
                    jules_reason=_safe_error(exc),
                ),
            )
            fallback_id = fallback_decision.selected_provider_id
            if fallback_id == COPILOT_PROVIDER_ID:
                provider_id = fallback_id
                try:
                    provider, session_id, session_url = _start_with_provider(
                        provider_id=provider_id,
                        registry=registry,
                        task=task,
                        owner=owner,
                        repo=repo,
                    )
                except ProviderQuotaError as fallback_exc:
                    return _pause_without_session(
                        gh,
                        task_id=task_id,
                        reason=(
                            "all configured implementation providers are quota paused: "
                            + _safe_error(fallback_exc)
                        ),
                        resume_after=admission.resume_after,
                        quota_admission=admission.to_dict(),
                    )
            else:
                return _pause_without_session(
                    gh,
                    task_id=task_id,
                    reason=_safe_error(exc),
                    resume_after=admission.resume_after,
                    quota_admission=admission.to_dict(),
                )
        else:
            return _pause_without_session(
                gh,
                task_id=task_id,
                reason=_safe_error(exc),
                resume_after=admission.resume_after,
                quota_admission=admission.to_dict(),
            )

    _persist_checkpoint(
        gh,
        _checkpoint(
            task_id,
            "RUNNING",
            provider_id=provider_id,
            session_id=session_id,
        ),
    )
    return monitor_existing(
        provider,
        provider_id=provider_id,
        gh=gh,
        task=task,
        session_id=session_id,
        target_repository=target_repository,
        session_url=session_url,
    )


def main() -> int:
    controller_owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    controller_repo = os.environ.get(
        "ADE_GITHUB_REPO",
        "autonomous-development-engine",
    )
    task_id = "unknown"
    gh: GitHubClient | None = None
    try:
        task = _load_task()
        task_id = str(task["task_id"])
        gh = GitHubClient()
        state_payload, _ = gh.get_json_file(STATE_PATH)
        target_repository = execution_target_from_state(
            state_payload,
            fallback_repository=f"{controller_owner}/{controller_repo}",
        )
        owner, repo = target_repository.split("/", 1)

        run_id = os.environ.get("GITHUB_RUN_ID", "manual")
        run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        try:
            claim_execution(
                gh,
                task_id=task_id,
                owner_id=f"github-actions-provider:{run_id}:{run_attempt}",
                now=datetime.now(UTC),
                ttl=timedelta(minutes=50),
            )
        except RuntimeError as exc:
            if "live execution lease" in str(exc):
                print(f"NOOP: duplicate dispatch blocked for {task_id}")
                return 0
            raise

        return run_new_cycle(
            task=task,
            gh=gh,
            owner=owner,
            repo=repo,
            target_repository=target_repository,
        )
    except ProviderUnauthorizedError as exc:
        if gh is not None and task_id != "unknown":
            return _human_wait(
                gh,
                task_id=task_id,
                provider_id=None,
                session_id=None,
                error=f"provider authentication requires attention: {_safe_error(exc)}",
            )
        _write_result(
            {"task_id": task_id, "state": "HUMAN_WAIT", "error": _safe_error(exc)}
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
        if gh is not None and task_id != "unknown":
            try:
                checkpoint = _checkpoint(
                    task_id,
                    "FAILED",
                    last_failure_kind="PROVIDER_ERROR",
                    last_error=error,
                )
                _persist_checkpoint(gh, checkpoint)
            except Exception as checkpoint_exc:
                print(
                    "WARNING: failed to persist checkpoint: "
                    + _safe_error(checkpoint_exc),
                    file=sys.stderr,
                )
        _write_result({"task_id": task_id, "state": "FAILED", "error": error})
        print(f"Trusted provider cycle failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
