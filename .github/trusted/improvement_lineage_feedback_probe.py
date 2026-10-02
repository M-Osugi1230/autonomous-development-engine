from __future__ import annotations

import json

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_goal import BacklogPlanningPolicy
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.improvement_bridge import build_improvement_memory_backlog_bridge
from ade.improvement_goal_handoff import (
    arm_improvement_planning_goal_handoff,
    record_improvement_planning_goal_handoff,
)
from ade.improvement_lineage_feedback import (
    build_verified_improvement_lineage_retirement,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import (
    ImprovementResolutionState,
    resolve_improvement_signals,
)
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
RELEASE_ID = "release-v19-feedback-proof"
TASK_ID = "v19-feedback-001"


def signal(seed: str = "a"):
    return build_improvement_signal(
        repository=REPO,
        source_sha=BASE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=ImprovementSignalKind.RUNTIME_GAP,
        statement="Investigate one bounded runtime gap.",
        evidence_refs=(
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path=".autodev/release-evidence.json",
                fingerprint=seed * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.POST_VERIFICATION,
                path=".autodev/post-verification.json",
                fingerprint=("b" if seed != "b" else "c") * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RECOVERY,
                path=".autodev/recovery-evidence.json",
                fingerprint=("c" if seed != "c" else "d") * 64,
            ),
        ),
        tags=("verified-release",),
    )


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke",),
        max_attempts=2,
        timeout_seconds=300,
    )


def report_wrapper():
    value = contract()
    report = evaluate_runtime_verification(
        value,
        (
            RuntimeProbeResult(
                probe_id="offline-cli-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=MERGE_SHA,
                attempt=1,
                detail_code="offline-cli-pass",
            ),
        ),
    )
    return {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1}
        ],
    }


def build(status: str = "VERIFIED"):
    origin = signal()
    ledger = ImprovementSignalLedger(signals=(origin,))
    resolution = resolve_improvement_signals(ledger)
    bridge = build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=resolution,
        signal_id=origin.signal_id,
        signal_path=".autodev/improvement/signal.json",
        resolution_path=".autodev/improvement/resolution.json",
    )
    backlog = AutonomousBacklog(candidates=(bridge.backlog_candidate,))
    backlog_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: BASE_SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        backlog_resolution,
        repository=REPO,
        source_sha=BASE_SHA,
    )
    activation = arm_improvement_planning_goal_handoff(
        ledger=ledger,
        improvement_resolution=resolution,
        bridge=bridge,
        backlog=backlog,
        backlog_resolution=backlog_resolution,
        selection=selection,
        backlog_policy=BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("tests",),
            request_prefix="v19fb",
            min_tasks=1,
            max_tasks=1,
        ),
        cycle_index=1,
    )
    goal_receipt = record_improvement_planning_goal_handoff(
        activation
    )
    handoff = activation.backlog_handoff
    runtime_contract = contract()
    runtime_receipt = RuntimeVerificationReceipt(
        verification_id=runtime_contract.verification_id,
        task_id=TASK_ID,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        contract_fingerprint=runtime_contract.fingerprint(),
        registry_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        status=status,
        dispatch_count=1,
    )
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
        "project_id": "v19-feedback-proof",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "metadata": {},
    }
    remote = RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=REPO,
        pull_request_url=f"https://github.com/{REPO}/pull/99",
        recorded_at="2026-10-02T00:00:00+00:00",
        status="MERGED",
    ).to_dict()
    result = build_verified_improvement_lineage_retirement(
        ledger=ledger,
        bridge=bridge,
        goal_receipt=goal_receipt,
        backlog=backlog,
        backlog_handoff=handoff,
        campaign_payload=campaign,
        state_payload=state,
        remote_execution_payload=remote,
        runtime_contract_payload=runtime_contract.canonical_dict(),
        runtime_receipt_payload=runtime_receipt.canonical_dict(),
        runtime_report_wrapper_payload=report_wrapper(),
        bridge_path=".autodev/improvement/bridge.json",
        goal_receipt_path=".autodev/improvement/goal-receipt.json",
        backlog_handoff_path=".autodev/autonomous-backlog/handoff.json",
        campaign_path=".autodev/campaign.json",
        state_path=".autodev/state.json",
        remote_execution_path=".autodev/runtime/remote-execution.json",
        runtime_contract_path=".autodev/runtime-verification/v19-feedback-001/contract.json",
        runtime_receipt_path=".autodev/runtime-verification/v19-feedback-001/receipt.json",
        runtime_report_path=".autodev/runtime-verification/v19-feedback-001/report.json",
        backlog_retirement_path=".autodev/autonomous-backlog/retirement.json",
    )
    return result, ledger, origin


def main() -> int:
    try:
        (retirement, backlog_retirement), ledger, origin = build()
        resolved = resolve_improvement_signals(
            ledger,
            retirements=(retirement,),
        )
        if (
            resolved.entry_for(origin.signal_id).state
            is not ImprovementResolutionState.RETIRED
        ):
            raise AssertionError(
                "verified successor did not retire origin signal"
            )

        repeated = signal(seed="d")
        extended = ImprovementSignalLedger(
            signals=(*ledger.signals, repeated)
        )
        repeated_resolution = resolve_improvement_signals(
            extended,
            retirements=(retirement,),
        )
        if (
            repeated_resolution.entry_for(repeated.signal_id).state
            is not ImprovementResolutionState.RETIRED
        ):
            raise AssertionError(
                "same improvement subject became current again"
            )

        failed_blocked = False
        try:
            build(status="FAILED")
        except ValueError:
            failed_blocked = True
        if not failed_blocked:
            raise AssertionError(
                "FAILED runtime outcome retired improvement lineage"
            )

        payload = retirement.canonical_dict()
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
        ):
            if payload[field] is not False:
                raise AssertionError(
                    f"retirement authority drift: {field}"
                )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": "v1.9-verified-improvement-lineage-retirement",
                    "retirement_id": retirement.retirement_id,
                    "retirement_fingerprint": retirement.fingerprint(),
                    "backlog_retirement_id": backlog_retirement.retirement_id,
                    "origin_signal_id": origin.signal_id,
                    "same_subject_reentry_blocked": True,
                    "failed_runtime_retirement_blocked": True,
                    "planning_authority": False,
                    "execution_authority": False,
                    "auto_dispatch": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        message = (
            str(exc).splitlines()[0].strip()
            if str(exc).strip()
            else type(exc).__name__
        )
        print(
            json.dumps(
                {"ok": False, "error": message[:256]},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
