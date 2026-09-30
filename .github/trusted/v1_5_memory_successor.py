from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ade.development_memory_successor import (
    BOOTSTRAP_EVIDENCE_PATH,
    BOOTSTRAP_REQUEST_ID,
    CONTRACT_PATH,
    PROOF002_CAMPAIGN_ID,
    PROOF002_REQUEST_ID,
    RECEIPT_PATH,
    REPORT_PATH,
    build_bootstrap_evidence,
    evaluate_v1_5_bootstrap_successor,
    proof002_planning_goal,
)
from github_client import GitHubClient, GitHubError


RESULT_PATH = Path(".autodev/runtime/v1-5-memory-successor-result.json")
STATE_PATH = ".autodev/state.json"
CAMPAIGN_PATH = ".autodev/campaign.json"
PLANNER_EVIDENCE_PATH = (
    ".autodev/planner-evidence/v1.5-development-memory-proof-001.json"
)
REMOTE_EXECUTION_PATH = ".autodev/runtime/remote-execution.json"
MEMORY_STORE_PATH = ".autodev/development-memory.json"
PLANNING_GOAL_PATH = ".autodev/planning-goal.json"


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _optional_json(gh: GitHubClient, path: str) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _result(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": state,
        "reason": reason,
        **extra,
    }


def main() -> int:
    gh = GitHubClient()
    try:
        state_payload, _ = gh.get_json_file(STATE_PATH)
        if not isinstance(state_payload, dict):
            raise ValueError("project state must be a JSON object")
        metadata = state_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        phase = metadata.get("phase")
        if phase != "v1.5-development-memory":
            payload = _result("NOOP", "project-not-in-v1.5-development-memory")
            _write(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        current_request = metadata.get("planning_request_id")
        current_campaign = metadata.get("campaign_id")
        planning_goal = _optional_json(gh, PLANNING_GOAL_PATH)
        goal_request = (
            planning_goal.get("request_id")
            if isinstance(planning_goal, dict)
            else None
        )
        if (
            current_request == PROOF002_REQUEST_ID
            or current_campaign == PROOF002_CAMPAIGN_ID
            or goal_request == PROOF002_REQUEST_ID
        ):
            payload = _result(
                "NOOP",
                "proof002-already-armed-or-active",
                request_id=PROOF002_REQUEST_ID,
            )
            _write(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        if current_request != BOOTSTRAP_REQUEST_ID:
            payload = _result(
                "NOOP",
                "bootstrap-request-not-current",
                current_request_id=current_request,
            )
            _write(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        required_paths = {
            CAMPAIGN_PATH: _optional_json(gh, CAMPAIGN_PATH),
            PLANNER_EVIDENCE_PATH: _optional_json(gh, PLANNER_EVIDENCE_PATH),
            REMOTE_EXECUTION_PATH: _optional_json(gh, REMOTE_EXECUTION_PATH),
            CONTRACT_PATH: _optional_json(gh, CONTRACT_PATH),
            RECEIPT_PATH: _optional_json(gh, RECEIPT_PATH),
            REPORT_PATH: _optional_json(gh, REPORT_PATH),
            MEMORY_STORE_PATH: _optional_json(gh, MEMORY_STORE_PATH),
        }
        missing = sorted(
            path for path, payload in required_paths.items() if payload is None
        )
        if missing:
            payload = _result(
                "NOOP",
                "bootstrap-evidence-not-ready",
                missing_paths=missing,
            )
            _write(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=state_payload,
            campaign_payload=required_paths[CAMPAIGN_PATH],
            planner_evidence_payload=required_paths[PLANNER_EVIDENCE_PATH],
            remote_execution_payload=required_paths[REMOTE_EXECUTION_PATH],
            contract_payload=required_paths[CONTRACT_PATH],
            receipt_payload=required_paths[RECEIPT_PATH],
            report_wrapper_payload=required_paths[REPORT_PATH],
            memory_store_payload=required_paths[MEMORY_STORE_PATH],
        )
        if not decision.eligible:
            payload = _result(
                "NOOP",
                "bootstrap-not-eligible",
                decision=decision.canonical_dict(),
            )
            _write(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        bootstrap_evidence = build_bootstrap_evidence(
            decision=decision,
            planner_evidence_payload=required_paths[PLANNER_EVIDENCE_PATH],
            remote_execution_payload=required_paths[REMOTE_EXECUTION_PATH],
            receipt_payload=required_paths[RECEIPT_PATH],
        )
        gh.upsert_json_file(
            BOOTSTRAP_EVIDENCE_PATH,
            bootstrap_evidence,
            message="v1.5: freeze bootstrap Development Memory proof001",
        )

        next_state = dict(state_payload)
        next_metadata = dict(metadata)
        next_metadata["milestone"] = "v1.5-proof-002-pending"
        next_metadata["next_required_human_action"] = None
        next_metadata["next_system_action"] = "run-v1.5-development-memory-proof-002"
        next_metadata["v1_5_proof_001_bootstrap_complete"] = True
        next_metadata["v1_5_proof_001_bootstrap_evidence"] = BOOTSTRAP_EVIDENCE_PATH
        next_metadata["v1_5_proof_001_memory_id"] = decision.memory_id
        next_metadata["v1_5_proof_001_memory_fingerprint"] = (
            decision.memory_fingerprint
        )
        next_metadata["v1_5_proof_001_store_fingerprint"] = (
            decision.store_fingerprint
        )
        next_metadata["v1_5_proof_002_armed"] = True
        next_metadata.pop("pause_reason", None)
        next_metadata.pop("resume_after", None)
        next_state["metadata"] = next_metadata
        next_state["status"] = "READY"
        next_state["current_task_id"] = None
        next_state["failed_task_ids"] = []
        next_state["updated_at"] = datetime.now(UTC).isoformat()
        gh.upsert_json_file(
            STATE_PATH,
            next_state,
            message="state: arm v1.5 durable-store proof002",
        )

        goal = proof002_planning_goal()
        gh.upsert_json_file(
            PLANNING_GOAL_PATH,
            goal,
            message="v1.5: activate durable-store proof002 goal",
        )

        dispatch_status = "DISPATCHED"
        try:
            gh.dispatch(
                "ade_planner_retry",
                {
                    "request_id": PROOF002_REQUEST_ID,
                    "campaign_id": PROOF002_CAMPAIGN_ID,
                    "source": "development-memory-successor",
                },
            )
        except GitHubError:
            dispatch_status = "SCHEDULED_FALLBACK"

        payload = _result(
            "ARMED",
            "bootstrap-verified-and-proof002-armed",
            request_id=PROOF002_REQUEST_ID,
            campaign_id=PROOF002_CAMPAIGN_ID,
            bootstrap_evidence_path=BOOTSTRAP_EVIDENCE_PATH,
            source_sha=decision.source_sha,
            memory_id=decision.memory_id,
            memory_fingerprint=decision.memory_fingerprint,
            store_fingerprint=decision.store_fingerprint,
            store_record_count=decision.store_record_count,
            planner_dispatch=dispatch_status,
        )
        _write(payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        payload = _result(
            "FAILED",
            str(exc).splitlines()[0][:256],
        )
        _write(payload)
        print(json.dumps(payload, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
