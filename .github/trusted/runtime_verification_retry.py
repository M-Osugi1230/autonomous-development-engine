from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    arm_post_merge_runtime_verification,
    record_runtime_verification_dispatch,
    runtime_verification_paths,
)
from github_client import GitHubClient
from runtime_probes import (
    build_runtime_probe_registry,
    build_runtime_verification_policy,
)


REQUEST_PATH = Path(".autodev/runtime-verification-retry.json")
RESULT_PATH = Path(".autodev/runtime/runtime-verification-retry-result.json")
REMOTE_PATH = ".autodev/runtime/remote-execution.json"
STATE_PATH = ".autodev/state.json"


def _load_request() -> dict[str, Any]:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("retry request must be a JSON object")
    allowed = {"schema_version", "request_id", "task_id", "reason"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown retry request fields: {sorted(unknown)}")
    if payload.get("schema_version") != 1:
        raise ValueError("retry request schema_version must be 1")
    for field in ("request_id", "task_id", "reason"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be non-empty")
    return payload


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_id() -> int:
    value = os.environ.get("GITHUB_RUN_ID", "")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("GITHUB_RUN_ID must be a positive integer")
    return int(value)


def main() -> int:
    try:
        request = _load_request()
        gh = GitHubClient()

        state, _ = gh.get_json_file(STATE_PATH)
        metadata = state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        task_id = request["task_id"]
        if state.get("current_task_id") != task_id:
            raise ValueError("retry task does not match current project task")
        if state.get("status") != "HUMAN_WAIT":
            raise ValueError("runtime retry requires HUMAN_WAIT project state")
        if metadata.get("recovery_failure") != "RUNTIME_VERIFICATION":
            raise ValueError("runtime retry requires runtime-verification recovery state")

        remote_payload, _ = gh.get_json_file(REMOTE_PATH)
        remote = RemoteExecutionReceipt.from_dict(remote_payload)
        if remote.task_id != task_id or remote.status != "MERGED":
            raise ValueError("runtime retry requires merged remote execution receipt")

        contract_path, receipt_path = runtime_verification_paths(task_id)
        receipt_payload, _ = gh.get_json_file(receipt_path)
        existing = RuntimeVerificationReceipt.from_dict(receipt_payload)
        if existing.status not in {"HUMAN_WAIT", "ARMED"}:
            raise ValueError(
                "runtime retry requires HUMAN_WAIT or ARMED verification receipt"
            )
        if existing.target_repository != remote.target_repository:
            raise ValueError("runtime retry repository drift")

        target_token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "").strip()
        if not target_token:
            raise ValueError("ADE_TARGET_GITHUB_TOKEN is required for runtime retry")
        target = GitHubClient(
            repository=remote.target_repository,
            token=target_token,
        )
        pr = target.get_pull_request(remote.pull_request_number)
        if pr.get("merged") is not True or not pr.get("merged_at"):
            raise ValueError("target pull request is not merged")
        head = pr.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        merge_sha = pr.get("merge_commit_sha")
        if not isinstance(head_sha, str) or len(head_sha) != 40:
            raise ValueError("target pull request head SHA is invalid")
        if not isinstance(merge_sha, str) or len(merge_sha) != 40:
            raise ValueError("target pull request merge SHA is invalid")
        if merge_sha != existing.source_sha:
            raise ValueError("runtime retry merge SHA does not match failed verification")

        policy = build_runtime_verification_policy(remote.target_repository)
        registry = build_runtime_probe_registry(
            target_repository=remote.target_repository,
        )
        activation = arm_post_merge_runtime_verification(
            policy=policy,
            registry=registry,
            task_id=task_id,
            target_repository=remote.target_repository,
            trusted_merge_sha=merge_sha,
            existing_receipt=existing,
        )
        if not activation.should_dispatch or activation.receipt.status != "ARMED":
            raise ValueError("updated runtime policy did not produce a retryable contract")

        gh.upsert_json_file(
            contract_path,
            activation.contract.canonical_dict(),
            message=f"runtime: retry contract {activation.contract.verification_id}",
        )
        gh.upsert_json_file(
            receipt_path,
            activation.receipt.canonical_dict(),
            message=f"runtime: retry arm {activation.receipt.verification_id}",
        )

        event = {
            "task_id": task_id,
            "verification_id": activation.receipt.verification_id,
            "target_repository": activation.receipt.target_repository,
            "source_sha": activation.receipt.source_sha,
            "remote_monitor_workflow_run_id": _run_id(),
            "pull_request_number": remote.pull_request_number,
            "pull_request_head_sha": head_sha,
            "trusted_merge_sha": merge_sha,
        }
        gh.dispatch("ade_runtime_verification", event)

        transition = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=registry,
            receipt=activation.receipt,
        )
        if transition.changed:
            gh.upsert_json_file(
                receipt_path,
                transition.receipt.canonical_dict(),
                message=f"runtime: retry dispatched {transition.receipt.verification_id}",
            )

        result = {
            "schema_version": 1,
            "state": "DISPATCHED",
            "request_id": request["request_id"],
            "task_id": task_id,
            "target_repository": remote.target_repository,
            "pull_request_number": remote.pull_request_number,
            "source_sha": merge_sha,
            "verification_id": activation.receipt.verification_id,
            "required_probe_ids": list(policy.required_probe_ids),
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "error": str(exc).splitlines()[0][:256],
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
