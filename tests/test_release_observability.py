from __future__ import annotations

from dataclasses import replace
import unittest

from ade.recovery import RecoveryFailure
from ade.recovery_runtime import advance_recovery
from ade.release_approval import (
    ReleaseApprovalDecision,
    ReleaseApprovalDisposition,
)
from ade.release_candidate import (
    ReleaseEnvironment,
    ReleaseEvidenceKind,
    ReleaseEvidenceRef,
    build_release_candidate,
)
from ade.release_deployment import (
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
)
from ade.release_observability import (
    ReleaseApprovalViewState,
    ReleaseContainmentViewState,
    ReleaseDeploymentViewState,
    ReleaseObservabilityError,
    ReleaseObservabilitySnapshot,
    ReleasePromotionViewState,
    ReleaseVerificationViewState,
    build_release_observability_snapshot,
)
from ade.release_policy import plan_release_transition
from ade.release_post_verification import (
    ReleasePostVerificationDisposition,
    ReleasePostVerificationFinalization,
    ReleasePostVerificationOutcome,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "d" * 40


def candidate():
    return build_release_candidate(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id="v1.8-release-observability-001",
        accepted_plan_fingerprint="1" * 64,
        runtime_verification_id=f"rv-{SOURCE_SHA}",
        target_environment=ReleaseEnvironment.PREVIEW,
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
                path=".autodev/runtime-verification/task-final/report.json",
                fingerprint="3" * 64,
            ),
        ),
    )


def transition():
    return plan_release_transition(
        candidate=candidate(),
        current_verified_environment=None,
    )


def approval(
    disposition: ReleaseApprovalDisposition = ReleaseApprovalDisposition.APPROVED,
):
    item = transition()
    selected = {
        ReleaseApprovalDisposition.APPROVED: "approve",
        ReleaseApprovalDisposition.REJECTED: "reject",
        ReleaseApprovalDisposition.HUMAN_WAIT: None,
    }[disposition]
    return ReleaseApprovalDecision(
        decision_id="release-approval-" + item.fingerprint()[:24],
        transition_id=item.transition_id,
        transition_fingerprint=item.fingerprint(),
        disposition=disposition,
        selected_option=selected,
    )


def deployment_receipt(
    status: ReleaseDeploymentStatus,
) -> ReleaseDeploymentReceipt:
    item = transition()
    approved = approval()
    return ReleaseDeploymentReceipt(
        deployment_request_id="deployment-observability-001",
        idempotency_key="ade-release-observability-001",
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        environment=ReleaseEnvironment.PREVIEW,
        transition_id=item.transition_id,
        transition_fingerprint=item.fingerprint(),
        approval_fingerprint=approved.fingerprint(),
        adapter_implementation_id="trusted-preview-adapter-v1",
        registry_fingerprint="4" * 64,
        status=status,
        dispatch_count=0 if status is ReleaseDeploymentStatus.ARMED else 1,
        deployment_id=(
            "dep-preview-observability-001"
            if status is ReleaseDeploymentStatus.DEPLOYED
            else None
        ),
        observation_fingerprint=(
            "5" * 64
            if status is ReleaseDeploymentStatus.DEPLOYED
            else None
        ),
    )


def runtime_receipt(status: str) -> RuntimeVerificationReceipt:
    return RuntimeVerificationReceipt(
        verification_id="release-rv-observability-001",
        task_id="task-final",
        target_repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        contract_fingerprint="6" * 64,
        registry_fingerprint="7" * 64,
        policy_fingerprint="8" * 64,
        status=status,
        dispatch_count=1,
    )


def finalization(
    disposition: ReleasePostVerificationDisposition,
) -> ReleasePostVerificationFinalization:
    outcome = ReleasePostVerificationOutcome(
        binding_fingerprint="9" * 64,
        target_evidence_fingerprint="a" * 64,
        runtime_report_fingerprint="b" * 64,
        disposition=disposition,
        deployment_id="dep-preview-observability-001",
        environment=ReleaseEnvironment.PREVIEW,
        failure_fingerprint=(
            "c" * 64
            if disposition is ReleasePostVerificationDisposition.HUMAN_WAIT
            else None
        ),
    )
    if disposition is ReleasePostVerificationDisposition.VERIFIED:
        receipt_status = "VERIFIED"
        recovery = None
    elif disposition is ReleasePostVerificationDisposition.PENDING:
        receipt_status = "DISPATCHED"
        recovery = None
    else:
        receipt_status = "HUMAN_WAIT"
        recovery = advance_recovery(
            "task-final",
            RecoveryFailure.RUNTIME_VERIFICATION,
            "c" * 64,
            None,
        )
    return ReleasePostVerificationFinalization(
        outcome=outcome,
        receipt=runtime_receipt(receipt_status),
        state={"status": "READY"},
        campaign={"status": "COMPLETED"},
        recovery=recovery,
    )


