from __future__ import annotations

import unittest

from ade.release_candidate import (
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)
from ade.release_policy import (
    ReleasePolicyError,
    ReleasePromotionPolicy,
    plan_release_transition,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "9" * 40


def candidate(environment: ReleaseEnvironment):
    refs = (
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
            path=".autodev/accepted-plan.json",
            fingerprint="a" * 64,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.CAMPAIGN,
            path=".autodev/campaign.json",
            fingerprint="b" * 64,
        ),
        ReleaseEvidenceRef(
            kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
            path=".autodev/runtime-verification/release-001/report.json",
            fingerprint="c" * 64,
        ),
    )
    return build_release_candidate(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id="v1.8-release-campaign-001",
        accepted_plan_fingerprint="a" * 64,
        runtime_verification_id=f"rv-{SOURCE_SHA}",
        target_environment=environment,
        evidence_refs=refs,
    )


class ReleasePromotionPolicyTests(unittest.TestCase):
    def test_policy_is_fixed_and_authority_free(self) -> None:
        policy = ReleasePromotionPolicy()
        payload = policy.canonical_dict()

        self.assertEqual(
            payload["ordered_environments"],
            ["preview", "staging", "production"],
        )
        self.assertTrue(payload["human_approval_required"])
        self.assertFalse(payload["provider_selects_environment"])
        self.assertFalse(payload["deployment_authority"])
        self.assertFalse(payload["promotion_authority"])
        self.assertFalse(payload["auto_promote"])
        self.assertEqual(
            ReleasePromotionPolicy.from_dict(payload),
            policy,
        )

    def test_legal_sequence_is_preview_staging_production(self) -> None:
        preview = plan_release_transition(
            candidate=candidate(ReleaseEnvironment.PREVIEW),
            current_verified_environment=None,
        )
        staging = plan_release_transition(
            candidate=candidate(ReleaseEnvironment.STAGING),
            current_verified_environment=ReleaseEnvironment.PREVIEW,
        )
        production = plan_release_transition(
            candidate=candidate(ReleaseEnvironment.PRODUCTION),
            current_verified_environment=ReleaseEnvironment.STAGING,
        )

        self.assertEqual(preview.from_environment, None)
        self.assertEqual(preview.to_environment, ReleaseEnvironment.PREVIEW)
        self.assertEqual(staging.from_environment, ReleaseEnvironment.PREVIEW)
        self.assertEqual(staging.to_environment, ReleaseEnvironment.STAGING)
        self.assertEqual(
            production.from_environment,
            ReleaseEnvironment.STAGING,
        )
        self.assertEqual(
            production.to_environment,
            ReleaseEnvironment.PRODUCTION,
        )
        for plan in (preview, staging, production):
            self.assertTrue(plan.requires_human_approval)
            payload = plan.canonical_dict()
            self.assertFalse(payload["deployment_authority"])
            self.assertFalse(payload["promotion_authority"])
            self.assertFalse(payload["auto_promote"])

    def test_transition_is_deterministic(self) -> None:
        first = plan_release_transition(
            candidate=candidate(ReleaseEnvironment.STAGING),
            current_verified_environment=ReleaseEnvironment.PREVIEW,
        )
        second = plan_release_transition(
            candidate=candidate(ReleaseEnvironment.STAGING),
            current_verified_environment=ReleaseEnvironment.PREVIEW,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_skipping_or_wrong_target_environment_fails_closed(self) -> None:
        cases = (
            (ReleaseEnvironment.STAGING, None),
            (ReleaseEnvironment.PRODUCTION, None),
            (ReleaseEnvironment.PRODUCTION, ReleaseEnvironment.PREVIEW),
            (ReleaseEnvironment.PREVIEW, ReleaseEnvironment.PREVIEW),
            (ReleaseEnvironment.STAGING, ReleaseEnvironment.STAGING),
        )
        for target, current in cases:
            with self.subTest(target=target, current=current):
                with self.assertRaisesRegex(
                    ReleasePolicyError,
                    "next trusted environment",
                ):
                    plan_release_transition(
                        candidate=candidate(target),
                        current_verified_environment=current,
                    )

    def test_production_is_terminal(self) -> None:
        with self.assertRaisesRegex(
            ReleasePolicyError,
            "production is terminal",
        ):
            plan_release_transition(
                candidate=candidate(ReleaseEnvironment.PRODUCTION),
                current_verified_environment=ReleaseEnvironment.PRODUCTION,
            )

    def test_policy_order_cannot_be_rewritten(self) -> None:
        with self.assertRaisesRegex(
            ReleasePolicyError,
            "controller-owned",
        ):
            ReleasePromotionPolicy(
                ordered_environments=(
                    ReleaseEnvironment.PRODUCTION,
                    ReleaseEnvironment.STAGING,
                    ReleaseEnvironment.PREVIEW,
                )
            )

        payload = ReleasePromotionPolicy().canonical_dict()
        changed = dict(payload)
        changed["ordered_environments"] = [
            "production",
            "staging",
            "preview",
        ]
        with self.assertRaises(ReleasePolicyError):
            ReleasePromotionPolicy.from_dict(changed)

    def test_serialized_authority_escalation_fails_closed(self) -> None:
        payload = ReleasePromotionPolicy().canonical_dict()
        for field in (
            "provider_selects_environment",
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
        ):
            changed = dict(payload)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ReleasePolicyError):
                    ReleasePromotionPolicy.from_dict(changed)

        changed = dict(payload)
        changed["human_approval_required"] = False
        with self.assertRaisesRegex(
            ReleasePolicyError,
            "must require human approval",
        ):
            ReleasePromotionPolicy.from_dict(changed)


if __name__ == "__main__":
    unittest.main()
