from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_goal import BacklogPlanningPolicy
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.improvement_bridge import build_improvement_memory_backlog_bridge
from ade.improvement_goal_handoff import (
    ImprovementCyclePolicy,
    arm_improvement_planning_goal_handoff,
    record_improvement_planning_goal_handoff,
)
from ade.improvement_lineage_feedback import (
    build_verified_improvement_lineage_retirement,
)
from ade.improvement_observability import (
    ImprovementCycleViewState,
    build_improvement_observability_snapshot,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import (
    ImprovementResolutionState,
    resolve_improvement_signals,
)
from github_client import GitHubClient, GitHubError
from v1_9_improvement_successor import (
    BACKLOG_HANDOFF_PATH,
    BACKLOG_PATH,
    BACKLOG_POLICY_PATH,
    BACKLOG_RESOLUTION_PATH,
    BACKLOG_SELECTION_PATH,
    BRIDGE_PATH,
    GOAL_RECEIPT_PATH,
    MISSION_CONTROL_PATH,
    PROOF_ID,
    PROOF_MISSION_CONTROL_PATH,
    PROOF_PLANNING_GOAL_PATH,
    PROOF_SOURCE_FINALIZATION_PATH,
    PROOF_SOURCE_RELEASE_PATH,
    PROOF_SOURCE_TARGET_PATH,
    RELEASE_CANDIDATE_ID,
    RESOLUTION_PATH,
    SIGNAL_LEDGER_PATH,
    SOURCE_SHA,
    TARGET_REPOSITORY,
    TELEMETRY_GAP_PATH,
    TELEMETRY_OBSERVATION_PATH,
    build_activation,
)


TASK_ID = "v19proof-63f46f6d8c-001"
TARGET_PULL_REQUEST = 23
TARGET_HEAD_SHA = "4057ebca5c4405573ae73300d03b208edf95ca62"
TARGET_MERGE_SHA = "fa4f4b3a87f78d2bea596177811247072bca37ce"
TARGET_CI_RUN_ID = 37003361924
TARGET_CI_WORKFLOW_NAME = "Phase 1 and 2 checks"

STATE_PATH = Path(".autodev/state.json")
CAMPAIGN_PATH = Path(".autodev/campaign.json")
REMOTE_PATH = Path(".autodev/runtime/remote-execution.json")
RUNTIME_DIR = Path(".autodev/runtime-verification") / TASK_ID
RUNTIME_CONTRACT_PATH = RUNTIME_DIR / "contract.json"
RUNTIME_RECEIPT_PATH = RUNTIME_DIR / "receipt.json"
RUNTIME_REPORT_PATH = RUNTIME_DIR / "report.json"
RUNTIME_PROVENANCE_PATH = RUNTIME_DIR / "provenance.json"

FINAL_DIR = Path(".autodev/improvement/proof/final")
CAMPAIGN_EVIDENCE_PATH = Path(
    ".autodev/campaign-evidence/"
    "v1.9-continuous-improvement-proof-001.json"
)
RESULT_PATH = Path(
    ".autodev/runtime/v1-9-improvement-finalize-result.json"
)


def _load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_local(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_result(payload: dict[str, Any]) -> None:
    _write_local(RESULT_PATH, payload)


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
        raise ValueError(
            f"immutable v1.9 final proof artifact drift: {path}"
        )


def _api_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ADE-v1.9-Improvement-Finalizer/1.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(
            f"GitHub HTTP {exc.code}: {detail[:400]}"
        ) from exc
    except URLError as exc:
        raise ValueError(
            f"GitHub network error: {exc.reason}"
        ) from exc
    return json.loads(raw.decode("utf-8"))


def _target_url(path: str) -> str:
    return (
        "https://api.github.com/repos/"
        + TARGET_REPOSITORY
        + path
    )


def _proof_policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="v19proof",
        min_tasks=1,
        max_tasks=1,
    )


def _assert_equal(
    actual: object,
    expected: object,
    *,
    label: str,
) -> None:
    if actual != expected:
        raise ValueError(
            f"v1.9 proof reconstruction drift: {label}"
        )


def _validate_target(
    api_get: Callable[[str], Any],
) -> dict[str, Any]:
    pr = api_get(
        _target_url(f"/pulls/{TARGET_PULL_REQUEST}")
    )
    files = api_get(
        _target_url(
            f"/pulls/{TARGET_PULL_REQUEST}/files?per_page=100"
        )
    )
    ci = api_get(
        _target_url(f"/actions/runs/{TARGET_CI_RUN_ID}")
    )
    if (
        not isinstance(pr, dict)
        or pr.get("number") != TARGET_PULL_REQUEST
        or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or pr.get("merge_commit_sha") != TARGET_MERGE_SHA
        or not isinstance(pr.get("head"), dict)
        or pr["head"].get("sha") != TARGET_HEAD_SHA
        or not isinstance(pr.get("base"), dict)
        or pr["base"].get("sha") != SOURCE_SHA
        or pr["base"].get("ref") != "main"
    ):
        raise ValueError(
            "v1.9 target pull request identity drift"
        )
    if not isinstance(files, list):
        raise ValueError("v1.9 target pull request files invalid")
    changed_paths = sorted(
        row.get("filename")
        for row in files
        if isinstance(row, dict)
        and isinstance(row.get("filename"), str)
    )
    if changed_paths != ["tests/test_models.py"]:
        raise ValueError(
            "v1.9 target proof changed paths outside tests/test_models.py"
        )
    if (
        not isinstance(ci, dict)
        or ci.get("id") != TARGET_CI_RUN_ID
        or ci.get("name") != TARGET_CI_WORKFLOW_NAME
        or ci.get("event") != "pull_request"
        or ci.get("status") != "completed"
        or ci.get("conclusion") != "success"
        or ci.get("head_sha") != TARGET_HEAD_SHA
    ):
        raise ValueError("v1.9 target CI evidence drift")
    return {
        "schema_version": 1,
        "pull_request": TARGET_PULL_REQUEST,
        "title": pr.get("title"),
        "base_sha": SOURCE_SHA,
        "head_sha": TARGET_HEAD_SHA,
        "merge_sha": TARGET_MERGE_SHA,
        "merged_at": pr.get("merged_at"),
        "changed_paths": changed_paths,
        "target_ci_run_id": TARGET_CI_RUN_ID,
        "target_ci_workflow_name": ci.get("name"),
        "target_ci_event": ci.get("event"),
        "target_ci_head_branch": ci.get("head_branch"),
        "target_ci_head_sha": ci.get("head_sha"),
        "target_ci_created_at": ci.get("created_at"),
        "target_ci_updated_at": ci.get("updated_at"),
        "target_ci_conclusion": ci.get("conclusion"),
    }


def build_final_proof(
    *,
    api_get: Callable[[str], Any] = _api_json,
    terminal_state_payload: dict[str, Any] | None = None,
    campaign_payload: dict[str, Any] | None = None,
    remote_payload: dict[str, Any] | None = None,
    runtime_contract_payload: dict[str, Any] | None = None,
    runtime_receipt_payload: dict[str, Any] | None = None,
    runtime_report_payload: dict[str, Any] | None = None,
    runtime_provenance_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    terminal_state = (
        terminal_state_payload
        if terminal_state_payload is not None
        else _load_json(STATE_PATH)
    )
    campaign = (
        campaign_payload
        if campaign_payload is not None
        else _load_json(CAMPAIGN_PATH)
    )
    remote = (
        remote_payload
        if remote_payload is not None
        else _load_json(REMOTE_PATH)
    )
    runtime_contract = (
        runtime_contract_payload
        if runtime_contract_payload is not None
        else _load_json(RUNTIME_CONTRACT_PATH)
    )
    runtime_receipt = (
        runtime_receipt_payload
        if runtime_receipt_payload is not None
        else _load_json(RUNTIME_RECEIPT_PATH)
    )
    runtime_report = (
        runtime_report_payload
        if runtime_report_payload is not None
        else _load_json(RUNTIME_REPORT_PATH)
    )
    runtime_provenance = (
        runtime_provenance_payload
        if runtime_provenance_payload is not None
        else _load_json(RUNTIME_PROVENANCE_PATH)
    )

    source_release = _load_json(PROOF_SOURCE_RELEASE_PATH)
    source_finalization = _load_json(
        PROOF_SOURCE_FINALIZATION_PATH
    )
    source_target = _load_json(PROOF_SOURCE_TARGET_PATH)
    rebuilt = build_activation(
        state_payload=terminal_state,
        source_release_payload=source_release,
        source_finalization_payload=source_finalization,
        source_target_payload=source_target,
    )

    frozen_mapping = {
        TELEMETRY_OBSERVATION_PATH: rebuilt[
            "telemetry_observation"
        ],
        TELEMETRY_GAP_PATH: rebuilt["telemetry_gap"],
        SIGNAL_LEDGER_PATH: rebuilt["ledger"],
        RESOLUTION_PATH: rebuilt["resolution"],
        BRIDGE_PATH: rebuilt["bridge"],
        BACKLOG_PATH: rebuilt["backlog"],
        BACKLOG_RESOLUTION_PATH: rebuilt[
            "backlog_resolution"
        ],
        BACKLOG_SELECTION_PATH: rebuilt["selection"],
        BACKLOG_POLICY_PATH: rebuilt["policy"],
        BACKLOG_HANDOFF_PATH: rebuilt["handoff"],
        GOAL_RECEIPT_PATH: rebuilt["goal_receipt"],
        PROOF_PLANNING_GOAL_PATH: rebuilt["planning_goal"],
        PROOF_MISSION_CONTROL_PATH: rebuilt["mission_control"],
    }
    for path, expected in frozen_mapping.items():
        _assert_equal(
            _load_json(path),
            expected,
            label=path,
        )

    ledger = ImprovementSignalLedger.from_dict(
        rebuilt["ledger"]
    )
    resolution = resolve_improvement_signals(ledger)
    _assert_equal(
        resolution.canonical_dict(),
        rebuilt["resolution"],
        label="trusted improvement resolution",
    )
    bridge = build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=resolution,
        signal_id=rebuilt["actionable_signal_id"],
        signal_path=SIGNAL_LEDGER_PATH,
        resolution_path=RESOLUTION_PATH,
    )
    _assert_equal(
        bridge.canonical_dict(),
        rebuilt["bridge"],
        label="Memory/Backlog bridge",
    )

    backlog = AutonomousBacklog.from_dict(
        rebuilt["backlog"]
    )
    backlog_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: SOURCE_SHA},
    )
    _assert_equal(
        backlog_resolution.canonical_dict(),
        rebuilt["backlog_resolution"],
        label="Backlog resolution",
    )
    selection = select_next_backlog_candidate(
        backlog,
        backlog_resolution,
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
    )
    _assert_equal(
        selection.canonical_dict(),
        rebuilt["selection"],
        label="Backlog selection",
    )
    policy = _proof_policy()
    _assert_equal(
        policy.canonical_dict(),
        rebuilt["policy"],
        label="Backlog planning policy",
    )
    planning_activation = arm_improvement_planning_goal_handoff(
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
    goal_receipt = record_improvement_planning_goal_handoff(
        planning_activation
    )
    backlog_handoff = planning_activation.backlog_handoff
    _assert_equal(
        backlog_handoff.canonical_dict(),
        rebuilt["handoff"],
        label="Backlog Goal handoff",
    )
    _assert_equal(
        goal_receipt.canonical_dict(),
        rebuilt["goal_receipt"],
        label="improvement Goal receipt",
    )

    if (
        campaign.get("campaign_id") != rebuilt["campaign_id"]
        or campaign.get("status") != "COMPLETED"
        or campaign.get("task_ids") != [TASK_ID]
        or campaign.get("completed_task_ids") != [TASK_ID]
    ):
        raise ValueError("v1.9 proof Campaign is not cleanly COMPLETED")
    if (
        terminal_state.get("status") != "READY"
        or terminal_state.get("current_task_id") is not None
        or terminal_state.get("failed_task_ids") != []
        or TASK_ID not in terminal_state.get(
            "completed_task_ids",
            [],
        )
    ):
        raise ValueError(
            "v1.9 proof ProjectState is not cleanly terminal"
        )
    if (
        remote.get("status") != "MERGED"
        or remote.get("task_id") != TASK_ID
        or remote.get("target_repository") != TARGET_REPOSITORY
        or remote.get("pull_request_url")
        != (
            "https://github.com/"
            + TARGET_REPOSITORY
            + f"/pull/{TARGET_PULL_REQUEST}"
        )
    ):
        raise ValueError("v1.9 remote execution evidence drift")
    if (
        runtime_contract.get("source_sha") != TARGET_MERGE_SHA
        or runtime_contract.get("target_repository")
        != TARGET_REPOSITORY
        or runtime_receipt.get("status") != "VERIFIED"
        or runtime_receipt.get("dispatch_count") != 1
        or runtime_receipt.get("source_sha") != TARGET_MERGE_SHA
        or runtime_receipt.get("task_id") != TASK_ID
        or runtime_report.get("report", {}).get("disposition")
        != "VERIFIED"
        or runtime_report.get("report", {}).get("source_sha")
        != TARGET_MERGE_SHA
    ):
        raise ValueError(
            "v1.9 Runtime Verification evidence is not exact VERIFIED evidence"
        )

    target = _validate_target(api_get)
    if target["merge_sha"] != runtime_contract["source_sha"]:
        raise ValueError(
            "v1.9 target merge does not bind Runtime Verification"
        )
    if (
        runtime_provenance.get("task_id") != TASK_ID
        or runtime_provenance.get("pull_request_number")
        != TARGET_PULL_REQUEST
        or runtime_provenance.get("pull_request_head_sha")
        != TARGET_HEAD_SHA
        or runtime_provenance.get("trusted_merge_sha")
        != TARGET_MERGE_SHA
        or runtime_provenance.get("workspace_source_sha")
        != TARGET_MERGE_SHA
        or runtime_provenance.get("verification_id")
        != runtime_receipt.get("verification_id")
        or runtime_provenance.get("report_fingerprint")
        != runtime_report.get("report_fingerprint")
    ):
        raise ValueError(
            "v1.9 Runtime Verification provenance drift"
        )

    retirement, backlog_retirement = (
        build_verified_improvement_lineage_retirement(
            ledger=ledger,
            bridge=bridge,
            goal_receipt=goal_receipt,
            backlog=backlog,
            backlog_handoff=backlog_handoff,
            campaign_payload=campaign,
            state_payload=terminal_state,
            remote_execution_payload=remote,
            runtime_contract_payload=runtime_contract,
            runtime_receipt_payload=runtime_receipt,
            runtime_report_wrapper_payload=runtime_report,
            bridge_path=BRIDGE_PATH,
            goal_receipt_path=GOAL_RECEIPT_PATH,
            backlog_handoff_path=BACKLOG_HANDOFF_PATH,
            campaign_path=".autodev/improvement/proof/final/terminal-campaign.json",
            state_path=".autodev/improvement/proof/final/terminal-state.json",
            remote_execution_path=".autodev/improvement/proof/final/remote-execution.json",
            runtime_contract_path=".autodev/improvement/proof/final/runtime-contract.json",
            runtime_receipt_path=".autodev/improvement/proof/final/runtime-receipt.json",
            runtime_report_path=".autodev/improvement/proof/final/runtime-report.json",
            backlog_retirement_path=".autodev/improvement/proof/final/backlog-retirement.json",
        )
    )

    post_resolution = resolve_improvement_signals(
        ledger,
        retirements=(retirement,),
    )
    actionable_entry = post_resolution.entry_for(
        rebuilt["actionable_signal_id"]
    )
    observation_entry = post_resolution.entry_for(
        rebuilt["observation_signal_id"]
    )
    if (
        actionable_entry.state
        is not ImprovementResolutionState.RETIRED
        or observation_entry.state
        is not ImprovementResolutionState.OBSERVATION_ONLY
        or post_resolution.current_signal_ids != ()
    ):
        raise ValueError(
            "v1.9 verified outcome did not close improvement signal loop"
        )

    post_backlog_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={
            TARGET_REPOSITORY: TARGET_MERGE_SHA
        },
        retirements=(backlog_retirement,),
    )
    if (
        post_backlog_resolution.entry_for(
            bridge.backlog_candidate.candidate_id
        ).state
        is not BacklogResolutionState.RETIRED
    ):
        raise ValueError(
            "v1.9 verified outcome did not retire Backlog candidate"
        )
    post_selection = select_next_backlog_candidate(
        backlog,
        post_backlog_resolution,
        repository=TARGET_REPOSITORY,
        source_sha=TARGET_MERGE_SHA,
    )
    if (
        post_selection.selected_candidate_id is not None
        or post_selection.eligible_candidate_ids != ()
    ):
        raise ValueError(
            "v1.9 retired Backlog candidate remained selectable"
        )

    mission = build_improvement_observability_snapshot(
        ledger=ledger,
        resolution=post_resolution,
        release_candidate_id=RELEASE_CANDIDATE_ID,
        goal_receipt=goal_receipt,
        retirements=(retirement,),
    )
    if (
        mission.cycle_state
        is not ImprovementCycleViewState.VERIFIED_RETIRED
        or mission.current_count != 0
        or mission.retired_count != 1
        or mission.observation_only_count != 1
        or mission.lineage_retirement_count != 1
    ):
        raise ValueError(
            "v1.9 post-retirement Mission Control projection drift"
        )

    external_provenance = {
        "schema_version": 1,
        "proof_id": PROOF_ID,
        "target": target,
        "runtime_provenance": runtime_provenance,
        "human_authored_per_task_work_items": False,
        "manual_campaign_progress_after_goal_submission": False,
        "execution_provenance_clean": True,
    }
    campaign_evidence = {
        "schema_version": 1,
        "version": "v1.9",
        "proof_id": PROOF_ID,
        "target_repository": TARGET_REPOSITORY,
        "source_release_candidate_id": RELEASE_CANDIDATE_ID,
        "source_release_sha": SOURCE_SHA,
        "observation_signal_id": rebuilt[
            "observation_signal_id"
        ],
        "actionable_signal_id": rebuilt[
            "actionable_signal_id"
        ],
        "planning": {
            "request_id": rebuilt["request_id"],
            "campaign_id": rebuilt["campaign_id"],
            "planning_request_fingerprint": rebuilt[
                "planning_request_fingerprint"
            ],
            "goal_receipt_fingerprint": rebuilt[
                "goal_receipt_fingerprint"
            ],
            "tests_only": True,
            "max_tasks": 1,
        },
        "execution": {
            "task_id": TASK_ID,
            "pull_request": TARGET_PULL_REQUEST,
            "head_sha": TARGET_HEAD_SHA,
            "merge_sha": TARGET_MERGE_SHA,
            "changed_paths": target["changed_paths"],
            "target_ci_run_id": TARGET_CI_RUN_ID,
        },
        "runtime_verification": {
            "verification_id": runtime_receipt[
                "verification_id"
            ],
            "workflow_run_id": runtime_provenance.get(
                "runtime_workflow_run_id"
            ),
            "remote_monitor_workflow_run_id": (
                runtime_provenance.get(
                    "remote_monitor_workflow_run_id"
                )
            ),
            "report_fingerprint": runtime_report[
                "report_fingerprint"
            ],
            "disposition": "VERIFIED",
        },
        "closure": {
            "lineage_retirement_id": retirement.retirement_id,
            "lineage_retirement_fingerprint": (
                retirement.fingerprint()
            ),
            "backlog_retirement_id": (
                backlog_retirement.retirement_id
            ),
            "backlog_retirement_fingerprint": (
                backlog_retirement.fingerprint()
            ),
            "post_resolution_fingerprint": (
                post_resolution.fingerprint()
            ),
            "post_backlog_resolution_fingerprint": (
                post_backlog_resolution.fingerprint()
            ),
            "post_selection_fingerprint": (
                post_selection.fingerprint()
            ),
            "cycle_state": mission.cycle_state.value,
            "current_signal_count": mission.current_count,
            "retired_signal_count": mission.retired_count,
            "lineage_retirement_count": (
                mission.lineage_retirement_count
            ),
        },
        "human_authored_per_task_work_items": False,
        "manual_campaign_progress_after_goal_submission": False,
        "execution_provenance_clean": True,
        "closed_loop_verified": True,
    }

    return {
        "terminal_state": terminal_state,
        "terminal_campaign": campaign,
        "remote_execution": remote,
        "runtime_contract": runtime_contract,
        "runtime_receipt": runtime_receipt,
        "runtime_report": runtime_report,
        "runtime_provenance": runtime_provenance,
        "external_provenance": external_provenance,
        "lineage_retirement": retirement.canonical_dict(),
        "backlog_retirement": backlog_retirement.canonical_dict(),
        "post_resolution": post_resolution.canonical_dict(),
        "post_backlog_resolution": (
            post_backlog_resolution.canonical_dict()
        ),
        "post_backlog_selection": post_selection.canonical_dict(),
        "mission_control": mission.canonical_dict(),
        "campaign_evidence": campaign_evidence,
    }


