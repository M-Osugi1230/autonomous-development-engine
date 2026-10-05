from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from github_client import GitHubClient
import runtime_verification_dispatch as base_dispatch
from sparse_runtime_workspace import prepare_sparse_repository_runtime_workspace
from target_runtime_profile import (
    build_runtime_probe_registry,
    is_chu_kei_candidate_path,
    is_chu_kei_plan_detection_repository,
)


_BASE_PREPARE_WORKSPACE = base_dispatch.prepare_repository_runtime_workspace


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


def main() -> int:
    base_dispatch.build_runtime_probe_registry = build_runtime_probe_registry
    base_dispatch.prepare_repository_runtime_workspace = prepare_target_runtime_workspace
    return base_dispatch.main()


if __name__ == "__main__":
    raise SystemExit(main())
