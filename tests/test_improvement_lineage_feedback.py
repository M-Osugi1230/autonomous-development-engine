from __future__ import annotations

import unittest

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_goal import BacklogPlanningPolicy
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.improvement_bridge import (
    build_improvement_memory_backlog_bridge,
)
from ade.improvement_goal_handoff import (
    arm_improvement_planning_goal_handoff,
    record_improvement_planning_goal_handoff,
)
from ade.improvement_lineage_feedback import (
    ImprovementLineageFeedbackError,
    ImprovementLineageRetirement,
    build_verified_improvement_lineage_retirement,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
    improvement_signal_subject_fingerprint,
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
RELEASE_ID = "release-proof-retirement-001"
TASK_ID = "v19ci-task-001"


def evidence(seed: str):
    return (
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
    )


def make_signal(
    *,
    seed: str = "a",
    parent_signal_id: str | None = None,
    generation: int = 0,
    statement: str = "Investigate one bounded runtime gap.",
):
    return build_improvement_signal(
        repository=REPO,
        source_sha=BASE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=ImprovementSignalKind.RUNTIME_GAP,
        statement=statement,
        evidence_refs=evidence(seed),
        parent_signal_id=parent_signal_id,
        generation=generation,
        tags=("verified-release",),
    )


def chain(origin, *, ancestors=()):
    ledger = ImprovementSignalLedger(
        signals=(*ancestors, origin)
    )
    improvement_resolution = resolve_improvement_signals(
        ledger
    )
    bridge = build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=improvement_resolution,
        signal_id=origin.signal_id,
        signal_path=(
            ".autodev/improvement/signals/"
            + origin.signal_id
            + ".json"
        ),
        resolution_path=".autodev/improvement/resolution.json",
    )
    backlog = AutonomousBacklog(
        candidates=(bridge.backlog_candidate,)
    )
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
        improvement_resolution=improvement_resolution,
        bridge=bridge,
        backlog=backlog,
        backlog_resolution=backlog_resolution,
        selection=selection,
        backlog_policy=BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("tests",),
            request_prefix="v19ci",
            min_tasks=1,
            max_tasks=1,
        ),
        cycle_index=1,
    )
    receipt = record_improvement_planning_goal_handoff(
        activation
    )
    return (
        ledger,
        bridge,
        backlog,
        activation.backlog_handoff,
        receipt,
    )


def runtime_contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=(
            "offline-cli-smoke",
            "production-import-smoke",
        ),
        max_attempts=2,
        timeout_seconds=300,
    )


def runtime_receipt(
    *,
    status: str = "VERIFIED",
) -> RuntimeVerificationReceipt:
    contract = runtime_contract()
    return RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id=TASK_ID,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        status=status,
        dispatch_count=1,
    )


def runtime_report_wrapper(*, fail: bool = False):
    contract = runtime_contract()
    results = (
        RuntimeProbeResult(
            probe_id="offline-cli-smoke",
            status=(
                RuntimeProbeStatus.FAIL
                if fail
                else RuntimeProbeStatus.PASS
            ),
            source_sha=MERGE_SHA,
            attempt=1,
            detail_code=(
                "offline-cli-fail"
                if fail
                else "offline-cli-pass"
            ),
        ),
        RuntimeProbeResult(
            probe_id="production-import-smoke",
            status=RuntimeProbeStatus.PASS,
            source_sha=MERGE_SHA,
            attempt=1,
            detail_code="production-import-pass",
        ),
    )
    report = evaluate_runtime_verification(
        contract,
        results,
    )
    return {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {
                "probe_id": "production-import-smoke",
                "attempts": 1,
            },
        ],
    }


def completion_evidence(handoff):
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
        "project_id": "ade-v19-test",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "metadata": {},
    }
    remote = RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=REPO,
        pull_request_url=(
            "https://github.com/"
            + REPO
            + "/pull/99"
        ),
        recorded_at="2026-10-02T00:00:00+00:00",
        status="MERGED",
    ).to_dict()
    return campaign, state, remote


