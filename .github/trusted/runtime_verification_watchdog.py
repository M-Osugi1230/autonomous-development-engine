from __future__ import annotations

import inspect
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    record_runtime_verification_dispatch,
    runtime_verification_paths,
)
from github_client import GitHubClient, GitHubError
from runtime_probes import build_runtime_probe_registry


STATE_PATH = ".autodev/state.json"
REMOTE_PATH = ".autodev/runtime/remote-execution.json"
RESULT_PATH = Path(".autodev/runtime/runtime-verification-watchdog-result.json")


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _result(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "state": state,
        "reason": reason,
    }
    payload.update(extra)
    return payload


def _positive_run_id(value: object) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError("workflow run id must be a positive integer")


def _read_optional_json(
    gh: GitHubClient,
    path: str,
) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path)
        return payload
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise


def _build_probe_registry(target_repository: str):
    """Build the branch-native registry without changing its fingerprint.

    Older control branches expose build_runtime_probe_registry(workspace=None)
    while newer trusted code also accepts target_repository as a keyword-only
    selector. Inspect the callable instead of catching TypeError so errors raised
    inside registry construction are never hidden by a compatibility fallback.
    """
    parameters = inspect.signature(build_runtime_probe_registry).parameters
    if "target_repository" in parameters:
        return build_runtime_probe_registry(
            target_repository=target_repository,
        )
    return build_runtime_probe_registry()


def watchdog_disposition(
    *,
    state_payload: dict[str, Any],
    receipt: RuntimeVerificationReceipt | None,
) -> tuple[str, str]:
    task_id = state_payload.get("current_task_id")
    if not isinstance(task_id, str) or not task_id:
        return "NOOP", "no-current-task"
    if receipt is None:
        return "NOOP", "runtime-receipt-missing"
    if receipt.task_id != task_id:
        return "NOOP", "runtime-receipt-not-current"
    if receipt.status == "ARMED":
        return "DISPATCH", "armed-runtime-verification"
    return "NOOP", f"runtime-receipt-{receipt.status.lower()}"


def run_watchdog(
    *,
    gh: GitHubClient,
    target_client_factory: Callable[[str, str], GitHubClient],
    target_token: str,
    run_id: int,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(target_token, str) or not target_token.strip():
        raise ValueError("ADE_TARGET_GITHUB_TOKEN is required")
    run_id = _positive_run_id(run_id)

    state_payload, _ = gh.get_json_file(STATE_PATH)
    task_id = state_payload.get("current_task_id")
    if not isinstance(task_id, str) or not task_id:
        return _result("NOOP", "no-current-task")

    contract_path, receipt_path = runtime_verification_paths(task_id)
    raw_receipt = _read_optional_json(gh, receipt_path)
    receipt = (
        RuntimeVerificationReceipt.from_dict(raw_receipt)
        if raw_receipt is not None
        else None
    )
    action, reason = watchdog_disposition(
        state_payload=state_payload,
        receipt=receipt,
    )
    if action != "DISPATCH":
        return _result(
            "NOOP",
            reason,
            task_id=task_id,
            receipt_status=(receipt.status if receipt is not None else None),
        )
    assert receipt is not None

    remote_payload, _ = gh.get_json_file(REMOTE_PATH)
    remote = RemoteExecutionReceipt.from_dict(remote_payload)
    if remote.task_id != task_id:
        raise ValueError("remote execution receipt does not match current task")
    if remote.target_repository != receipt.target_repository:
        raise ValueError("remote execution repository does not match runtime receipt")

    target = target_client_factory(remote.target_repository, target_token.strip())
    pr = target.get_pull_request(remote.pull_request_number)
    if pr.get("merged") is not True or not pr.get("merged_at"):
        return _result(
            "NOOP",
            "target-pull-request-not-merged",
            task_id=task_id,
            pull_request_number=remote.pull_request_number,
        )

    head = pr.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    merge_sha = pr.get("merge_commit_sha")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        raise ValueError("target pull request head SHA is invalid")
    if not isinstance(merge_sha, str) or len(merge_sha) != 40:
        raise ValueError("target pull request merge SHA is invalid")
    if merge_sha != receipt.source_sha:
        raise ValueError("target merge SHA does not match runtime receipt")

    contract_payload, _ = gh.get_json_file(contract_path)
    contract = RuntimeVerificationContract.from_dict(contract_payload)
    if contract.fingerprint() != receipt.contract_fingerprint:
        raise ValueError("runtime contract fingerprint does not match receipt")

    registry = _build_probe_registry(receipt.target_repository)
    # Keep this base payload at eight properties or fewer. Legacy control
    # branches append both control_ref and project_key, and repository_dispatch
    # accepts at most ten top-level client_payload properties.
    event = {
        "task_id": receipt.task_id,
        "verification_id": receipt.verification_id,
        "target_repository": receipt.target_repository,
        "source_sha": receipt.source_sha,
        "remote_monitor_workflow_run_id": run_id,
        "pull_request_number": remote.pull_request_number,
        "pull_request_head_sha": head_sha,
        "trusted_merge_sha": merge_sha,
    }
    gh.dispatch("ade_runtime_verification", event)

    transition = record_runtime_verification_dispatch(
        contract=contract,
        registry=registry,
        receipt=receipt,
    )
    active_receipt = transition.receipt
    if transition.changed:
        gh.upsert_json_file(
            receipt_path,
            active_receipt.canonical_dict(),
            message=f"runtime: watchdog dispatched {active_receipt.verification_id}",
        )

    if remote.status != "MERGED":
        merged_remote = RemoteExecutionReceipt(
            task_id=remote.task_id,
            target_repository=remote.target_repository,
            pull_request_url=remote.pull_request_url,
            recorded_at=now.astimezone(UTC).isoformat(),
            status="MERGED",
        )
        gh.upsert_json_file(
            REMOTE_PATH,
            merged_remote.to_dict(),
            message=f"remote: watchdog reconciled merge {remote.task_id}",
        )

    return _result(
        "DISPATCHED",
        reason,
        task_id=receipt.task_id,
        verification_id=receipt.verification_id,
        target_repository=receipt.target_repository,
        source_sha=receipt.source_sha,
        pull_request_number=remote.pull_request_number,
        dispatch_count=active_receipt.dispatch_count,
    )


def _target_client(repository: str, token: str) -> GitHubClient:
    return GitHubClient(repository=repository, token=token)


def main() -> int:
    try:
        gh = GitHubClient()
        target_token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "")
        result = run_watchdog(
            gh=gh,
            target_client_factory=_target_client,
            target_token=target_token,
            run_id=_positive_run_id(os.environ.get("GITHUB_RUN_ID", "")),
            now=datetime.now(UTC),
        )
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        result = _result(
            "FAILED",
            "runtime-verification-watchdog-error",
            error=str(exc).splitlines()[0][:256],
        )
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
