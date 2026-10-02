from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_goal import BacklogPlanningPolicy
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.improvement_bridge import build_improvement_memory_backlog_bridge
from ade.improvement_goal_handoff import (
    ImprovementCyclePolicy,
    arm_improvement_planning_goal_handoff,
    record_improvement_planning_goal_handoff,
)
from ade.improvement_observability import (
    build_improvement_observability_snapshot,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementSignalKind,
)
from ade.improvement_signal_extraction import (
    extract_actionable_release_gap_signal,
    extract_verified_release_followup_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import resolve_improvement_signals
from github_client import GitHubClient, GitHubError


PROOF_ID = "v1.9-continuous-improvement-proof-001"
PHASE = "v1.9-continuous-improvement"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_CANDIDATE_ID = "release-a4cd075b270b6ad434ae2602"
DETAIL_CODE = "variant-unicode-space-coverage-2005-2008"

STATE_PATH = ".autodev/state.json"
LIVE_PLANNING_GOAL_PATH = ".autodev/planning-goal.json"
MISSION_CONTROL_PATH = ".autodev/improvement/mission-control.json"
RESULT_PATH = Path(".autodev/runtime/v1-9-improvement-successor-result.json")

SOURCE_RELEASE_PATH = (
    ".autodev/campaign-evidence/"
    "v1.8-autonomous-release-proof-001.json"
)
SOURCE_FINALIZATION_PATH = (
    ".autodev/release/proof/final/"
    "post-verification-finalization.json"
)
SOURCE_TARGET_PATH = (
    ".autodev/release/proof/final/"
    "post-verification-target.json"
)

PROOF_DIR = ".autodev/improvement/proof"
PROOF_SOURCE_RELEASE_PATH = f"{PROOF_DIR}/source-release-evidence.json"
PROOF_SOURCE_FINALIZATION_PATH = (
    f"{PROOF_DIR}/source-post-verification-finalization.json"
)
PROOF_SOURCE_TARGET_PATH = f"{PROOF_DIR}/source-runtime-target.json"
TELEMETRY_OBSERVATION_PATH = f"{PROOF_DIR}/telemetry-observation.json"
TELEMETRY_GAP_PATH = f"{PROOF_DIR}/telemetry-gap.json"
SIGNAL_LEDGER_PATH = f"{PROOF_DIR}/signal-ledger.json"
RESOLUTION_PATH = f"{PROOF_DIR}/resolution.json"
BRIDGE_PATH = f"{PROOF_DIR}/bridge.json"
BACKLOG_PATH = f"{PROOF_DIR}/backlog.json"
BACKLOG_RESOLUTION_PATH = f"{PROOF_DIR}/backlog-resolution.json"
BACKLOG_SELECTION_PATH = f"{PROOF_DIR}/backlog-selection.json"
BACKLOG_POLICY_PATH = f"{PROOF_DIR}/backlog-policy.json"
BACKLOG_HANDOFF_PATH = f"{PROOF_DIR}/backlog-handoff.json"
GOAL_RECEIPT_PATH = f"{PROOF_DIR}/goal-receipt.json"
PROOF_PLANNING_GOAL_PATH = f"{PROOF_DIR}/planning-goal.json"
PROOF_MISSION_CONTROL_PATH = f"{PROOF_DIR}/mission-control.json"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _load_local(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
        raise ValueError(f"immutable v1.9 proof artifact drift: {path}")


def _proof_policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="v19proof",
        min_tasks=1,
        max_tasks=1,
    )


def _telemetry_observation() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "check_id": "variant-unicode-whitespace-regression-coverage-v1",
        "repository": TARGET_REPOSITORY,
        "source_sha": SOURCE_SHA,
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "release_environment": "preview",
        "observed_gap": {
            "kind": "MISSING_REGRESSION_COVERAGE",
            "function": "normalize_experiment_variant_label",
            "test_path": "tests/test_models.py",
            "missing_codepoints": [
                "U+2005 FOUR-PER-EM SPACE",
                "U+2008 PUNCTUATION SPACE",
            ],
            "application_behavior_change_required": False,
        },
    }


