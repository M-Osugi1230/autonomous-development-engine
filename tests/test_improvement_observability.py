from __future__ import annotations

import unittest

from ade.improvement_observability import (
    ImprovementCycleViewState,
    ImprovementObservabilityError,
    ImprovementObservabilitySnapshot,
    build_improvement_observability_snapshot,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import resolve_improvement_signals


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
RELEASE_ID = "release-observability-v19-001"


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


def signal(kind: ImprovementSignalKind, seed: str, statement: str):
    return build_improvement_signal(
        repository=REPO,
        source_sha=SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=evidence(seed),
        tags=("verified-release",),
    )


class ImprovementObservabilityTests(unittest.TestCase):
    def test_projection_exposes_only_safe_state_summary(self) -> None:
        runtime = signal(
            ImprovementSignalKind.RUNTIME_GAP,
            "a",
            "Investigate one bounded runtime gap.",
        )
        quality = signal(
            ImprovementSignalKind.QUALITY_GAP,
            "d",
            "Investigate one bounded quality gap.",
        )
        ledger = ImprovementSignalLedger(
            signals=(runtime, quality)
        )
        resolution = resolve_improvement_signals(ledger)
        snapshot = build_improvement_observability_snapshot(
            ledger=ledger,
            resolution=resolution,
            release_candidate_id=RELEASE_ID,
        )

        self.assertEqual(snapshot.signal_count, 2)
        self.assertEqual(snapshot.current_count, 1)
        self.assertEqual(snapshot.cooldown_count, 1)
        self.assertEqual(
            snapshot.current_signal_id,
            runtime.signal_id,
        )
        self.assertEqual(
            snapshot.current_signal_kind,
            ImprovementSignalKind.RUNTIME_GAP.value,
        )
        self.assertEqual(
            snapshot.cycle_state,
            ImprovementCycleViewState.NOT_STARTED,
        )

        payload = snapshot.canonical_dict()
        serialized = str(payload)
        for forbidden in (
            "statement",
            "evidence_refs",
            "detail_fingerprint",
            "provider_session",
            "registry_fingerprint",
            "planning_authority",
            "execution_authority",
            "ghp_",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_projection_round_trip_and_unknown_fields_fail_closed(self) -> None:
        runtime = signal(
            ImprovementSignalKind.RUNTIME_GAP,
            "a",
            "Investigate one bounded runtime gap.",
        )
        ledger = ImprovementSignalLedger(signals=(runtime,))
        resolution = resolve_improvement_signals(ledger)
        snapshot = build_improvement_observability_snapshot(
            ledger=ledger,
            resolution=resolution,
            release_candidate_id=RELEASE_ID,
        )
        payload = snapshot.canonical_dict()
        self.assertEqual(
            ImprovementObservabilitySnapshot.from_dict(payload),
            snapshot,
        )

        payload["raw_telemetry"] = "secret detail"
        with self.assertRaisesRegex(
            ImprovementObservabilityError,
            "unknown improvement observability fields",
        ):
            ImprovementObservabilitySnapshot.from_dict(payload)

    def test_resolution_mismatch_fails_closed(self) -> None:
        runtime = signal(
            ImprovementSignalKind.RUNTIME_GAP,
            "a",
            "Investigate one bounded runtime gap.",
        )
        quality = signal(
            ImprovementSignalKind.QUALITY_GAP,
            "d",
            "Investigate one bounded quality gap.",
        )
        first_ledger = ImprovementSignalLedger(signals=(runtime,))
        second_ledger = ImprovementSignalLedger(
            signals=(runtime, quality)
        )
        first_resolution = resolve_improvement_signals(
            first_ledger
        )
        with self.assertRaisesRegex(
            ImprovementObservabilityError,
            "resolution does not bind",
        ):
            build_improvement_observability_snapshot(
                ledger=second_ledger,
                resolution=first_resolution,
                release_candidate_id=RELEASE_ID,
            )

    def test_manual_snapshot_requires_consistent_counts(self) -> None:
        with self.assertRaisesRegex(
            ImprovementObservabilityError,
            "do not sum",
        ):
            ImprovementObservabilitySnapshot(
                release_candidate_id=RELEASE_ID,
                repository=REPO,
                source_sha=SHA,
                release_environment="preview",
                signal_count=2,
                observation_only_count=0,
                current_count=1,
                cooldown_count=0,
                superseded_count=0,
                conflicted_count=0,
                cycle_limit_count=0,
                retired_count=0,
                current_signal_id="improve-current",
                current_signal_kind="RUNTIME_GAP",
                cycle_state=ImprovementCycleViewState.NOT_STARTED,
                cycle_index=None,
                handoff_count=0,
                lineage_retirement_count=0,
                latest_retirement_id=None,
            )


if __name__ == "__main__":
    unittest.main()
