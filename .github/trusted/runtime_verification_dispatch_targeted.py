from __future__ import annotations

import json
import os
from pathlib import Path

from ade_pr_gate import advance_queue
from github_client import GitHubClient
import runtime_verification_dispatch as base_dispatch
from sparse_runtime_workspace import prepare_sparse_repository_runtime_workspace
from target_runtime_profile import (
    build_runtime_probe_registry,
    is_chu_kei_candidate_path,
    is_chu_kei_plan_detection_repository,
)


_BASE_PREPARE_WORKSPACE = base_dispatch.prepare_repository_runtime_workspace
_BASE_RECONCILE = base_dispatch._reconcile_autonomous_development_success


def _event_task_id() -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    client_payload = payload.get("client_payload") if isinstance(payload, dict) else None
    task_id = client_payload.get("task_id") if isinstance(client_payload, dict) else None
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("runtime dispatch task_id is required")
    return task_id


def _task_allowed_paths(gh: GitHubClient, task_id: str) -> tuple[str, ...]:
    payload, _ = gh.get_json_file(".autodev/accepted-plan.json")
    plan = payload.get("plan")
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("accepted plan tasks are unavailable")
    for task in tasks:
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            continue
        raw = task.get("allowed_paths")
        if not isinstance(raw, list) or not raw:
            raise ValueError("accepted plan task has no allowed paths")
        paths = tuple(str(path) for path in raw)
        if any(not is_chu_kei_candidate_path(path) for path in paths):
            raise ValueError(
                "Chu-kei sparse runtime task contains an untrusted path"
            )
        return paths
    raise ValueError("runtime task is absent from accepted plan")


def prepare_target_runtime_workspace(contract):
    if not is_chu_kei_plan_detection_repository(contract.target_repository):
        return _BASE_PREPARE_WORKSPACE(contract)
    gh = GitHubClient()
    paths = _task_allowed_paths(gh, _event_task_id())
    return prepare_sparse_repository_runtime_workspace(
        contract,
        paths=paths,
    )


def _clear_recovered_runtime_metadata(gh: GitHubClient, task_id: str) -> None:
    state, state_sha = gh.get_json_file(".autodev/state.json")
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return
    if metadata.get("runtime_verification_id") is None:
        return
    next_metadata = dict(metadata)
    changed = False
    for key in (
        "recovery_action",
        "recovery_failure",
        "runtime_verification_failure_fingerprint",
    ):
        if key in next_metadata:
            next_metadata.pop(key, None)
            changed = True
    if next_metadata.get("next_required_human_action") is not None:
        next_metadata["next_required_human_action"] = None
        changed = True
    if not changed:
        return
    next_state = dict(state)
    next_state["metadata"] = next_metadata
    gh.put_json_file(
        ".autodev/state.json",
        next_state,
        sha=state_sha,
        message=f"state: clear recovered runtime wait {task_id}",
    )


def reconcile_verified_task(gh: GitHubClient, *, receipt):
    if receipt.status == "VERIFIED":
        campaign, _ = gh.get_json_file(".autodev/campaign.json")
        task_ids = campaign.get("task_ids")
        completed = campaign.get("completed_task_ids")
        if (
            isinstance(task_ids, list)
            and receipt.task_id in task_ids
            and isinstance(completed, list)
            and receipt.task_id not in completed
        ):
            # The normal remote-monitor path advances the queue immediately
            # after merge. If that monitor crashed after arming Runtime
            # Verification, recover the lost queue transition exactly once,
            # but only after Runtime Verification has now succeeded.
            advance_queue(
                gh,
                completed_task_id=receipt.task_id,
            )
            _clear_recovered_runtime_metadata(
                gh,
                receipt.task_id,
            )
    return _BASE_RECONCILE(
        gh,
        receipt=receipt,
    )


def main() -> int:
    base_dispatch.build_runtime_probe_registry = build_runtime_probe_registry
    base_dispatch.prepare_repository_runtime_workspace = prepare_target_runtime_workspace
    base_dispatch._reconcile_autonomous_development_success = reconcile_verified_task
    return base_dispatch.main()


if __name__ == "__main__":
    raise SystemExit(main())
