from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    arm_post_merge_runtime_verification,
    runtime_verification_paths,
)
from github_client import GitHubClient, GitHubError
from target_runtime_profile import (
    build_runtime_probe_registry,
    build_runtime_verification_policy,
)


RESULT_PATH = Path(
    ".autodev/runtime/runtime-verification-profile-migration.json"
)


def _result(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "state": state,
        "reason": reason,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    payload.update(extra)
    return payload


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _target_client(repository: str, token: str) -> GitHubClient:
    return GitHubClient(repository=repository, token=token)


def migrate_runtime_profile_if_needed(
    *,
    gh: GitHubClient,
    target_token: str,
) -> dict[str, Any]:
    state_payload, state_sha = gh.get_json_file(".autodev/state.json")
    task_id = state_payload.get("current_task_id")
    if not isinstance(task_id, str) or not task_id:
        return _result("NOOP", "no-current-task")

    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if state_payload.get("status") != "HUMAN_WAIT":
        return _result("NOOP", "project-not-human-wait", task_id=task_id)
    if metadata.get("recovery_failure") != "RUNTIME_VERIFICATION":
        return _result(
            "NOOP",
            "human-wait-not-runtime-verification",
            task_id=task_id,
        )

    contract_path, receipt_path = runtime_verification_paths(task_id)
    try:
        raw_receipt, _ = gh.get_json_file(receipt_path)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return _result(
                "NOOP",
                "runtime-receipt-missing",
                task_id=task_id,
            )
        raise
    receipt = RuntimeVerificationReceipt.from_dict(raw_receipt)
    if receipt.status != "HUMAN_WAIT":
        return _result(
            "NOOP",
            "runtime-receipt-not-human-wait",
            task_id=task_id,
            receipt_status=receipt.status,
        )

    remote_payload, _ = gh.get_json_file(
        ".autodev/runtime/remote-execution.json"
    )
    remote = RemoteExecutionReceipt.from_dict(remote_payload)
    if remote.task_id != task_id:
        return _result(
            "NOOP",
            "remote-receipt-not-current",
            task_id=task_id,
        )
    if remote.target_repository != receipt.target_repository:
        raise ValueError("runtime migration target repository drift")
    if not isinstance(target_token, str) or not target_token.strip():
        raise ValueError("ADE_TARGET_GITHUB_TOKEN is required")

    target = _target_client(
        receipt.target_repository,
        target_token.strip(),
    )
    pr = target.get_pull_request(remote.pull_request_number)
    if pr.get("merged") is not True or not pr.get("merged_at"):
        return _result(
            "NOOP",
            "target-pull-request-not-merged",
            task_id=task_id,
        )
    trusted_merge_sha = pr.get("merge_commit_sha")
    if trusted_merge_sha != receipt.source_sha:
        raise ValueError("runtime migration merge SHA drift")

    registry = build_runtime_probe_registry(
        target_repository=receipt.target_repository,
    )
    policy = build_runtime_verification_policy(
        receipt.target_repository
    )
    activation = arm_post_merge_runtime_verification(
        policy=policy,
        registry=registry,
        task_id=task_id,
        target_repository=receipt.target_repository,
        trusted_merge_sha=receipt.source_sha,
        existing_receipt=receipt,
    )

    replacement = activation.receipt
    profile_changed = any(
        (
            replacement.contract_fingerprint
            != receipt.contract_fingerprint,
            replacement.registry_fingerprint
            != receipt.registry_fingerprint,
            replacement.policy_fingerprint
            != receipt.policy_fingerprint,
        )
    )
    if not profile_changed:
        return _result(
            "NOOP",
            "runtime-profile-unchanged",
            task_id=task_id,
            verification_id=receipt.verification_id,
        )
    if replacement.status != "ARMED" or not activation.should_dispatch:
        raise ValueError("runtime profile migration did not produce ARMED receipt")

    gh.upsert_json_file(
        contract_path,
        activation.contract.canonical_dict(),
        message=f"runtime: migrate contract {activation.contract.verification_id}",
    )
    gh.upsert_json_file(
        receipt_path,
        replacement.canonical_dict(),
        message=f"runtime: rearm profile {replacement.verification_id}",
    )

    next_state = dict(state_payload)
    next_metadata = dict(metadata)
    for key in (
        "recovery_action",
        "recovery_failure",
        "runtime_verification_failure_fingerprint",
    ):
        next_metadata.pop(key, None)
    next_metadata.update(
        {
            "runtime_verification_id": replacement.verification_id,
            "runtime_verification_source_sha": replacement.source_sha,
            "next_required_human_action": None,
            "next_system_action": "retry-runtime-verification-after-profile-migration",
        }
    )
    next_state["status"] = "RUNNING"
    next_state["metadata"] = next_metadata
    gh.put_json_file(
        ".autodev/state.json",
        next_state,
        sha=state_sha,
        message=f"state: rearm runtime profile {task_id}",
    )

    campaign, campaign_sha = gh.get_json_file(".autodev/campaign.json")
    if campaign.get("status") == "HUMAN_WAIT":
        next_campaign = dict(campaign)
        next_campaign["status"] = "RUNNING"
        gh.put_json_file(
            ".autodev/campaign.json",
            next_campaign,
            sha=campaign_sha,
            message=f"campaign: rearm runtime profile {task_id}",
        )

    return _result(
        "REARMED",
        "trusted-runtime-profile-changed",
        task_id=task_id,
        verification_id=replacement.verification_id,
        target_repository=replacement.target_repository,
        old_contract_fingerprint=receipt.contract_fingerprint,
        new_contract_fingerprint=replacement.contract_fingerprint,
        old_registry_fingerprint=receipt.registry_fingerprint,
        new_registry_fingerprint=replacement.registry_fingerprint,
        old_policy_fingerprint=receipt.policy_fingerprint,
        new_policy_fingerprint=replacement.policy_fingerprint,
    )


def main() -> int:
    try:
        gh = GitHubClient()
        result = migrate_runtime_profile_if_needed(
            gh=gh,
            target_token=os.environ.get(
                "ADE_TARGET_GITHUB_TOKEN",
                "",
            ),
        )
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        result = _result(
            "FAILED",
            "runtime-profile-migration-error",
            error=str(exc).splitlines()[0][:256],
        )
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