def build_retirement(
    *,
    origin=None,
    ancestors=(),
    runtime_status: str = "VERIFIED",
):
    origin = origin or make_signal()
    ledger, bridge, backlog, handoff, goal_receipt = chain(
        origin,
        ancestors=ancestors,
    )
    campaign, state, remote = completion_evidence(
        handoff
    )
    return (
        build_verified_improvement_lineage_retirement(
            ledger=ledger,
            bridge=bridge,
            goal_receipt=goal_receipt,
            backlog=backlog,
            backlog_handoff=handoff,
            campaign_payload=campaign,
            state_payload=state,
            remote_execution_payload=remote,
            runtime_contract_payload=(
                runtime_contract().canonical_dict()
            ),
            runtime_receipt_payload=(
                runtime_receipt(
                    status=runtime_status
                ).canonical_dict()
            ),
            runtime_report_wrapper_payload=(
                runtime_report_wrapper()
            ),
            bridge_path=".autodev/improvement/bridge.json",
            goal_receipt_path=(
                ".autodev/improvement/goal-receipt.json"
            ),
            backlog_handoff_path=(
                ".autodev/autonomous-backlog/handoff.json"
            ),
            campaign_path=".autodev/campaign.json",
            state_path=".autodev/state.json",
            remote_execution_path=(
                ".autodev/runtime/remote-execution.json"
            ),
            runtime_contract_path=(
                ".autodev/runtime-verification/"
                + TASK_ID
                + "/contract.json"
            ),
            runtime_receipt_path=(
                ".autodev/runtime-verification/"
                + TASK_ID
                + "/receipt.json"
            ),
            runtime_report_path=(
                ".autodev/runtime-verification/"
                + TASK_ID
                + "/report.json"
            ),
            backlog_retirement_path=(
                ".autodev/autonomous-backlog/"
                "retirement.json"
            ),
        ),
        ledger,
        origin,
    )


class ImprovementLineageFeedbackTests(unittest.TestCase):
    def test_verified_successor_retires_origin_signal(self) -> None:
        (retirement, backlog_retirement), ledger, origin = (
            build_retirement()
        )
        self.assertEqual(
            retirement.origin_signal_id,
            origin.signal_id,
        )
        self.assertEqual(
            retirement.subject_fingerprint,
            improvement_signal_subject_fingerprint(origin),
        )
        self.assertEqual(
            retirement.retired_signal_ids,
            (origin.signal_id,),
        )
        self.assertEqual(
            retirement.backlog_retirement_id,
            backlog_retirement.retirement_id,
        )
        self.assertEqual(
            retirement.verified_source_sha,
            MERGE_SHA,
        )

        resolved = resolve_improvement_signals(
            ledger,
            retirements=(retirement,),
        )
        entry = resolved.entry_for(origin.signal_id)
        self.assertEqual(
            entry.state,
            ImprovementResolutionState.RETIRED,
        )
        self.assertEqual(
            resolved.current_signal_ids,
            (),
        )

    def test_same_subject_with_new_evidence_stays_retired(self) -> None:
        (retirement, _), ledger, origin = build_retirement()
        repeated = make_signal(seed="d")
        self.assertNotEqual(
            repeated.signal_id,
            origin.signal_id,
        )
        self.assertEqual(
            improvement_signal_subject_fingerprint(repeated),
            retirement.subject_fingerprint,
        )
        extended = ImprovementSignalLedger(
            signals=(*ledger.signals, repeated)
        )
        resolved = resolve_improvement_signals(
            extended,
            retirements=(retirement,),
        )
        self.assertEqual(
            resolved.entry_for(repeated.signal_id).state,
            ImprovementResolutionState.RETIRED,
        )
        self.assertEqual(
            resolved.current_signal_ids,
            (),
        )

    def test_verified_child_completion_retires_whole_ancestor_lineage(self) -> None:
        root = make_signal(
            statement="Investigate root runtime gap.",
        )
        child = make_signal(
            seed="d",
            parent_signal_id=root.signal_id,
            generation=1,
            statement="Investigate refined runtime gap.",
        )
        (retirement, _), ledger, _ = build_retirement(
            origin=child,
            ancestors=(root,),
        )
        self.assertEqual(
            retirement.retired_signal_ids,
            (root.signal_id, child.signal_id),
        )
        resolved = resolve_improvement_signals(
            ledger,
            retirements=(retirement,),
        )
        self.assertEqual(
            resolved.entry_for(root.signal_id).state,
            ImprovementResolutionState.RETIRED,
        )
        self.assertEqual(
            resolved.entry_for(child.signal_id).state,
            ImprovementResolutionState.RETIRED,
        )

    def test_failed_runtime_outcome_cannot_retire_lineage(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires VERIFIED runtime receipt",
        ):
            build_retirement(runtime_status="FAILED")

    def test_retirement_authority_escalation_fails_closed(self) -> None:
        (retirement, _), _, _ = build_retirement()
        payload = retirement.canonical_dict()
        payload["execution_authority"] = True
        with self.assertRaisesRegex(
            ImprovementLineageFeedbackError,
            "cannot grant execution authority",
        ):
            ImprovementLineageRetirement.from_dict(payload)

    def test_retirement_round_trip_is_deterministic(self) -> None:
        (first, _), _, _ = build_retirement()
        (second, _), _, _ = build_retirement()
        self.assertEqual(
            first.canonical_dict(),
            second.canonical_dict(),
        )
        self.assertEqual(
            first.fingerprint(),
            second.fingerprint(),
        )
        self.assertEqual(
            ImprovementLineageRetirement.from_dict(
                first.canonical_dict()
            ),
            first,
        )


if __name__ == "__main__":
    unittest.main()