def build_activation(
    *,
    state_payload: object,
    source_release_payload: object,
    source_finalization_payload: object,
    source_target_payload: object,
) -> dict[str, Any]:
    if not isinstance(state_payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    if metadata.get("v1_8_graduated") is not True:
        raise ValueError("v1.8 must be graduated before v1.9 proof")
    if metadata.get("v1_9_slice_007_mission_control_observability") is not True:
        raise ValueError("v1.9 Slice 007 must be complete before real proof")
    if state_payload.get("status") != "READY":
        raise ValueError("ProjectState must be READY")
    if state_payload.get("current_task_id") is not None:
        raise ValueError("ProjectState still has an active task")
    if state_payload.get("failed_task_ids") != []:
        raise ValueError("ProjectState contains failed tasks")

    observation = extract_verified_release_followup_signal(
        campaign_evidence_payload=source_release_payload,
        finalization_payload=source_finalization_payload,
        target_payload=source_target_payload,
        campaign_evidence_path=PROOF_SOURCE_RELEASE_PATH,
        finalization_path=PROOF_SOURCE_FINALIZATION_PATH,
        target_path=PROOF_SOURCE_TARGET_PATH,
    )

    telemetry_observation = _telemetry_observation()
    telemetry_gap = {
        "schema_version": 1,
        "repository": TARGET_REPOSITORY,
        "source_sha": SOURCE_SHA,
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "release_environment": "preview",
        "signal_kind": ImprovementSignalKind.QUALITY_GAP.value,
        "detail_code": DETAIL_CODE,
        "detail_fingerprint": _fingerprint(telemetry_observation),
    }
    actionable = extract_actionable_release_gap_signal(
        campaign_evidence_payload=source_release_payload,
        finalization_payload=source_finalization_payload,
        target_payload=source_target_payload,
        campaign_evidence_path=PROOF_SOURCE_RELEASE_PATH,
        finalization_path=PROOF_SOURCE_FINALIZATION_PATH,
        target_path=PROOF_SOURCE_TARGET_PATH,
        gap_kind=ImprovementSignalKind.QUALITY_GAP,
        gap_evidence_kind=ImprovementEvidenceKind.TELEMETRY,
        gap_evidence_payload=telemetry_gap,
        gap_evidence_path=TELEMETRY_GAP_PATH,
    )
    if "U+2005 FOUR-PER-EM SPACE" not in actionable.statement:
        raise ValueError("trusted semantic detail did not reach ImprovementSignal")
    if "U+2008 PUNCTUATION SPACE" not in actionable.statement:
        raise ValueError("trusted semantic detail did not reach ImprovementSignal")

    ledger = ImprovementSignalLedger(
        signals=(observation, actionable)
    )
    resolution = resolve_improvement_signals(ledger)
    if resolution.current_signal_ids != (actionable.signal_id,):
        raise ValueError("v1.9 proof must resolve exactly one actionable signal")

    bridge = build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=resolution,
        signal_id=actionable.signal_id,
        signal_path=SIGNAL_LEDGER_PATH,
        resolution_path=RESOLUTION_PATH,
    )
    if "U+2005 FOUR-PER-EM SPACE" not in bridge.backlog_candidate.statement:
        raise ValueError("trusted semantic detail did not reach Backlog candidate")

    backlog = AutonomousBacklog(candidates=(bridge.backlog_candidate,))
    backlog_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: SOURCE_SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        backlog_resolution,
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
    )
    policy = _proof_policy()
    activation = arm_improvement_planning_goal_handoff(
        ledger=ledger,
        improvement_resolution=resolution,
        bridge=bridge,
        backlog=backlog,
        backlog_resolution=backlog_resolution,
        selection=selection,
        backlog_policy=policy,
        cycle_index=1,
        cycle_policy=ImprovementCyclePolicy(max_cycles=4),
    )
    if not activation.should_handoff:
        raise ValueError("v1.9 proof PlanningGoal is not armed")
    handoff = activation.backlog_handoff
    if handoff.request.target_repository != TARGET_REPOSITORY:
        raise ValueError("v1.9 proof target repository drift")
    if handoff.request.allowed_path_prefixes != ("tests",):
        raise ValueError("v1.9 proof must remain tests-only")
    if handoff.request.max_tasks != 1:
        raise ValueError("v1.9 proof must remain single-task")

    goal_receipt = record_improvement_planning_goal_handoff(
        activation
    )
    mission = build_improvement_observability_snapshot(
        ledger=ledger,
        resolution=resolution,
        release_candidate_id=RELEASE_CANDIDATE_ID,
        goal_receipt=goal_receipt,
    )

    return {
        "source_release": source_release_payload,
        "source_finalization": source_finalization_payload,
        "source_target": source_target_payload,
        "telemetry_observation": telemetry_observation,
        "telemetry_gap": telemetry_gap,
        "ledger": ledger.canonical_dict(),
        "ledger_fingerprint": ledger.fingerprint(),
        "resolution": resolution.canonical_dict(),
        "resolution_fingerprint": resolution.fingerprint(),
        "observation_signal_id": observation.signal_id,
        "observation_signal_fingerprint": observation.fingerprint(),
        "actionable_signal_id": actionable.signal_id,
        "actionable_signal_fingerprint": actionable.fingerprint(),
        "bridge": bridge.canonical_dict(),
        "bridge_fingerprint": bridge.fingerprint(),
        "memory_record_id": bridge.memory_record.memory_id,
        "backlog": backlog.canonical_dict(),
        "backlog_fingerprint": backlog.fingerprint(),
        "backlog_resolution": backlog_resolution.canonical_dict(),
        "backlog_resolution_fingerprint": backlog_resolution.fingerprint(),
        "selection": selection.canonical_dict(),
        "selection_fingerprint": selection.fingerprint(),
        "policy": policy.canonical_dict(),
        "policy_fingerprint": policy.fingerprint(),
        "handoff": handoff.canonical_dict(),
        "handoff_fingerprint": handoff.fingerprint(),
        "goal_receipt": goal_receipt.canonical_dict(),
        "goal_receipt_fingerprint": goal_receipt.fingerprint(),
        "planning_goal": handoff.request.to_dict(),
        "planning_request_fingerprint": handoff.request.fingerprint(),
        "mission_control": mission.canonical_dict(),
        "request_id": handoff.request.request_id,
        "campaign_id": handoff.request.campaign_id,
        "candidate_id": bridge.backlog_candidate.candidate_id,
        "candidate_fingerprint": bridge.backlog_candidate.fingerprint(),
    }