def main() -> int:
    try:
        local_state = _load_json(STATE_PATH)
        metadata = local_state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("v1_9_graduated") is True:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-already-graduated",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0
        if metadata.get("v1_9_proof_001_verified") is True:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-proof001-already-verified",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0
        if metadata.get("v1_9_proof_001_armed") is not True:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-proof001-not-armed",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0
        if not RUNTIME_PROVENANCE_PATH.exists():
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.9-runtime-provenance-not-ready",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        bundle = build_final_proof()
        gh = GitHubClient()

        artifacts = {
            "terminal-state.json": bundle["terminal_state"],
            "terminal-campaign.json": bundle[
                "terminal_campaign"
            ],
            "remote-execution.json": bundle[
                "remote_execution"
            ],
            "runtime-contract.json": bundle[
                "runtime_contract"
            ],
            "runtime-receipt.json": bundle[
                "runtime_receipt"
            ],
            "runtime-report.json": bundle["runtime_report"],
            "runtime-provenance.json": bundle[
                "runtime_provenance"
            ],
            "external-provenance.json": bundle[
                "external_provenance"
            ],
            "lineage-retirement.json": bundle[
                "lineage_retirement"
            ],
            "backlog-retirement.json": bundle[
                "backlog_retirement"
            ],
            "post-resolution.json": bundle[
                "post_resolution"
            ],
            "post-backlog-resolution.json": bundle[
                "post_backlog_resolution"
            ],
            "post-backlog-selection.json": bundle[
                "post_backlog_selection"
            ],
            "mission-control.json": bundle["mission_control"],
            "campaign-evidence.json": bundle[
                "campaign_evidence"
            ],
        }
        for filename, payload in artifacts.items():
            _write_once_json(
                gh,
                str(FINAL_DIR / filename),
                payload,
                message=(
                    "v1.9: freeze final improvement proof "
                    + filename
                ),
            )

        _write_once_json(
            gh,
            str(CAMPAIGN_EVIDENCE_PATH),
            bundle["campaign_evidence"],
            message=(
                "v1.9: freeze Continuous Improvement campaign evidence"
            ),
        )
        gh.upsert_json_file(
            str(MISSION_CONTROL_PATH),
            bundle["mission_control"],
            message=(
                "v1.9: publish verified-retired Mission Control"
            ),
        )

        workflow_run_id = int(
            os.environ.get("GITHUB_RUN_ID", "0")
        )
        finalizer_provenance = {
            "schema_version": 1,
            "proof_id": PROOF_ID,
            "workflow_run_id": workflow_run_id,
            "finalizer_state": "EVIDENCE_FROZEN",
            "target_pull_request": TARGET_PULL_REQUEST,
            "target_merge_sha": TARGET_MERGE_SHA,
            "runtime_workflow_run_id": bundle[
                "runtime_provenance"
            ].get("runtime_workflow_run_id"),
            "lineage_retirement_id": bundle[
                "lineage_retirement"
            ]["retirement_id"],
            "external_write_after_successor_merge": False,
        }
        _write_once_json(
            gh,
            str(FINAL_DIR / "finalization-provenance.json"),
            finalizer_provenance,
            message="v1.9: freeze finalizer provenance",
        )

        next_state = dict(local_state)
        next_metadata = dict(metadata)
        next_metadata.update(
            {
                "phase": "v1.9-continuous-improvement",
                "milestone": "v1.9-proof-001-verified",
                "v1_9_proof_001_verified": True,
                "v1_9_proof_target_pull_request": (
                    TARGET_PULL_REQUEST
                ),
                "v1_9_proof_target_final_sha": (
                    TARGET_MERGE_SHA
                ),
                "v1_9_runtime_verification_id": bundle[
                    "runtime_receipt"
                ]["verification_id"],
                "v1_9_lineage_retirement_id": bundle[
                    "lineage_retirement"
                ]["retirement_id"],
                "v1_9_lineage_retirement_fingerprint": (
                    bundle["campaign_evidence"]["closure"][
                        "lineage_retirement_fingerprint"
                    ]
                ),
                "v1_9_finalizer_workflow_run_id": (
                    workflow_run_id
                ),
                "v1_9_graduation_evidence": str(
                    CAMPAIGN_EVIDENCE_PATH
                ),
                "next_system_action": "v1.9-graduation",
                "next_required_human_action": None,
                "queue_exhausted": True,
            }
        )
        next_state["metadata"] = next_metadata
        next_state["status"] = "READY"
        next_state["current_task_id"] = None
        next_state["failed_task_ids"] = []
        gh.upsert_json_file(
            str(STATE_PATH),
            next_state,
            message="state: verify v1.9 Continuous Improvement proof",
        )

        result = {
            "schema_version": 1,
            "state": "EVIDENCE_FROZEN",
            "proof_id": PROOF_ID,
            "task_id": TASK_ID,
            "pull_request": TARGET_PULL_REQUEST,
            "merge_sha": TARGET_MERGE_SHA,
            "runtime_verification_id": bundle[
                "runtime_receipt"
            ]["verification_id"],
            "lineage_retirement_id": bundle[
                "lineage_retirement"
            ]["retirement_id"],
            "closed_loop_verified": True,
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        GitHubError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": str(exc).splitlines()[0][:256],
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
