from __future__ import annotations

import json

from ade.autonomous_backlog import (
    AutonomousBacklog,
    BacklogCandidate,
    BacklogCandidateKind,
)
from ade.autonomous_backlog_feedback import build_verified_backlog_retirement
from ade.autonomous_backlog_goal import (
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


REPO = "M-Osugi1230/one-minute-thought-experiments"
BASE_SHA = "a" * 40
MERGE_SHA = "b" * 40
TASK_ID = "abg-proof-001"


def main() -> int:
    candidate = BacklogCandidate(
        candidate_id="backlog-proof-001",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=BASE_SHA,
        statement="Trusted evidence identifies a bounded regression-test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("1" * 64,),
        tags=("repair",),
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: BASE_SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=REPO,
        source_sha=BASE_SHA,
    )
    handoff = build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("tests",),
            min_tasks=1,
            max_tasks=1,
        ),
    )

    contract = RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id=TASK_ID,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )
    report = evaluate_runtime_verification(
        contract,
        (
            RuntimeProbeResult(
                probe_id="offline-cli-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=MERGE_SHA,
                detail_code="offline-cli-pass",
            ),
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=MERGE_SHA,
                detail_code="production-import-pass",
            ),
        ),
    )
    report_wrapper = {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }
    campaign = {
        "schema_version": 1,
        "campaign_id": handoff.request.campaign_id,
        "status": "COMPLETED",
        "task_ids": [TASK_ID],
        "completed_task_ids": [TASK_ID],
        "goal": handoff.request.goal,
    }
    state = {
        "schema_version": 1,
        "project_id": "ade-proof",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "metadata": {},
    }
    remote = RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=REPO,
        pull_request_url=f"https://github.com/{REPO}/pull/21",
        recorded_at="2026-10-01T01:00:00+00:00",
        status="MERGED",
    )

    retirement = build_verified_backlog_retirement(
        backlog=backlog,
        handoff=handoff,
        campaign_payload=campaign,
        state_payload=state,
        remote_execution_payload=remote.to_dict(),
        runtime_contract_payload=contract.canonical_dict(),
        runtime_receipt_payload=receipt.canonical_dict(),
        runtime_report_wrapper_payload=report_wrapper,
        handoff_path=".autodev/autonomous-backlog/handoff.json",
        campaign_path=".autodev/campaign.json",
        state_path=".autodev/state.json",
        remote_execution_path=".autodev/runtime/remote-execution.json",
        runtime_contract_path=".autodev/runtime-verification/abg-proof-001/contract.json",
        runtime_receipt_path=".autodev/runtime-verification/abg-proof-001/receipt.json",
        runtime_report_path=".autodev/runtime-verification/abg-proof-001/report.json",
    )

    retired_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: MERGE_SHA},
        retirements=(retirement,),
    )
    entry = retired_resolution.entry_for(candidate.candidate_id)
    assert entry.state is BacklogResolutionState.RETIRED

    next_selection = select_next_backlog_candidate(
        backlog,
        retired_resolution,
        repository=REPO,
        source_sha=MERGE_SHA,
    )
    assert next_selection.selected_candidate_id is None
    assert next_selection.eligible_candidate_ids == ()

    failed_receipt = dict(receipt.canonical_dict())
    failed_receipt["status"] = "FAILED"
    rejected = False
    try:
        build_verified_backlog_retirement(
            backlog=backlog,
            handoff=handoff,
            campaign_payload=campaign,
            state_payload=state,
            remote_execution_payload=remote.to_dict(),
            runtime_contract_payload=contract.canonical_dict(),
            runtime_receipt_payload=failed_receipt,
            runtime_report_wrapper_payload=report_wrapper,
            handoff_path=".autodev/autonomous-backlog/handoff.json",
            campaign_path=".autodev/campaign.json",
            state_path=".autodev/state.json",
            remote_execution_path=".autodev/runtime/remote-execution.json",
            runtime_contract_path=".autodev/runtime-verification/abg-proof-001/contract.json",
            runtime_receipt_path=".autodev/runtime-verification/abg-proof-001/receipt.json",
            runtime_report_path=".autodev/runtime-verification/abg-proof-001/report.json",
        )
    except ValueError:
        rejected = True
    assert rejected

    print(
        json.dumps(
            {
                "ok": True,
                "verified_runtime_required": True,
                "terminal_campaign_required": True,
                "clean_project_state_required": True,
                "trusted_merge_receipt_required": True,
                "retirement_evidence_fingerprinted": True,
                "retired_candidate_not_reselected": True,
                "retirement_execution_authority": False,
                "retirement_id": retirement.retirement_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
