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
    ImprovementCyclePolicy,
    ImprovementGoalHandoffError,
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
SOURCE_SHA = "a" * 40
RELEASE_ID = "release-proof-goal-001"


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
    kind: ImprovementSignalKind = ImprovementSignalKind.RUNTIME_GAP,
    seed: str = "a",
    statement: str = "Investigate one bounded runtime gap.",
):
    return build_improvement_signal(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=evidence(seed),
        tags=("verified-release",),
    )


def chain(signal):
    ledger = ImprovementSignalLedger(signals=(signal,))
    improvement_resolution = resolve_improvement_signals(ledger)
    bridge = build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=improvement_resolution,
        signal_id=signal.signal_id,
        signal_path=(
            ".autodev/improvement/signals/"
            + signal.signal_id
            + ".json"
        ),
        resolution_path=".autodev/improvement/resolution.json",
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
    policy = BacklogPlanningPolicy(
        repository=REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("src", "tests"),
        request_prefix="v19ci",
        min_tasks=1,
        max_tasks=2,
    )
    return (
        ledger,
        improvement_resolution,
        bridge,
        backlog,
        backlog_resolution,
        selection,
        policy,
    )


class ImprovementGoalHandoffTests(unittest.TestCase):
    def test_current_signal_handoffs_through_existing_backlog_goal_layer(self) -> None:
        value = make_signal()
        (
            ledger,
            improvement_resolution,
            bridge,
            backlog,
            backlog_resolution,
            selection,
            policy,
        ) = chain(value)

        activation = arm_improvement_planning_goal_handoff(
            ledger=ledger,
            improvement_resolution=improvement_resolution,
            bridge=bridge,
            backlog=backlog,
            backlog_resolution=backlog_resolution,
            selection=selection,
            backlog_policy=policy,
            cycle_index=1,
        )
        self.assertTrue(activation.should_handoff)
        self.assertEqual(
            activation.receipt.status,
            ImprovementGoalReceiptStatus.ARMED,
        )
        self.assertEqual(activation.receipt.handoff_count, 0)

        request = activation.backlog_handoff.request
        self.assertEqual(request.target_repository, REPOSITORY)
        self.assertEqual(
            request.allowed_path_prefixes,
            ("src", "tests"),
        )
        self.assertEqual(request.min_tasks, 1)
        self.assertEqual(request.max_tasks, 2)

        payload = activation.canonical_dict()
        self.assertEqual(
            payload["handoff_target"],
            "AutonomousPlanner",
        )
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["accepted_plan_authority"])
        self.assertFalse(payload["auto_dispatch"])

    def test_handoff_receipt_suppresses_duplicate_in_same_cycle(self) -> None:
        (
            ledger,
            improvement_resolution,
            bridge,
            backlog,
            backlog_resolution,
            selection,
            policy,
        ) = chain(make_signal())

        first = arm_improvement_planning_goal_handoff(
            ledger=ledger,
            improvement_resolution=improvement_resolution,
            bridge=bridge,
            backlog=backlog,
            backlog_resolution=backlog_resolution,
            selection=selection,
            backlog_policy=policy,
            cycle_index=1,
        )
        receipt = record_improvement_planning_goal_handoff(first)
        self.assertEqual(
            receipt.status,
            ImprovementGoalReceiptStatus.HANDED_OFF,
        )
        self.assertEqual(receipt.handoff_count, 1)

        second = arm_improvement_planning_goal_handoff(
            ledger=ledger,
            improvement_resolution=improvement_resolution,
            bridge=bridge,
            backlog=backlog,
            backlog_resolution=backlog_resolution,
            selection=selection,
            backlog_policy=policy,
            cycle_index=1,
            existing_receipt=receipt,
        )
        self.assertFalse(second.should_handoff)
        self.assertEqual(
            record_improvement_planning_goal_handoff(second),
            receipt,
        )

    def test_same_cycle_cannot_be_reused_for_different_signal(self) -> None:
        first_chain = chain(make_signal())
        first = arm_improvement_planning_goal_handoff(
            ledger=first_chain[0],
            improvement_resolution=first_chain[1],
            bridge=first_chain[2],
            backlog=first_chain[3],
            backlog_resolution=first_chain[4],
            selection=first_chain[5],
            backlog_policy=first_chain[6],
            cycle_index=1,
        )
        receipt = record_improvement_planning_goal_handoff(first)

        second_chain = chain(
            make_signal(
                kind=ImprovementSignalKind.QUALITY_GAP,
                seed="d",
                statement="Investigate one bounded quality gap.",
            )
        )
        with self.assertRaisesRegex(
            ImprovementGoalHandoffError,
            "existing PlanningGoal receipt identity drift",
        ):
            arm_improvement_planning_goal_handoff(
                ledger=second_chain[0],
                improvement_resolution=second_chain[1],
                bridge=second_chain[2],
                backlog=second_chain[3],
                backlog_resolution=second_chain[4],
                selection=second_chain[5],
                backlog_policy=second_chain[6],
                cycle_index=1,
                existing_receipt=receipt,
            )

    def test_cycle_budget_bounds_recursive_goal_handoffs(self) -> None:
        (
            ledger,
            improvement_resolution,
            bridge,
            backlog,
            backlog_resolution,
            selection,
            policy,
        ) = chain(make_signal())

        with self.assertRaisesRegex(
            ImprovementGoalHandoffError,
            "cycle_index exceeds trusted improvement cycle budget",
        ):
            arm_improvement_planning_goal_handoff(
                ledger=ledger,
                improvement_resolution=improvement_resolution,
                bridge=bridge,
                backlog=backlog,
                backlog_resolution=backlog_resolution,
                selection=selection,
                backlog_policy=policy,
                cycle_index=5,
                cycle_policy=ImprovementCyclePolicy(
                    max_cycles=4
                ),
            )

    def test_bridge_and_selection_identity_must_match(self) -> None:
        first = chain(make_signal())
        second = chain(
            make_signal(
                kind=ImprovementSignalKind.QUALITY_GAP,
                seed="d",
                statement="Investigate one bounded quality gap.",
            )
        )
        with self.assertRaises(
            ImprovementGoalHandoffError
        ):
            arm_improvement_planning_goal_handoff(
                ledger=first[0],
                improvement_resolution=first[1],
                bridge=first[2],
                backlog=second[3],
                backlog_resolution=second[4],
                selection=second[5],
                backlog_policy=second[6],
                cycle_index=1,
            )

    def test_handoff_is_deterministic(self) -> None:
        values = chain(make_signal())
        left = arm_improvement_planning_goal_handoff(
            ledger=values[0],
            improvement_resolution=values[1],
            bridge=values[2],
            backlog=values[3],
            backlog_resolution=values[4],
            selection=values[5],
            backlog_policy=values[6],
            cycle_index=2,
        )
        right = arm_improvement_planning_goal_handoff(
            ledger=values[0],
            improvement_resolution=values[1],
            bridge=values[2],
            backlog=values[3],
            backlog_resolution=values[4],
            selection=values[5],
            backlog_policy=values[6],
            cycle_index=2,
        )
        self.assertEqual(
            left.canonical_dict(),
            right.canonical_dict(),
        )
        self.assertEqual(left.fingerprint(), right.fingerprint())


if __name__ == "__main__":
    unittest.main()
