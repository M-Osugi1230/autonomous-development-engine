from __future__ import annotations

import json

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_goal import BacklogPlanningPolicy
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.improvement_bridge import (
    build_improvement_memory_backlog_bridge,
)
from ade.improvement_goal_handoff import (
    ImprovementCyclePolicy,
    ImprovementGoalReceiptStatus,
    arm_improvement_planning_goal_handoff,
    record_improvement_planning_goal_handoff,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import resolve_improvement_signals


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_ID = "release-a4cd075b270b6ad434ae2602"


def _signal():
    return build_improvement_signal(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=ImprovementSignalKind.RUNTIME_GAP,
        statement="Investigate one bounded runtime gap.",
        evidence_refs=(
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path=(
                    ".autodev/campaign-evidence/"
                    "v1.8-autonomous-release-proof-001.json"
                ),
                fingerprint="a" * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.POST_VERIFICATION,
                path=(
                    ".autodev/release/proof/final/"
                    "post-verification-finalization.json"
                ),
                fingerprint="b" * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RECOVERY,
                path=".autodev/improvement/recovery-gap.json",
                fingerprint="c" * 64,
            ),
        ),
        tags=("verified-release",),
    )


def main() -> int:
    try:
        signal = _signal()
        ledger = ImprovementSignalLedger(signals=(signal,))
        improvement_resolution = resolve_improvement_signals(
            ledger
        )
        bridge = build_improvement_memory_backlog_bridge(
            ledger=ledger,
            resolution=improvement_resolution,
            signal_id=signal.signal_id,
            signal_path=(
                ".autodev/improvement/signals/"
                + signal.signal_id
                + ".json"
            ),
            resolution_path=(
                ".autodev/improvement/resolution.json"
            ),
        )
        backlog = AutonomousBacklog(
            candidates=(bridge.backlog_candidate,)
        )
        backlog_resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPOSITORY: SOURCE_SHA},
        )
        selection = select_next_backlog_candidate(
            backlog,
            backlog_resolution,
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
        )
        backlog_policy = BacklogPlanningPolicy(
            repository=REPOSITORY,
            base_branch="main",
            allowed_path_prefixes=("src", "tests"),
            request_prefix="v19ci",
            min_tasks=1,
            max_tasks=2,
        )
        cycle_policy = ImprovementCyclePolicy(
            max_cycles=4
        )
        activation = arm_improvement_planning_goal_handoff(
            ledger=ledger,
            improvement_resolution=improvement_resolution,
            bridge=bridge,
            backlog=backlog,
            backlog_resolution=backlog_resolution,
            selection=selection,
            backlog_policy=backlog_policy,
            cycle_index=1,
            cycle_policy=cycle_policy,
        )
        if not activation.should_handoff:
            raise AssertionError(
                "first trusted improvement cycle did not arm"
            )
        request = activation.backlog_handoff.request
        if request.allowed_path_prefixes != ("src", "tests"):
            raise AssertionError(
                "PlanningGoal scope did not come from trusted policy"
            )

        receipt = record_improvement_planning_goal_handoff(
            activation
        )
        if (
            receipt.status
            is not ImprovementGoalReceiptStatus.HANDED_OFF
            or receipt.handoff_count != 1
        ):
            raise AssertionError(
                "PlanningGoal handoff was not recorded exactly once"
            )

        replay = arm_improvement_planning_goal_handoff(
            ledger=ledger,
            improvement_resolution=improvement_resolution,
            bridge=bridge,
            backlog=backlog,
            backlog_resolution=backlog_resolution,
            selection=selection,
            backlog_policy=backlog_policy,
            cycle_index=1,
            cycle_policy=cycle_policy,
            existing_receipt=receipt,
        )
        if replay.should_handoff:
            raise AssertionError(
                "duplicate PlanningGoal handoff was not suppressed"
            )

        payload = replay.canonical_dict()
        for field in (
            "execution_authority",
            "accepted_plan_authority",
            "auto_dispatch",
        ):
            if payload[field] is not False:
                raise AssertionError(
                    f"PlanningGoal handoff authority drift: {field}"
                )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-bounded-successor-planning-goal-handoff"
                    ),
                    "cycle_id": receipt.cycle_id,
                    "cycle_index": receipt.cycle_index,
                    "signal_id": receipt.signal_id,
                    "backlog_candidate_id": (
                        receipt.backlog_candidate_id
                    ),
                    "planning_request_id": request.request_id,
                    "planning_request_fingerprint": (
                        request.fingerprint()
                    ),
                    "handoff_count": receipt.handoff_count,
                    "duplicate_suppressed": True,
                    "max_cycles": cycle_policy.max_cycles,
                    "max_goal_handoffs_per_cycle": 1,
                    "scope_from_trusted_policy": True,
                    "execution_authority": False,
                    "accepted_plan_authority": False,
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
