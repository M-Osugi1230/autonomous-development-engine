from __future__ import annotations

import tempfile
from pathlib import Path

from ade.decision_store import DecisionStore
from ade.decisions import DecisionResponse
from ade.human_interrupt import HumanInterruptCoordinator
from ade.release_approval import (
    ReleaseApprovalDisposition,
    ReleaseApprovalError,
    build_release_approval_request,
    evaluate_release_approval,
    request_release_approval,
)
from ade.release_candidate import (
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)
from ade.release_policy import plan_release_transition


def _candidate(environment: ReleaseEnvironment):
    source_sha = "a" * 40
    return build_release_candidate(
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha=source_sha,
        campaign_id="v1.8-release-approval-probe-001",
        accepted_plan_fingerprint="1" * 64,
        runtime_verification_id=f"rv-{source_sha}",
        target_environment=environment,
        evidence_refs=(
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
                path=".autodev/accepted-plan.json",
                fingerprint="1" * 64,
            ),
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.CAMPAIGN,
                path=".autodev/campaign.json",
                fingerprint="2" * 64,
            ),
            ReleaseEvidenceRef(
                kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
                path=".autodev/runtime-verification/release-001/report.json",
                fingerprint="3" * 64,
            ),
        ),
    )


def main() -> None:
    transition = plan_release_transition(
        candidate=_candidate(ReleaseEnvironment.PREVIEW),
        current_verified_environment=None,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        store = DecisionStore(Path(temp_dir) / "decisions.json")
        coordinator = HumanInterruptCoordinator(store)

        waiting = request_release_approval(
            coordinator=coordinator,
            transition=transition,
        )
        assert waiting.disposition is ReleaseApprovalDisposition.HUMAN_WAIT
        assert waiting.approval_satisfied is False
        assert len(store.list_open()) == 1

        repeated = request_release_approval(
            coordinator=coordinator,
            transition=transition,
        )
        assert repeated == waiting
        assert len(store.load()) == 1

        request = build_release_approval_request(transition)
        record = coordinator.resolve(
            request.decision_id,
            DecisionResponse(
                decision_id=request.decision_id,
                text="Approve this exact promotion.",
                selected_option="approve",
            ),
        )
        approved = evaluate_release_approval(
            transition=transition,
            record=record,
        )
        assert approved.disposition is ReleaseApprovalDisposition.APPROVED
        assert approved.approval_satisfied is True
        assert approved.canonical_dict()["deployment_authority"] is False
        assert approved.canonical_dict()["promotion_authority"] is False

        staging = plan_release_transition(
            candidate=_candidate(ReleaseEnvironment.STAGING),
            current_verified_environment=ReleaseEnvironment.PREVIEW,
        )
        try:
            evaluate_release_approval(
                transition=staging,
                record=record,
            )
        except ReleaseApprovalError:
            pass
        else:
            raise AssertionError(
                "approval for one transition must not approve another"
            )

        print(
            {
                "schema_version": 1,
                "proof": "v1.8-release-human-approval-gate",
                "decision_id": approved.decision_id,
                "transition_id": approved.transition_id,
                "transition_fingerprint": approved.transition_fingerprint,
                "disposition": approved.disposition.value,
                "approval_satisfied": approved.approval_satisfied,
                "deployment_authority": False,
                "promotion_authority": False,
            }
        )


if __name__ == "__main__":
    main()
