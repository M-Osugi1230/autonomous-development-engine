from __future__ import annotations

import unittest

from ade.release_candidate import (
    ReleaseCandidate,
    ReleaseCandidateError,
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
    build_release_candidate_id,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "7" * 40
ACCEPTED_PLAN_FINGERPRINT = "a" * 64
CAMPAIGN_FINGERPRINT = "b" * 64
RUNTIME_FINGERPRINT = "c" * 64
REVIEW_FINGERPRINT = "d" * 64


def evidence_refs(
    *,
    include_review: bool = True,
) -> tuple[ReleaseEvidenceRef, ...]:
    items = [
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
            path=".autodev/accepted-plan.json",
            fingerprint=ACCEPTED_PLAN_FINGERPRINT,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.CAMPAIGN,
            path=".autodev/campaign.json",
            fingerprint=CAMPAIGN_FINGERPRINT,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
            path=".autodev/runtime-verification/task-001/report.json",
            fingerprint=RUNTIME_FINGERPRINT,
        ),
    ]
    if include_review:
        items.append(
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.REVIEW_CLEARANCE,
                path=".autodev/multi-agent/task-001/review-clearance.json",
                fingerprint=REVIEW_FINGERPRINT,
            )
        )
    return tuple(items)


def candidate(
    *,
    environment: ReleaseEnvironment = ReleaseEnvironment.STAGING,
    refs: tuple[ReleaseEvidenceRef, ...] | None = None,
) -> ReleaseCandidate:
    return build_release_candidate(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id="v1.8-release-campaign-001",
        accepted_plan_fingerprint=ACCEPTED_PLAN_FINGERPRINT,
        runtime_verification_id="rv-release-proof-001",
        target_environment=environment,
        evidence_refs=refs if refs is not None else evidence_refs(),
    )


class ReleaseCandidateTests(unittest.TestCase):
    def test_candidate_is_deterministic_and_authority_free(self) -> None:
        first = candidate(refs=evidence_refs())
        second = candidate(refs=tuple(reversed(evidence_refs())))

        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertTrue(first.requires_human_approval)

        payload = first.canonical_dict()
        self.assertTrue(payload["requires_human_approval"])
        for field in (
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
            "may_expand_scope",
            "may_mutate_acceptance",
        ):
            self.assertIs(payload[field], False)

        self.assertEqual(
            [item["kind"] for item in payload["evidence_refs"]],
            [
                "ACCEPTED_PLAN",
                "CAMPAIGN",
                "REVIEW_CLEARANCE",
                "RUNTIME_VERIFICATION",
            ],
        )

    def test_round_trip_preserves_fingerprint(self) -> None:
        original = candidate(environment=ReleaseEnvironment.PRODUCTION)
        restored = ReleaseCandidate.from_dict(original.canonical_dict())

        self.assertEqual(restored, original)
        self.assertEqual(restored.fingerprint(), original.fingerprint())

    def test_all_environments_remain_human_approval_gated(self) -> None:
        for environment in ReleaseEnvironment:
            with self.subTest(environment=environment):
                item = candidate(environment=environment)
                self.assertTrue(item.requires_human_approval)
                self.assertFalse(item.canonical_dict()["auto_promote"])

    def test_required_verified_evidence_cannot_be_omitted(self) -> None:
        refs = tuple(
            item
            for item in evidence_refs()
            if item.kind is not ReleaseEvidenceKind.RUNTIME_VERIFICATION
        )
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "missing required evidence",
        ):
            candidate(refs=refs)

    def test_duplicate_evidence_kind_is_rejected(self) -> None:
        refs = evidence_refs() + (
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.CAMPAIGN,
                path=".autodev/campaign-evidence/duplicate.json",
                fingerprint="e" * 64,
            ),
        )
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "duplicate release evidence kind",
        ):
            candidate(refs=refs)

    def test_untrusted_evidence_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "inside .autodev",
        ):
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.CAMPAIGN,
                path="ROADMAP.md",
                fingerprint=CAMPAIGN_FINGERPRINT,
            )

    def test_release_candidate_id_is_content_bound(self) -> None:
        refs = evidence_refs()
        expected = build_release_candidate_id(
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            campaign_id="v1.8-release-campaign-001",
            accepted_plan_fingerprint=ACCEPTED_PLAN_FINGERPRINT,
            runtime_verification_id="rv-release-proof-001",
            target_environment=ReleaseEnvironment.STAGING,
            evidence_refs=refs,
        )
        built = candidate(refs=refs)
        self.assertEqual(built.release_candidate_id, expected)

        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "does not match trusted content",
        ):
            ReleaseCandidate(
                release_candidate_id="release-wrong",
                repository=built.repository,
                source_sha=built.source_sha,
                campaign_id=built.campaign_id,
                accepted_plan_fingerprint=built.accepted_plan_fingerprint,
                runtime_verification_id=built.runtime_verification_id,
                target_environment=built.target_environment,
                evidence_refs=built.evidence_refs,
            )

    def test_serialized_authority_escalation_is_rejected(self) -> None:
        payload = candidate().canonical_dict()
        for field in (
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
            "may_expand_scope",
            "may_mutate_acceptance",
        ):
            changed = dict(payload)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ReleaseCandidateError):
                    ReleaseCandidate.from_dict(changed)

        changed = dict(payload)
        changed["requires_human_approval"] = False
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "must require human approval",
        ):
            ReleaseCandidate.from_dict(changed)

    def test_unknown_fields_and_schema_drift_fail_closed(self) -> None:
        payload = candidate().canonical_dict()
        changed = dict(payload)
        changed["provider_instruction"] = "deploy now"
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "unknown release candidate fields",
        ):
            ReleaseCandidate.from_dict(changed)

        changed = dict(payload)
        changed["schema_version"] = 2
        with self.assertRaisesRegex(
            ReleaseCandidateError,
            "unsupported release candidate schema version",
        ):
            ReleaseCandidate.from_dict(changed)


if __name__ == "__main__":
    unittest.main()
