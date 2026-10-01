from __future__ import annotations

import unittest

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignal,
    ImprovementSignalError,
    ImprovementSignalKind,
    build_improvement_signal,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_CANDIDATE_ID = "release-a4cd075b270b6ad434ae2602"


def evidence() -> tuple[ImprovementEvidenceRef, ...]:
    return (
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
    )


def signal():
    return build_improvement_signal(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        release_candidate_id=RELEASE_CANDIDATE_ID,
        release_environment="preview",
        kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
        statement=(
            "Review the verified preview release for one bounded "
            "evidence-backed improvement opportunity."
        ),
        evidence_refs=evidence(),
        tags=("release", "verified"),
    )


class ImprovementSignalTests(unittest.TestCase):
    def test_signal_is_deterministic_and_round_trips(self) -> None:
        first = signal()
        second = build_improvement_signal(
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            release_candidate_id=RELEASE_CANDIDATE_ID,
            release_environment="preview",
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement=(
                "Review the verified preview release for one bounded "
                "evidence-backed improvement opportunity."
            ),
            evidence_refs=tuple(reversed(evidence())),
            tags=("verified", "release"),
        )

        self.assertEqual(first.signal_id, second.signal_id)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(
            ImprovementSignal.from_dict(first.canonical_dict()),
            first,
        )
        self.assertTrue(first.signal_id.startswith("improve-"))
        self.assertEqual(first.generation, 0)
        self.assertIsNone(first.parent_signal_id)

    def test_signal_requires_verified_release_evidence(self) -> None:
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "missing required evidence",
        ):
            build_improvement_signal(
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                release_candidate_id=RELEASE_CANDIDATE_ID,
                release_environment="preview",
                kind=ImprovementSignalKind.QUALITY_GAP,
                statement="Investigate one bounded quality gap.",
                evidence_refs=(
                    ImprovementEvidenceRef(
                        kind=(
                            ImprovementEvidenceKind.RELEASE_EVIDENCE
                        ),
                        path=(
                            ".autodev/campaign-evidence/"
                            "v1.8-autonomous-release-proof-001.json"
                        ),
                        fingerprint="a" * 64,
                    ),
                ),
            )

    def test_duplicate_evidence_kind_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "duplicate improvement evidence kind",
        ):
            build_improvement_signal(
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                release_candidate_id=RELEASE_CANDIDATE_ID,
                release_environment="preview",
                kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
                statement="Review one bounded follow-up.",
                evidence_refs=evidence()
                + (
                    ImprovementEvidenceRef(
                        kind=(
                            ImprovementEvidenceKind.POST_VERIFICATION
                        ),
                        path=(
                            ".autodev/release/proof/final/"
                            "post-verification-report.json"
                        ),
                        fingerprint="c" * 64,
                    ),
                ),
            )

    def test_lineage_requires_parent_for_successors(self) -> None:
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "successor improvement signal requires parent_signal_id",
        ):
            build_improvement_signal(
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                release_candidate_id=RELEASE_CANDIDATE_ID,
                release_environment="preview",
                kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
                statement="Review one bounded successor.",
                evidence_refs=evidence(),
                generation=1,
            )

        root = signal()
        child = build_improvement_signal(
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            release_candidate_id=RELEASE_CANDIDATE_ID,
            release_environment="preview",
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate one bounded successor quality gap.",
            evidence_refs=evidence(),
            parent_signal_id=root.signal_id,
            generation=1,
            tags=("quality",),
        )
        self.assertEqual(child.parent_signal_id, root.signal_id)
        self.assertEqual(child.generation, 1)

    def test_lineage_depth_is_bounded(self) -> None:
        root = signal()
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "generation is outside trusted budget",
        ):
            build_improvement_signal(
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                release_candidate_id=RELEASE_CANDIDATE_ID,
                release_environment="preview",
                kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
                statement="Review one bounded successor.",
                evidence_refs=evidence(),
                parent_signal_id=root.signal_id,
                generation=17,
            )

    def test_statement_rejects_urls_and_secret_markers(self) -> None:
        for unsafe in (
            "Investigate https://example.com after release.",
            "Use ghp_12345678901234567890 to inspect the release.",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ImprovementSignalError):
                    build_improvement_signal(
                        repository=REPOSITORY,
                        source_sha=SOURCE_SHA,
                        release_candidate_id=RELEASE_CANDIDATE_ID,
                        release_environment="preview",
                        kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
                        statement=unsafe,
                        evidence_refs=evidence(),
                    )

    def test_evidence_must_remain_inside_autodev(self) -> None:
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "remain inside .autodev",
        ):
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path="docs/release.json",
                fingerprint="a" * 64,
            )

    def test_serialized_authority_escalation_fails_closed(self) -> None:
        payload = signal().canonical_dict()
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
            "scope_expansion_authority",
            "acceptance_mutation_authority",
            "human_decision_authority",
        ):
            with self.subTest(field=field):
                tampered = dict(payload)
                tampered[field] = True
                with self.assertRaisesRegex(
                    ImprovementSignalError,
                    "cannot grant",
                ):
                    ImprovementSignal.from_dict(tampered)

    def test_unknown_fields_and_content_id_drift_fail_closed(self) -> None:
        payload = signal().canonical_dict()

        with self.assertRaisesRegex(
            ImprovementSignalError,
            "unknown improvement signal fields",
        ):
            ImprovementSignal.from_dict(
                {**payload, "provider_priority": 999}
            )

        drifted = dict(payload)
        drifted["statement"] = "A different bounded statement."
        with self.assertRaisesRegex(
            ImprovementSignalError,
            "signal_id does not match trusted content",
        ):
            ImprovementSignal.from_dict(drifted)


if __name__ == "__main__":
    unittest.main()