def main() -> int:
    try:
        local_state = _load_local(STATE_PATH)
        local_metadata = local_state.get("metadata")
        local_metadata = (
            local_metadata if isinstance(local_metadata, dict) else {}
        )
        if local_metadata.get("v1_9_graduated") is True:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-already-graduated",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if local_metadata.get(
            "v1_9_slice_007_mission_control_observability"
        ) is not True:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-slice-007-not-complete",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        gh = GitHubClient()
        state_payload, _ = gh.get_json_file(STATE_PATH)
        metadata = state_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        if metadata.get("v1_9_graduated") is True:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-already-graduated",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if metadata.get("v1_9_proof_001_armed") is True:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-proof001-already-armed",
                "request_id": metadata.get("planning_request_id"),
                "campaign_id": metadata.get("campaign_id"),
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        source_release = _load_local(SOURCE_RELEASE_PATH)
        source_finalization = _load_local(SOURCE_FINALIZATION_PATH)
        source_target = _load_local(SOURCE_TARGET_PATH)
        activation = build_activation(
            state_payload=state_payload,
            source_release_payload=source_release,
            source_finalization_payload=source_finalization,
            source_target_payload=source_target,
        )

        immutable = (
            (PROOF_SOURCE_RELEASE_PATH, activation["source_release"], "v1.9: freeze source release evidence"),
            (PROOF_SOURCE_FINALIZATION_PATH, activation["source_finalization"], "v1.9: freeze source post-verification"),
            (PROOF_SOURCE_TARGET_PATH, activation["source_target"], "v1.9: freeze source runtime target"),
            (TELEMETRY_OBSERVATION_PATH, activation["telemetry_observation"], "v1.9: freeze trusted improvement observation"),
            (TELEMETRY_GAP_PATH, activation["telemetry_gap"], "v1.9: freeze trusted gap envelope"),
            (SIGNAL_LEDGER_PATH, activation["ledger"], "v1.9: freeze ImprovementSignal ledger"),
            (RESOLUTION_PATH, activation["resolution"], "v1.9: freeze improvement resolution"),
            (BRIDGE_PATH, activation["bridge"], "v1.9: freeze Memory Backlog bridge"),
            (BACKLOG_PATH, activation["backlog"], "v1.9: freeze proof Backlog"),
            (BACKLOG_RESOLUTION_PATH, activation["backlog_resolution"], "v1.9: freeze proof Backlog resolution"),
            (BACKLOG_SELECTION_PATH, activation["selection"], "v1.9: freeze proof Backlog selection"),
            (BACKLOG_POLICY_PATH, activation["policy"], "v1.9: freeze proof planning policy"),
            (BACKLOG_HANDOFF_PATH, activation["handoff"], "v1.9: freeze proof Backlog handoff"),
            (GOAL_RECEIPT_PATH, activation["goal_receipt"], "v1.9: freeze proof PlanningGoal receipt"),
            (PROOF_PLANNING_GOAL_PATH, activation["planning_goal"], "v1.9: freeze proof PlanningGoal"),
            (PROOF_MISSION_CONTROL_PATH, activation["mission_control"], "v1.9: freeze proof Mission Control projection"),
        )
        for path, value, message in immutable:
            _write_once_json(gh, path, value, message=message)

        gh.upsert_json_file(
            MISSION_CONTROL_PATH,
            activation["mission_control"],
            message="v1.9: publish Continuous Improvement Mission Control",
        )
        gh.upsert_json_file(
            LIVE_PLANNING_GOAL_PATH,
            activation["planning_goal"],
            message="v1.9: activate Continuous Improvement proof Goal",
        )

        next_state = dict(state_payload)
        next_metadata = dict(metadata)
        next_metadata.update(
            {
                "phase": PHASE,
                "milestone": "v1.9-proof-001-planning",
                "planning_request_id": activation["request_id"],
                "campaign_id": activation["campaign_id"],
                "target_repository": TARGET_REPOSITORY,
                "target_base_branch": "main",
                "v1_9_proof_001_armed": True,
                "v1_9_proof_id": PROOF_ID,
                "v1_9_source_release_candidate_id": RELEASE_CANDIDATE_ID,
                "v1_9_source_release_sha": SOURCE_SHA,
                "v1_9_observation_signal_id": activation["observation_signal_id"],
                "v1_9_observation_signal_fingerprint": activation[
                    "observation_signal_fingerprint"
                ],
                "v1_9_actionable_signal_id": activation["actionable_signal_id"],
                "v1_9_actionable_signal_fingerprint": activation[
                    "actionable_signal_fingerprint"
                ],
                "v1_9_signal_ledger_fingerprint": activation["ledger_fingerprint"],
                "v1_9_resolution_fingerprint": activation["resolution_fingerprint"],
                "v1_9_bridge_fingerprint": activation["bridge_fingerprint"],
                "v1_9_backlog_candidate_id": activation["candidate_id"],
                "v1_9_backlog_candidate_fingerprint": activation[
                    "candidate_fingerprint"
                ],
                "v1_9_backlog_fingerprint": activation["backlog_fingerprint"],
                "v1_9_backlog_resolution_fingerprint": activation[
                    "backlog_resolution_fingerprint"
                ],
                "v1_9_selection_fingerprint": activation["selection_fingerprint"],
                "v1_9_policy_fingerprint": activation["policy_fingerprint"],
                "v1_9_handoff_fingerprint": activation["handoff_fingerprint"],
                "v1_9_goal_receipt_fingerprint": activation[
                    "goal_receipt_fingerprint"
                ],
                "v1_9_planning_request_fingerprint": activation[
                    "planning_request_fingerprint"
                ],
                "next_system_action": "autonomous-planner",
                "next_required_human_action": None,
                "queue_exhausted": False,
            }
        )
        next_state["metadata"] = next_metadata
        next_state["status"] = "READY"
        next_state["current_task_id"] = None
        next_state["failed_task_ids"] = []
        gh.upsert_json_file(
            STATE_PATH,
            next_state,
            message="state: arm v1.9 Continuous Improvement proof001",
        )

        dispatch_state = "DISPATCHED"
        try:
            gh.dispatch(
                "ade_planner_retry",
                {
                    "request_id": activation["request_id"],
                    "campaign_id": activation["campaign_id"],
                    "source": "v1.9-continuous-improvement-successor",
                },
            )
        except GitHubError:
            dispatch_state = "SCHEDULED_FALLBACK"

        payload = {
            "schema_version": 1,
            "state": "ARMED",
            "reason": "verified-release-and-trusted-gap-bound",
            "proof_id": PROOF_ID,
            "request_id": activation["request_id"],
            "campaign_id": activation["campaign_id"],
            "actionable_signal_id": activation["actionable_signal_id"],
            "candidate_id": activation["candidate_id"],
            "source_sha": SOURCE_SHA,
            "detail_code": DETAIL_CODE,
            "planning_goal_tests_only": True,
            "max_tasks": 1,
            "planner_dispatch": dispatch_state,
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (
        GitHubError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
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
