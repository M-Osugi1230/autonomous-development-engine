from __future__ import annotations

import unittest

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import (
    ImprovementSignalLedger,
    ImprovementSignalLedgerError,
)
from ade.improvement_signal_resolution import (
    ImprovementResolutionPolicy,
    ImprovementResolutionReason,
    ImprovementResolutionState,
    resolve_improvement_signals,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40
RELEASE_ID = "release-proof-001"


def evidence(seed: str = "a"):
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
    )


def make_signal(
    *,
    kind: ImprovementSignalKind,
    statement: str,
    parent_signal_id: str | None = None,
    generation: int = 0,
    release_id: str = RELEASE_ID,
    repository: str = REPOSITORY,
    evidence_seed: str = "a",
):
    return build_improvement_signal(
        repository=repository,
        source_sha=SOURCE_SHA,
        release_candidate_id=release_id,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=evidence(evidence_seed),
        parent_signal_id=parent_signal_id,
        generation=generation,
        tags=(kind.value.casefold().replace("_", "-"),),
    )


class ImprovementSignalLedgerTests(unittest.TestCase):
    def test_ledger_order_and_fingerprint_are_deterministic(self) -> None:
        observation = make_signal(
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement="Retain one release observation.",
        )
        gap = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate one runtime gap.",
            evidence_seed="c",
        )

        first = ImprovementSignalLedger(
            signals=(observation, gap)
        )
        second = ImprovementSignalLedger(
            signals=(gap, observation)
        )
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_append_is_idempotent_for_same_content(self) -> None:
        signal = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate one runtime gap.",
        )
        ledger = ImprovementSignalLedger().append(signal)
        again = ledger.append(signal)
        self.assertEqual(ledger, again)
        self.assertEqual(again.signal_count, 1)

    def test_cross_release_lineage_fails_closed(self) -> None:
        parent = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate root runtime gap.",
        )
        child = make_signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate successor quality gap.",
            parent_signal_id=parent.signal_id,
            generation=1,
            release_id="release-other-001",
            evidence_seed="c",
        )
        with self.assertRaisesRegex(
            ImprovementSignalLedgerError,
            "cross-release improvement lineage",
        ):
            ImprovementSignalLedger(
                signals=(parent, child)
            )

    def test_missing_parent_fails_closed(self) -> None:
        child = make_signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate successor quality gap.",
            parent_signal_id="improve-missing-parent",
            generation=1,
        )
        with self.assertRaisesRegex(
            ImprovementSignalLedgerError,
            "parent is absent",
        ):
            ImprovementSignalLedger(signals=(child,))


class ImprovementSignalResolutionTests(unittest.TestCase):
    def test_release_followup_is_observation_only(self) -> None:
        observation = make_signal(
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement="Retain one release observation.",
        )
        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(signals=(observation,))
        )
        entry = resolution.entry_for(observation.signal_id)
        self.assertEqual(
            entry.state,
            ImprovementResolutionState.OBSERVATION_ONLY,
        )
        self.assertEqual(
            entry.reason,
            ImprovementResolutionReason.VERIFIED_RELEASE_OBSERVATION,
        )
        self.assertEqual(resolution.current_signal_ids, ())

    def test_one_current_gap_per_release_and_priority_is_controller_owned(self) -> None:
        runtime = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate runtime gap.",
            evidence_seed="c",
        )
        quality = make_signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate quality gap.",
            evidence_seed="d",
        )
        performance = make_signal(
            kind=ImprovementSignalKind.PERFORMANCE_GAP,
            statement="Investigate performance gap.",
            evidence_seed="e",
        )
        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(
                signals=(performance, quality, runtime)
            )
        )

        self.assertEqual(
            resolution.entry_for(runtime.signal_id).state,
            ImprovementResolutionState.CURRENT,
        )
        self.assertEqual(
            resolution.entry_for(quality.signal_id).state,
            ImprovementResolutionState.COOLDOWN,
        )
        self.assertEqual(
            resolution.entry_for(performance.signal_id).state,
            ImprovementResolutionState.COOLDOWN,
        )
        self.assertEqual(
            resolution.current_signal_ids,
            (runtime.signal_id,),
        )

    def test_clear_successor_supersedes_parent(self) -> None:
        parent = make_signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate root quality gap.",
        )
        child = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate refined runtime gap.",
            parent_signal_id=parent.signal_id,
            generation=1,
            evidence_seed="c",
        )
        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(
                signals=(child, parent)
            )
        )
        self.assertEqual(
            resolution.entry_for(parent.signal_id).state,
            ImprovementResolutionState.SUPERSEDED,
        )
        self.assertEqual(
            resolution.entry_for(parent.signal_id).reason,
            ImprovementResolutionReason.LINEAGE_ADVANCED,
        )
        self.assertEqual(
            resolution.entry_for(child.signal_id).state,
            ImprovementResolutionState.CURRENT,
        )

    def test_branching_lineage_conflicts_children_without_superseding_parent(self) -> None:
        parent = make_signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate root quality gap.",
        )
        first = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate first refined gap.",
            parent_signal_id=parent.signal_id,
            generation=1,
            evidence_seed="c",
        )
        second = make_signal(
            kind=ImprovementSignalKind.RELIABILITY_GAP,
            statement="Investigate second refined gap.",
            parent_signal_id=parent.signal_id,
            generation=1,
            evidence_seed="d",
        )
        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(
                signals=(parent, first, second)
            )
        )
        self.assertEqual(
            resolution.entry_for(first.signal_id).state,
            ImprovementResolutionState.CONFLICTED,
        )
        self.assertEqual(
            resolution.entry_for(second.signal_id).state,
            ImprovementResolutionState.CONFLICTED,
        )
        self.assertEqual(
            resolution.entry_for(parent.signal_id).state,
            ImprovementResolutionState.CURRENT,
        )

    def test_generation_limit_stops_recursive_successor_loop(self) -> None:
        signals = []
        parent = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate generation zero.",
        )
        signals.append(parent)
        for generation in range(1, 6):
            child = make_signal(
                kind=ImprovementSignalKind.RUNTIME_GAP,
                statement=(
                    "Investigate generation "
                    + str(generation)
                    + "."
                ),
                parent_signal_id=parent.signal_id,
                generation=generation,
                evidence_seed=chr(ord("c") + generation),
            )
            signals.append(child)
            parent = child

        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(signals=tuple(signals)),
            policy=ImprovementResolutionPolicy(
                max_generation=4
            ),
        )
        limited = signals[-1]
        current = signals[-2]
        self.assertEqual(
            resolution.entry_for(limited.signal_id).state,
            ImprovementResolutionState.CYCLE_LIMIT,
        )
        self.assertEqual(
            resolution.entry_for(current.signal_id).state,
            ImprovementResolutionState.CURRENT,
        )

    def test_resolution_carries_no_authority(self) -> None:
        gap = make_signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate runtime gap.",
        )
        resolution = resolve_improvement_signals(
            ImprovementSignalLedger(signals=(gap,))
        )
        payload = resolution.canonical_dict()
        self.assertFalse(payload["planning_authority"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])


if __name__ == "__main__":
    unittest.main()