class ReleaseObservabilityTests(unittest.TestCase):
    def test_candidate_only_projection_is_safe_and_minimal(self) -> None:
        snapshot = build_release_observability_snapshot(
            candidate=candidate(),
        )
        self.assertEqual(
            snapshot.promotion_state,
            ReleasePromotionViewState.CANDIDATE_READY,
        )
        self.assertEqual(
            snapshot.approval_state,
            ReleaseApprovalViewState.NOT_REQUESTED,
        )
        self.assertEqual(
            snapshot.deployment_state,
            ReleaseDeploymentViewState.NOT_STARTED,
        )
        self.assertEqual(
            snapshot.verification_state,
            ReleaseVerificationViewState.NOT_STARTED,
        )
        self.assertEqual(
            snapshot.containment_state,
            ReleaseContainmentViewState.NONE,
        )
        self.assertFalse(snapshot.deployment_identity_present)
        payload = snapshot.canonical_dict()
        serialized_keys = set(payload)
        self.assertNotIn("deployment_id", serialized_keys)
        self.assertNotIn("decision_context", serialized_keys)
        self.assertNotIn("idempotency_key", serialized_keys)
        self.assertNotIn("adapter_implementation_id", serialized_keys)

    def test_transition_and_human_wait_approval_are_visible(self) -> None:
        waiting = build_release_observability_snapshot(
            candidate=candidate(),
            transition=transition(),
            approval=approval(ReleaseApprovalDisposition.HUMAN_WAIT),
        )
        self.assertEqual(
            waiting.approval_state,
            ReleaseApprovalViewState.HUMAN_WAIT,
        )
        self.assertEqual(
            waiting.promotion_state,
            ReleasePromotionViewState.AWAITING_APPROVAL,
        )
        self.assertEqual(
            waiting.next_required_human_action,
            "review-release-promotion-approval",
        )

        rejected = build_release_observability_snapshot(
            candidate=candidate(),
            transition=transition(),
            approval=approval(ReleaseApprovalDisposition.REJECTED),
        )
        self.assertEqual(
            rejected.approval_state,
            ReleaseApprovalViewState.REJECTED,
        )
        self.assertEqual(
            rejected.promotion_state,
            ReleasePromotionViewState.REJECTED,
        )

    def test_deployment_lifecycle_is_visible_without_deployment_id(self) -> None:
        expected = {
            ReleaseDeploymentStatus.ARMED: (
                ReleaseDeploymentViewState.ARMED,
                ReleasePromotionViewState.DEPLOYMENT_ARMED,
                False,
            ),
            ReleaseDeploymentStatus.DISPATCHED: (
                ReleaseDeploymentViewState.DISPATCHED,
                ReleasePromotionViewState.DEPLOYING,
                False,
            ),
            ReleaseDeploymentStatus.DEPLOYED: (
                ReleaseDeploymentViewState.DEPLOYED,
                ReleasePromotionViewState.DEPLOYED_AWAITING_VERIFICATION,
                True,
            ),
        }
        for status, states in expected.items():
            with self.subTest(status=status):
                snapshot = build_release_observability_snapshot(
                    candidate=candidate(),
                    transition=transition(),
                    approval=approval(),
                    deployment_receipt=deployment_receipt(status),
                )
                self.assertEqual(snapshot.deployment_state, states[0])
                self.assertEqual(snapshot.promotion_state, states[1])
                self.assertEqual(
                    snapshot.deployment_identity_present,
                    states[2],
                )
                self.assertNotIn(
                    "dep-preview-observability-001",
                    str(snapshot.canonical_dict()),
                )

    def test_verified_post_verification_is_visible(self) -> None:
        snapshot = build_release_observability_snapshot(
            candidate=candidate(),
            transition=transition(),
            approval=approval(),
            deployment_receipt=deployment_receipt(
                ReleaseDeploymentStatus.DEPLOYED
            ),
            finalization=finalization(
                ReleasePostVerificationDisposition.VERIFIED
            ),
        )
        self.assertEqual(
            snapshot.promotion_state,
            ReleasePromotionViewState.VERIFIED,
        )
        self.assertEqual(
            snapshot.verification_state,
            ReleaseVerificationViewState.VERIFIED,
        )
        self.assertEqual(
            snapshot.containment_state,
            ReleaseContainmentViewState.NONE,
        )
        self.assertTrue(snapshot.deployment_identity_present)
        self.assertIsNone(snapshot.next_required_human_action)

    def test_failed_post_verification_exposes_containment_not_raw_failure(self) -> None:
        snapshot = build_release_observability_snapshot(
            candidate=candidate(),
            transition=transition(),
            approval=approval(),
            deployment_receipt=deployment_receipt(
                ReleaseDeploymentStatus.DEPLOYED
            ),
            finalization=finalization(
                ReleasePostVerificationDisposition.HUMAN_WAIT
            ),
        )
        self.assertEqual(
            snapshot.promotion_state,
            ReleasePromotionViewState.HUMAN_WAIT,
        )
        self.assertEqual(
            snapshot.verification_state,
            ReleaseVerificationViewState.HUMAN_WAIT,
        )
        self.assertEqual(
            snapshot.containment_state,
            ReleaseContainmentViewState.HUMAN_WAIT,
        )
        self.assertEqual(
            snapshot.next_required_human_action,
            "review-release-runtime-verification-failure",
        )
        payload = snapshot.canonical_dict()
        self.assertNotIn("failure_fingerprint", payload)
        self.assertNotIn("recovery", payload)

    def test_cross_release_evidence_drift_fails_closed(self) -> None:
        item = transition()
        changed_candidate = build_release_candidate(
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            campaign_id="v1.8-release-observability-other",
            accepted_plan_fingerprint="f" * 64,
            runtime_verification_id=f"rv-{SOURCE_SHA}",
            target_environment=ReleaseEnvironment.PREVIEW,
            evidence_refs=(
                ReleaseEvidenceRef(
                    kind=ReleaseEvidenceKind.ACCEPTED_PLAN,
                    path=".autodev/accepted-plan.json",
                    fingerprint="f" * 64,
                ),
                ReleaseEvidenceRef(
                    kind=ReleaseEvidenceKind.CAMPAIGN,
                    path=".autodev/campaign.json",
                    fingerprint="2" * 64,
                ),
                ReleaseEvidenceRef(
                    kind=ReleaseEvidenceKind.RUNTIME_VERIFICATION,
                    path=(
                        ".autodev/runtime-verification/"
                        "task-final/report.json"
                    ),
                    fingerprint="3" * 64,
                ),
            ),
        )
        with self.assertRaisesRegex(
            ReleaseObservabilityError,
            "release candidate id drift",
        ):
            build_release_observability_snapshot(
                candidate=changed_candidate,
                transition=item,
            )

        changed_receipt = replace(
            deployment_receipt(ReleaseDeploymentStatus.DEPLOYED),
            source_sha="e" * 40,
        )
        with self.assertRaisesRegex(
            ReleaseObservabilityError,
            "deployment source SHA drift",
        ):
            build_release_observability_snapshot(
                candidate=candidate(),
                transition=item,
                approval=approval(),
                deployment_receipt=changed_receipt,
            )

    def test_persisted_projection_rejects_unknown_or_secret_like_fields(self) -> None:
        payload = build_release_observability_snapshot(
            candidate=candidate(),
        ).canonical_dict()
        restored = ReleaseObservabilitySnapshot.from_dict(payload)
        self.assertEqual(restored, build_release_observability_snapshot(
            candidate=candidate(),
        ))

        unknown = dict(payload)
        unknown["deployment_token"] = "secret"
        with self.assertRaisesRegex(
            ReleaseObservabilityError,
            "unknown release observability fields",
        ):
            ReleaseObservabilitySnapshot.from_dict(unknown)

        secret_like = dict(payload)
        secret_like["release_candidate_id"] = "ghp_1234567890"
        with self.assertRaisesRegex(
            ReleaseObservabilityError,
            "secret-like marker",
        ):
            ReleaseObservabilitySnapshot.from_dict(secret_like)


if __name__ == "__main__":
    unittest.main()
