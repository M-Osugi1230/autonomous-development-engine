from __future__ import annotations

import unittest

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)
from ade.autonomous_backlog_selection import (
    select_next_backlog_candidate,
)
from ade.development_memory import MemoryKind
from ade.improvement_bridge import (
    ImprovementBridgeError,
    build_improvement_memory_backlog_bridge,
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


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40
RELEASE_ID = "release-proof-bridge-001"


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


def signal(
    *,
    kind: ImprovementSignalKind,
    statement: str,
    seed: str,
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


def bridge_for(
    ledger: ImprovementSignalLedger,
    signal_id: str,
):
    resolution = resolve_improvement_signals(ledger)
    return build_improvement_memory_backlog_bridge(
        ledger=ledger,
        resolution=resolution,
        signal_id=signal_id,
        signal_path=(
            ".autodev/improvement/signals/"
            + signal_id
            + ".json"
        ),
        resolution_path=(
            ".autodev/improvement/resolution.json"
        ),
    )


class ImprovementBridgeTests(unittest.TestCase):
    def test_current_runtime_gap_builds_memory_and_backlog_candidate(self) -> None:
        gap = signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate one runtime gap.",
            seed="a",
        )
        ledger = ImprovementSignalLedger(signals=(gap,))
        bundle = bridge_for(ledger, gap.signal_id)

        self.assertEqual(bundle.signal_id, gap.signal_id)
        self.assertEqual(
            bundle.memory_record.kind,
            MemoryKind.REMEDIATION,
        )
        self.assertEqual(
            bundle.memory_record.repository,
            gap.repository,
        )
        self.assertEqual(
            bundle.backlog_candidate.repository,
            gap.repository,
        )
        self.assertEqual(
            bundle.backlog_candidate.source_sha,
            gap.source_sha,
        )
        self.assertFalse(
            bundle.backlog_candidate.human_only
        )
        payload = bundle.canonical_dict()
        self.assertEqual(
            payload["memory_authority"],
            "advisory-data-only",
        )
        self.assertFalse(payload["planning_authority"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["selection_authority"])

    def test_observation_only_release_followup_cannot_cross_bridge(self) -> None:
        observation = signal(
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement="Retain one release observation.",
            seed="a",
        )
        ledger = ImprovementSignalLedger(
            signals=(observation,)
        )
        resolution = resolve_improvement_signals(ledger)
        self.assertEqual(
            resolution.entry_for(observation.signal_id).state,
            ImprovementResolutionState.OBSERVATION_ONLY,
        )

        with self.assertRaisesRegex(
            ImprovementBridgeError,
            "only CURRENT improvement signal",
        ):
            build_improvement_memory_backlog_bridge(
                ledger=ledger,
                resolution=resolution,
                signal_id=observation.signal_id,
                signal_path=(
                    ".autodev/improvement/signals/"
                    + observation.signal_id
                    + ".json"
                ),
                resolution_path=(
                    ".autodev/improvement/resolution.json"
                ),
            )

    def test_cooldown_signal_cannot_cross_bridge(self) -> None:
        runtime = signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate runtime gap.",
            seed="a",
        )
        quality = signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate quality gap.",
            seed="d",
        )
        ledger = ImprovementSignalLedger(
            signals=(runtime, quality)
        )
        resolution = resolve_improvement_signals(ledger)
        self.assertEqual(
            resolution.entry_for(quality.signal_id).state,
            ImprovementResolutionState.COOLDOWN,
        )

        with self.assertRaisesRegex(
            ImprovementBridgeError,
            "only CURRENT improvement signal",
        ):
            build_improvement_memory_backlog_bridge(
                ledger=ledger,
                resolution=resolution,
                signal_id=quality.signal_id,
                signal_path=(
                    ".autodev/improvement/signals/"
                    + quality.signal_id
                    + ".json"
                ),
                resolution_path=(
                    ".autodev/improvement/resolution.json"
                ),
            )

    def test_resolution_drift_cannot_cross_bridge(self) -> None:
        first = signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate runtime gap.",
            seed="a",
        )
        second = signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate quality gap.",
            seed="d",
        )
        first_ledger = ImprovementSignalLedger(
            signals=(first,)
        )
        second_ledger = ImprovementSignalLedger(
            signals=(first, second)
        )
        wrong_resolution = resolve_improvement_signals(
            first_ledger
        )

        with self.assertRaisesRegex(
            ImprovementBridgeError,
            "resolution does not bind supplied signal ledger",
        ):
            build_improvement_memory_backlog_bridge(
                ledger=second_ledger,
                resolution=wrong_resolution,
                signal_id=first.signal_id,
                signal_path=(
                    ".autodev/improvement/signals/"
                    + first.signal_id
                    + ".json"
                ),
                resolution_path=(
                    ".autodev/improvement/resolution.json"
                ),
            )

    def test_bridge_still_requires_existing_backlog_resolution_and_selection(self) -> None:
        gap = signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate runtime gap.",
            seed="a",
        )
        ledger = ImprovementSignalLedger(signals=(gap,))
        bundle = bridge_for(ledger, gap.signal_id)

        backlog = AutonomousBacklog(
            candidates=(bundle.backlog_candidate,)
        )
        backlog_resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPOSITORY: SOURCE_SHA},
        )
        entry = backlog_resolution.entry_for(
            bundle.backlog_candidate.candidate_id
        )
        self.assertEqual(
            entry.state,
            BacklogResolutionState.CURRENT,
        )
        selection = select_next_backlog_candidate(
            backlog,
            backlog_resolution,
        )
        self.assertEqual(
            selection.selected_candidate_id,
            bundle.backlog_candidate.candidate_id,
        )
        self.assertFalse(
            selection.canonical_dict()["planning_goal_authority"]
        )

    def test_bridge_is_deterministic(self) -> None:
        gap = signal(
            kind=ImprovementSignalKind.RELIABILITY_GAP,
            statement="Investigate reliability gap.",
            seed="a",
        )
        ledger = ImprovementSignalLedger(signals=(gap,))
        first = bridge_for(ledger, gap.signal_id)
        second = bridge_for(ledger, gap.signal_id)
        self.assertEqual(
            first.canonical_dict(),
            second.canonical_dict(),
        )
        self.assertEqual(
            first.fingerprint(),
            second.fingerprint(),
        )


if __name__ == "__main__":
    unittest.main()
