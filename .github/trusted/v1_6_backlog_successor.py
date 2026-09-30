from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_extraction import extract_verified_memory_followup_candidate
from ade.autonomous_backlog_goal import BacklogPlanningPolicy, build_planning_goal_handoff
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.development_memory import MemoryKind
from ade.development_memory_store import DevelopmentMemoryStore
from github_client import GitHubClient, GitHubError
from scripts.v1_5_development_memory_audit import audit as audit_v1_5


STATE_PATH = ".autodev/state.json"
STORE_PATH = ".autodev/development-memory.json"
SOURCE_STORE_PATH = ".autodev/autonomous-backlog/source-memory-store.json"
BACKLOG_PATH = ".autodev/autonomous-backlog/backlog.json"
RESOLUTION_PATH = ".autodev/autonomous-backlog/resolution.json"
SELECTION_PATH = ".autodev/autonomous-backlog/selection.json"
POLICY_PATH = ".autodev/autonomous-backlog/policy.json"
HANDOFF_PATH = ".autodev/autonomous-backlog/handoff.json"
PLANNING_GOAL_PATH = ".autodev/planning-goal.json"
RESULT_PATH = Path(".autodev/runtime/v1-6-backlog-successor-result.json")

TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_TASK_ID = "v15mem2-001"
SOURCE_PHASE = "v1.6-autonomous-backlog"


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _proof_policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="abgproof",
        min_tasks=1,
        max_tasks=1,
    )


def build_activation(
    *,
    state_payload: object,
    store_payload: object,
) -> dict[str, Any]:
    if not isinstance(state_payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    if metadata.get("v1_5_graduated") is not True:
        raise ValueError("v1.5 is not graduated")
    if state_payload.get("status") != "READY":
        raise ValueError("ProjectState must be READY")
    if state_payload.get("current_task_id") is not None:
        raise ValueError("ProjectState still has an active task")
    if state_payload.get("failed_task_ids") != []:
        raise ValueError("ProjectState contains failed tasks")

    store = DevelopmentMemoryStore.from_dict(store_payload)
    matches = [
        record
        for record in store.ledger.records
        if record.task_id == SOURCE_TASK_ID
        and record.repository == TARGET_REPOSITORY
        and record.kind is MemoryKind.VERIFIED_OUTCOME
    ]
    if len(matches) != 1:
        raise ValueError(
            "v1.6 proof requires exactly one proof002 VERIFIED_OUTCOME memory record"
        )
    source_record = matches[0]
    required_tags = {"feedback", "runtime", "verified"}
    if not required_tags.issubset(set(source_record.tags)):
        raise ValueError("proof002 memory record lacks trusted runtime verified tags")

    candidate = extract_verified_memory_followup_candidate(
        store_path=SOURCE_STORE_PATH,
        store_payload=store.canonical_dict(),
        memory_id=source_record.memory_id,
        source_phase=SOURCE_PHASE,
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: source_record.source_sha},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=TARGET_REPOSITORY,
        source_sha=source_record.source_sha,
    )
    policy = _proof_policy()
    handoff = build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=policy,
    )

    return {
        "source_store": store.canonical_dict(),
        "source_store_fingerprint": store.fingerprint(),
        "source_memory_id": source_record.memory_id,
        "source_memory_fingerprint": source_record.fingerprint(),
        "source_sha": source_record.source_sha,
        "backlog": backlog.canonical_dict(),
        "backlog_fingerprint": backlog.fingerprint(),
        "resolution": resolution.canonical_dict(),
        "resolution_fingerprint": resolution.fingerprint(),
        "selection": selection.canonical_dict(),
        "selection_fingerprint": selection.fingerprint(),
        "policy": policy.canonical_dict(),
        "policy_fingerprint": policy.fingerprint(),
        "handoff": handoff.canonical_dict(),
        "handoff_fingerprint": handoff.fingerprint(),
        "planning_goal": handoff.request.to_dict(),
        "request_id": handoff.request.request_id,
        "campaign_id": handoff.request.campaign_id,
        "candidate_id": candidate.candidate_id,
        "candidate_fingerprint": candidate.fingerprint(),
    }


def _write_once_json(
    gh: GitHubClient,
    path: str,
    payload: dict[str, Any],
    *,
    message: str,
) -> None:
    try:
        existing, _ = gh.get_json_file(path)
    except GitHubError as exc:
        if "GitHub HTTP 404:" not in str(exc):
            raise
        gh.put_json_file(
            path,
            payload,
            sha=None,
            message=message,
        )
        return
    if existing != payload:
        raise ValueError(f"immutable v1.6 artifact drift: {path}")


