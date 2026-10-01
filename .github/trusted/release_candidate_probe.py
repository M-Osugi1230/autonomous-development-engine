from __future__ import annotations

from ade.release_candidate import (
    ReleaseCandidate,
    ReleaseCandidateError,
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)


def main() -> None:
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
            path=".autodev/runtime-verification/probe/report.json",
            fingerprint="c" * 64,
        ),
    )
    candidate = build_release_candidate(
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha="7" * 40,
        campaign_id="v1.8-release-probe-001",
        accepted_plan_fingerprint="a" * 64,
        runtime_verification_id="rv-release-probe-001",
        target_environment=ReleaseEnvironment.STAGING,
        evidence_refs=refs,
    )
    payload = candidate.canonical_dict()
    assert payload["requires_human_approval"] is True
    assert payload["deployment_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["auto_promote"] is False
    assert payload["may_expand_scope"] is False
    assert payload["may_mutate_acceptance"] is False
    assert ReleaseCandidate.from_dict(payload).fingerprint() == candidate.fingerprint()

    escalated = dict(payload)
    escalated["promotion_authority"] = True
    try:
        ReleaseCandidate.from_dict(escalated)
    except ReleaseCandidateError:
        pass
    else:
        raise AssertionError("promotion authority escalation must fail closed")

    missing_runtime = dict(payload)
    missing_runtime["evidence_refs"] = [
        item
        for item in payload["evidence_refs"]
        if item["kind"] != ReleaseEvidenceKind.RUNTIME_VERIFICATION.value
    ]
    try:
        ReleaseCandidate.from_dict(missing_runtime)
    except ReleaseCandidateError:
        pass
    else:
        raise AssertionError("runtime verification evidence is mandatory")

    print(
        {
            "schema_version": 1,
            "proof": "v1.8-release-candidate-foundation",
            "candidate_id": candidate.release_candidate_id,
            "candidate_fingerprint": candidate.fingerprint(),
            "target_environment": candidate.target_environment.value,
            "requires_human_approval": candidate.requires_human_approval,
            "authority_free": True,
        }
    )


if __name__ == "__main__":
    main()
