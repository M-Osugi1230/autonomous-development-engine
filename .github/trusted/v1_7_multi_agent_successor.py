from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.planning_activation import PlanningGoalRequest
from github_client import GitHubClient, GitHubError


STATE_PATH = ".autodev/state.json"
PLANNING_GOAL_PATH = ".autodev/planning-goal.json"
ACTIVATION_PATH = ".autodev/multi-agent/proof-activation.json"
RESULT_PATH = Path(".autodev/runtime/v1-7-multi-agent-successor-result.json")

TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
PHASE = "v1.7-multi-agent"
REQUEST_ID = "v1.7-multi-agent-proof-001"
CAMPAIGN_ID = "v1.7-multi-agent-campaign-001"
ID_PREFIX = "v17ma1"
V1_6_EVIDENCE = ".autodev/campaign-evidence/v1.6-autonomous-backlog-proof-001.json"
GOAL = (
    "Add one bounded regression test for experiment variant label normalization "
    "covering U+2004 THREE-PER-EM SPACE and U+2006 SIX-PER-EM SPACE. "
    "Do not change application behavior or implementation code."
)


def _canonical_fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_error(exc: BaseException) -> str:
    value = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    return value[:256]


def _optional_json(
    gh: GitHubClient,
    path: str,
) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise
    return payload


def _write_once_json(
    gh: GitHubClient,
    path: str,
    payload: dict[str, Any],
    *,
    message: str,
) -> None:
    current = _optional_json(gh, path)
    if current is None:
        gh.put_json_file(path, payload, sha=None, message=message)
        return
    if current != payload:
        raise RuntimeError(f"immutable v1.7 activation artifact drift: {path}")


def build_activation(*, state_payload: object) -> dict[str, Any]:
    if not isinstance(state_payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    if metadata.get("v1_6_graduated") is not True:
        raise ValueError("v1.6 is not graduated")
    if metadata.get("v1_6_graduation_evidence") != V1_6_EVIDENCE:
        raise ValueError("v1.6 graduation evidence is not the trusted proof001 artifact")
    if metadata.get("v1_6_post_retirement_queue_empty") is not True:
        raise ValueError("v1.6 post-retirement backlog is not empty")
    if metadata.get("milestone") != "v1.6-graduated":
        raise ValueError("ProjectState milestone is not v1.6-graduated")
    if state_payload.get("status") != "READY":
        raise ValueError("ProjectState must be READY")
    if state_payload.get("current_task_id") is not None:
        raise ValueError("ProjectState still has an active task")
    if state_payload.get("failed_task_ids") != []:
        raise ValueError("ProjectState contains failed tasks")

    source_sha = metadata.get("v1_6_proof_target_final_sha")
    if (
        not isinstance(source_sha, str)
        or len(source_sha) != 40
        or any(ch not in "0123456789abcdef" for ch in source_sha)
    ):
        raise ValueError("v1.6 final target SHA is invalid")

    request = PlanningGoalRequest(
        request_id=REQUEST_ID,
        campaign_id=CAMPAIGN_ID,
        id_prefix=ID_PREFIX,
        goal=GOAL,
        target_repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        min_tasks=1,
        max_tasks=1,
    )
    planning_goal = request.to_dict()

    activation = {
        "schema_version": 1,
        "phase": PHASE,
        "request_id": REQUEST_ID,
        "campaign_id": CAMPAIGN_ID,
        "target_repository": TARGET_REPOSITORY,
        "base_branch": "main",
        "planning_goal": planning_goal,
        "planning_goal_fingerprint": request.fingerprint(),
        "source_v1_6_graduation_evidence": V1_6_EVIDENCE,
        "source_v1_6_target_final_sha": source_sha,
        "reviewer_required": True,
        "independent_reviewer_session_required": True,
        "target_merge_gate_authority": True,
        "execution_authority": False,
        "accepted_plan_authority": False,
        "merge_authority": False,
        "auto_dispatch": False,
        "may_expand_scope": False,
    }
    activation["activation_fingerprint"] = _canonical_fingerprint(activation)
    return activation


def _local_v1_6_graduated() -> bool:
    root = Path(__file__).resolve().parents[2]
    path = root / STATE_PATH
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return metadata.get("v1_6_graduated") is True


def main() -> int:
    try:
        if not _local_v1_6_graduated():
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.6-not-graduated",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        gh = GitHubClient()
        state_payload, _ = gh.get_json_file(STATE_PATH)
        activation = build_activation(state_payload=state_payload)
        expected_goal = activation["planning_goal"]

        metadata = state_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        existing_goal = _optional_json(gh, PLANNING_GOAL_PATH)
        if (
            metadata.get("phase") == PHASE
            and metadata.get("v1_7_proof_001_armed") is True
            and existing_goal == expected_goal
        ):
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.7-proof001-already-armed",
                "request_id": REQUEST_ID,
                "campaign_id": CAMPAIGN_ID,
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        _write_once_json(
            gh,
            ACTIVATION_PATH,
            activation,
            message="v1.7: freeze Multi-Agent proof activation",
        )

        next_state = dict(state_payload)
        next_metadata = dict(metadata)
        next_metadata.update(
            {
                "phase": PHASE,
                "milestone": "v1.7-proof-001-planning",
                "planning_request_id": REQUEST_ID,
                "campaign_id": CAMPAIGN_ID,
                "target_repository": TARGET_REPOSITORY,
                "target_base_branch": "main",
                "v1_7_proof_001_armed": True,
                "v1_7_activation_fingerprint": activation[
                    "activation_fingerprint"
                ],
                "v1_7_source_v1_6_graduation_evidence": V1_6_EVIDENCE,
                "v1_7_source_v1_6_target_final_sha": activation[
                    "source_v1_6_target_final_sha"
                ],
                "next_required_human_action": None,
                "next_system_action": "autonomous-planner",
                "queue_exhausted": False,
                "dag_blocked": False,
            }
        )
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
            message="state: arm v1.7 Multi-Agent proof001",
        )
        gh.upsert_json_file(
            PLANNING_GOAL_PATH,
            expected_goal,
            message="v1.7: activate Multi-Agent proof Goal",
        )

        dispatch_state = "DISPATCHED"
        try:
            gh.dispatch(
                "ade_planner_retry",
                {
                    "request_id": REQUEST_ID,
                    "source": "v1.7-multi-agent-successor",
                },
            )
        except GitHubError as exc:
            dispatch_state = "SCHEDULED_FALLBACK"
            print(
                "WARNING: immediate Planner dispatch failed; push/schedule triggers remain armed: "
                + _safe_error(exc),
                file=sys.stderr,
            )

        payload = {
            "schema_version": 1,
            "state": "ARMED",
            "phase": PHASE,
            "request_id": REQUEST_ID,
            "campaign_id": CAMPAIGN_ID,
            "activation_fingerprint": activation["activation_fingerprint"],
            "planner_dispatch": dispatch_state,
            "execution_authority": False,
            "accepted_plan_authority": False,
            "merge_authority": False,
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (
        GitHubError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        payload = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": _safe_error(exc),
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
