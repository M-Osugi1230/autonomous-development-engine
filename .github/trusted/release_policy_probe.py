from __future__ import annotations

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


def _candidate(environment: ReleaseEnvironment):
    source_sha = "9" * 40
    return build_release_candidate(
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha=source_sha,
        campaign_id="v1.8-release-policy-probe-001",
        accepted_plan_fingerprint="a" * 64,
        runtime_verification_id=f"rv-{source_sha}",
        target_environment=environment,
        evidence_refs=(
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
        ),
    )


def main() -> None:
    policy = ReleasePromotionPolicy()
    preview = plan_release_transition(
        candidate=_candidate(ReleaseEnvironment.PREVIEW),
        current_verified_environment=None,
        policy=policy,
    )
    staging = plan_release_transition(
        candidate=_candidate(ReleaseEnvironment.STAGING),
        current_verified_environment=ReleaseEnvironment.PREVIEW,
        policy=policy,
    )
    production = plan_release_transition(
        candidate=_candidate(ReleaseEnvironment.PRODUCTION),
        current_verified_environment=ReleaseEnvironment.STAGING,
        policy=policy,
    )
    assert [item.to_environment.value for item in (preview, staging, production)] == [
        "preview",
        "staging",
        "production",
    ]
    assert all(item.requires_human_approval for item in (preview, staging, production))
    assert all(
        item.canonical_dict()["promotion_authority"] is False
        for item in (preview, staging, production)
    )

    try:
        plan_release_transition(
            candidate=_candidate(ReleaseEnvironment.PRODUCTION),
            current_verified_environment=ReleaseEnvironment.PREVIEW,
            policy=policy,
        )
    except ReleasePolicyError:
        pass
    else:
        raise AssertionError("environment skipping must fail closed")

    print(
        {
            "schema_version": 1,
            "proof": "v1.8-release-promotion-policy",
            "policy_fingerprint": policy.fingerprint(),
            "ordered_environments": [
                item.value for item in policy.ordered_environments
            ],
            "human_approval_required": True,
            "promotion_authority": False,
        }
    )


if __name__ == "__main__":
    main()