def _local_v1_5_graduated(root: Path = Path(".")) -> bool:
    path = root / STATE_PATH
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return metadata.get("v1_5_graduated") is True


def main() -> int:
    try:
        if not _local_v1_5_graduated():
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.5-not-graduated",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        audit_result = audit_v1_5(Path("."))
        if not audit_result.get("v1_5_development_memory_graduated"):
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.5-graduation-audit-not-green",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        gh = GitHubClient()
        state_payload, _ = gh.get_json_file(STATE_PATH)
        metadata = state_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        if (
            metadata.get("phase") == SOURCE_PHASE
            and metadata.get("v1_6_proof_001_armed") is True
        ):
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.6-proof001-already-armed",
                "request_id": metadata.get("planning_request_id"),
                "campaign_id": metadata.get("campaign_id"),
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        store_payload, _ = gh.get_json_file(STORE_PATH)
        activation = build_activation(
            state_payload=state_payload,
            store_payload=store_payload,
        )

        immutable = (
            (SOURCE_STORE_PATH, activation["source_store"], "v1.6: freeze proof source memory store"),
            (BACKLOG_PATH, activation["backlog"], "v1.6: freeze proof backlog"),
            (RESOLUTION_PATH, activation["resolution"], "v1.6: freeze initial backlog resolution"),
            (SELECTION_PATH, activation["selection"], "v1.6: freeze backlog selection"),
            (POLICY_PATH, activation["policy"], "v1.6: freeze backlog planning policy"),
            (HANDOFF_PATH, activation["handoff"], "v1.6: freeze Planner Goal handoff"),
        )
        for path, value, message in immutable:
            _write_once_json(gh, path, value, message=message)

        gh.upsert_json_file(
            PLANNING_GOAL_PATH,
            activation["planning_goal"],
            message="v1.6: activate Autonomous Backlog proof Goal",
        )

        next_state = dict(state_payload)
        next_metadata = dict(metadata)
        next_metadata.update(
            {
                "phase": SOURCE_PHASE,
                "milestone": "v1.6-proof-001-planning",
                "planning_request_id": activation["request_id"],
                "campaign_id": activation["campaign_id"],
                "target_repository": TARGET_REPOSITORY,
                "target_base_branch": "main",
                "v1_6_proof_001_armed": True,
                "v1_6_source_memory_id": activation["source_memory_id"],
                "v1_6_source_memory_fingerprint": activation[
                    "source_memory_fingerprint"
                ],
                "v1_6_source_store_fingerprint": activation[
                    "source_store_fingerprint"
                ],
                "v1_6_backlog_candidate_id": activation["candidate_id"],
                "v1_6_backlog_candidate_fingerprint": activation[
                    "candidate_fingerprint"
                ],
                "v1_6_backlog_fingerprint": activation["backlog_fingerprint"],
                "v1_6_resolution_fingerprint": activation[
                    "resolution_fingerprint"
                ],
                "v1_6_selection_fingerprint": activation[
                    "selection_fingerprint"
                ],
                "v1_6_policy_fingerprint": activation["policy_fingerprint"],
                "v1_6_handoff_fingerprint": activation["handoff_fingerprint"],
                "next_system_action": "autonomous-planner",
                "next_required_human_action": None,
            }
        )
        next_metadata.pop("pause_reason", None)
        next_metadata.pop("resume_after", None)
        next_state["metadata"] = next_metadata
        next_state["status"] = "READY"
        next_state["current_task_id"] = None
        next_state["failed_task_ids"] = []
        gh.upsert_json_file(
            STATE_PATH,
            next_state,
            message="state: arm v1.6 Autonomous Backlog proof001",
        )

        dispatch_state = "DISPATCHED"
        try:
            gh.dispatch(
                "ade_planner_retry",
                {
                    "request_id": activation["request_id"],
                    "campaign_id": activation["campaign_id"],
                    "source": "v1.6-autonomous-backlog-successor",
                },
            )
        except GitHubError:
            dispatch_state = "SCHEDULED_FALLBACK"

        payload = {
            "schema_version": 1,
            "state": "ARMED",
            "reason": "v1.5-graduated-and-proof002-memory-bound",
            "request_id": activation["request_id"],
            "campaign_id": activation["campaign_id"],
            "candidate_id": activation["candidate_id"],
            "source_memory_id": activation["source_memory_id"],
            "source_memory_fingerprint": activation[
                "source_memory_fingerprint"
            ],
            "source_sha": activation["source_sha"],
            "planner_dispatch": dispatch_state,
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    except (GitHubError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": str(exc).splitlines()[0][:256],
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
