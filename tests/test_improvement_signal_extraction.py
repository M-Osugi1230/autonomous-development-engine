from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementSignalKind,
)
from ade.improvement_signal_extraction import (
    ImprovementSignalExtractionError,
    extract_actionable_release_gap_signal,
    extract_verified_release_followup_signal,
)


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_PATH = (
    ROOT
    / ".autodev"
    / "campaign-evidence"
    / "v1.8-autonomous-release-proof-001.json"
)
FINALIZATION_PATH = (
    ROOT
    / ".autodev"
    / "release"
    / "proof"
    / "final"
    / "post-verification-finalization.json"
)
TARGET_PATH = (
    ROOT
    / ".autodev"
    / "release"
    / "proof"
    / "final"
    / "post-verification-target.json"
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def base_kwargs():
    return {
        "campaign_evidence_payload": load(CAMPAIGN_PATH),
        "finalization_payload": load(FINALIZATION_PATH),
        "target_payload": load(TARGET_PATH),
        "campaign_evidence_path": (
            ".autodev/campaign-evidence/"
            "v1.8-autonomous-release-proof-001.json"
        ),
        "finalization_path": (
            ".autodev/release/proof/final/"
            "post-verification-finalization.json"
        ),
        "target_path": (
            ".autodev/release/proof/final/"
            "post-verification-target.json"
        ),
    }


def gap_evidence(kind: ImprovementSignalKind):
    return {
        "schema_version": 1,
        "repository": (
            "M-Osugi1230/one-minute-thought-experiments"
        ),
        "source_sha": (
            "726431b60db8b25cdd4bc15bb1493a0060f36327"
        ),
        "release_candidate_id": (
            "release-a4cd075b270b6ad434ae2602"
        ),
        "release_environment": "preview",
        "signal_kind": kind.value,
        "detail_fingerprint": "d" * 64,
    }


class ImprovementSignalExtractionTests(unittest.TestCase):
    def test_verified_release_creates_observation_only_followup(self) -> None:
        first = extract_verified_release_followup_signal(
            **base_kwargs()
        )
        second = extract_verified_release_followup_signal(
            **base_kwargs()
        )

        self.assertEqual(
            first.kind,
            ImprovementSignalKind.RELEASE_FOLLOWUP,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.generation, 0)
        self.assertIsNone(first.parent_signal_id)
        self.assertEqual(
            first.repository,
            "M-Osugi1230/one-minute-thought-experiments",
        )
        self.assertEqual(
            first.source_sha,
            "726431b60db8b25cdd4bc15bb1493a0060f36327",
        )
        self.assertEqual(
            first.release_candidate_id,
            "release-a4cd075b270b6ad434ae2602",
        )
        self.assertEqual(
            tuple(ref.kind for ref in first.evidence_refs),
            (
                ImprovementEvidenceKind.POST_VERIFICATION,
                ImprovementEvidenceKind.RELEASE_EVIDENCE,
                ImprovementEvidenceKind.RUNTIME_TARGET,
            ),
        )
        payload = first.canonical_dict()
        self.assertFalse(payload["planning_authority"])
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["release_authority"])

    def test_release_identity_drift_fails_closed(self) -> None:
        kwargs = base_kwargs()
        finalization = copy.deepcopy(
            kwargs["finalization_payload"]
        )
        finalization["outcome"]["deployment_id"] = "different-deployment"
        kwargs["finalization_payload"] = finalization

        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "outcome identity drift",
        ):
            extract_verified_release_followup_signal(**kwargs)

    def test_runtime_target_source_drift_fails_closed(self) -> None:
        kwargs = base_kwargs()
        target = copy.deepcopy(kwargs["target_payload"])
        target["evidence"]["source_sha"] = "f" * 40
        kwargs["target_payload"] = target

        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "runtime target observation identity drift",
        ):
            extract_verified_release_followup_signal(**kwargs)

    def test_unverified_release_cannot_create_followup(self) -> None:
        kwargs = base_kwargs()
        campaign = copy.deepcopy(
            kwargs["campaign_evidence_payload"]
        )
        campaign["promotion_verified"] = False
        kwargs["campaign_evidence_payload"] = campaign

        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "requires verified promotion",
        ):
            extract_verified_release_followup_signal(**kwargs)

    def test_actionable_gap_requires_additional_recovery_or_telemetry(self) -> None:
        kwargs = base_kwargs()
        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "requires trusted RECOVERY or TELEMETRY",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.QUALITY_GAP,
                gap_evidence_kind=(
                    ImprovementEvidenceKind.HUMAN_DECISION
                ),
                gap_evidence_payload=gap_evidence(
                    ImprovementSignalKind.QUALITY_GAP
                ),
                gap_evidence_path=(
                    ".autodev/improvement/gap-evidence.json"
                ),
            )

    def test_success_alone_cannot_be_relabelled_as_actionable_gap(self) -> None:
        kwargs = base_kwargs()
        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "requires a gap signal kind",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=(
                    ImprovementSignalKind.RELEASE_FOLLOWUP
                ),
                gap_evidence_kind=(
                    ImprovementEvidenceKind.TELEMETRY
                ),
                gap_evidence_payload=gap_evidence(
                    ImprovementSignalKind.RELEASE_FOLLOWUP
                ),
                gap_evidence_path=(
                    ".autodev/improvement/telemetry.json"
                ),
            )

    def test_bound_recovery_evidence_can_create_runtime_gap(self) -> None:
        kwargs = base_kwargs()
        signal = extract_actionable_release_gap_signal(
            **kwargs,
            gap_kind=ImprovementSignalKind.RUNTIME_GAP,
            gap_evidence_kind=ImprovementEvidenceKind.RECOVERY,
            gap_evidence_payload=gap_evidence(
                ImprovementSignalKind.RUNTIME_GAP
            ),
            gap_evidence_path=(
                ".autodev/improvement/recovery-gap.json"
            ),
        )

        self.assertEqual(
            signal.kind,
            ImprovementSignalKind.RUNTIME_GAP,
        )
        self.assertIn("recovery", signal.tags)
        self.assertEqual(
            {ref.kind for ref in signal.evidence_refs},
            {
                ImprovementEvidenceKind.RELEASE_EVIDENCE,
                ImprovementEvidenceKind.POST_VERIFICATION,
                ImprovementEvidenceKind.RUNTIME_TARGET,
                ImprovementEvidenceKind.RECOVERY,
            },
        )

    def test_gap_envelope_is_strict_and_bound_to_release(self) -> None:
        kwargs = base_kwargs()
        payload = gap_evidence(
            ImprovementSignalKind.PERFORMANCE_GAP
        )
        payload["raw_telemetry"] = "provider supplied text"

        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "unknown trusted gap evidence fields",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.PERFORMANCE_GAP,
                gap_evidence_kind=(
                    ImprovementEvidenceKind.TELEMETRY
                ),
                gap_evidence_payload=payload,
                gap_evidence_path=(
                    ".autodev/improvement/performance.json"
                ),
            )

        payload = gap_evidence(
            ImprovementSignalKind.PERFORMANCE_GAP
        )
        payload["release_candidate_id"] = "release-different"
        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "release candidate drift",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.PERFORMANCE_GAP,
                gap_evidence_kind=(
                    ImprovementEvidenceKind.TELEMETRY
                ),
                gap_evidence_payload=payload,
                gap_evidence_path=(
                    ".autodev/improvement/performance.json"
                ),
            )

    def test_trusted_detail_code_preserves_semantic_goal(self) -> None:
        kwargs = base_kwargs()
        payload = gap_evidence(
            ImprovementSignalKind.QUALITY_GAP
        )
        payload["detail_code"] = (
            "variant-unicode-space-coverage-2005-2008"
        )
        signal = extract_actionable_release_gap_signal(
            **kwargs,
            gap_kind=ImprovementSignalKind.QUALITY_GAP,
            gap_evidence_kind=ImprovementEvidenceKind.TELEMETRY,
            gap_evidence_payload=payload,
            gap_evidence_path=(
                ".autodev/improvement/telemetry-gap.json"
            ),
        )
        self.assertIn("U+2005 FOUR-PER-EM SPACE", signal.statement)
        self.assertIn("U+2008 PUNCTUATION SPACE", signal.statement)
        self.assertIn("tests-only", signal.tags)
        self.assertIn("unicode-whitespace", signal.tags)

    def test_unknown_or_mismatched_detail_code_fails_closed(self) -> None:
        kwargs = base_kwargs()
        payload = gap_evidence(
            ImprovementSignalKind.QUALITY_GAP
        )
        payload["detail_code"] = "unknown-gap-detail"
        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "detail_code is unknown",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.QUALITY_GAP,
                gap_evidence_kind=ImprovementEvidenceKind.TELEMETRY,
                gap_evidence_payload=payload,
                gap_evidence_path=(
                    ".autodev/improvement/telemetry-gap.json"
                ),
            )

        payload["detail_code"] = (
            "variant-unicode-space-coverage-2005-2008"
        )
        with self.assertRaisesRegex(
            ImprovementSignalExtractionError,
            "signal kind drift",
        ):
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.RUNTIME_GAP,
                gap_evidence_kind=ImprovementEvidenceKind.TELEMETRY,
                gap_evidence_payload={
                    **payload,
                    "signal_kind": ImprovementSignalKind.RUNTIME_GAP.value,
                },
                gap_evidence_path=(
                    ".autodev/improvement/telemetry-gap.json"
                ),
            )


if __name__ == "__main__":
    unittest.main()
