from __future__ import annotations

import tempfile
import unittest
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


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40


def candidate(environment: ReleaseEnvironment):
    return build_release_candidate(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id="v1.8-release-campaign-001",
        accepted_plan_fingerprint="1" * 64,
        runtime_verification_id=f"rv-{SOURCE_SHA}",
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


def preview_transition():
    return plan_release_transition(
        candidate=candidate(ReleaseEnvironment.PREVIEW),
        current_verified_environment=None,
    )


def staging_transition():
    return plan_release_transition(
        candidate=candidate(ReleaseEnvironment.STAGING),
        current_verified_environment=ReleaseEnvironment.PREVIEW,
    )


class ReleaseApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = DecisionStore(
            Path(self.temp_dir.name) / "decisions.json"
        )
        self.coordinator = HumanInterruptCoordinator(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_request_is_exactly_bound_and_human_wait(self) -> None:
        transition = preview_transition()
        request = build_release_approval_request(transition)

        self.assertEqual(
            request.decision_id,
            "release-approval-" + transition.fingerprint()[:24],
        )
        self.assertEqual(request.options, ("approve", "reject"))
        self.assertEqual(
            request.blocking_task_id,
            transition.transition_id,
        )
        self.assertEqual(
            request.context["transition_fingerprint"],
            transition.fingerprint(),
        )
        self.assertEqual(
            request.context["release_candidate_fingerprint"],
            transition.release_candidate_fingerprint,
        )
        self.assertFalse(request.context["deployment_authority"])
        self.assertFalse(request.context["promotion_authority"])
        self.assertFalse(request.context["auto_promote"])

        gate = request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        self.assertEqual(
            gate.disposition,
            ReleaseApprovalDisposition.HUMAN_WAIT,
        )
        self.assertFalse(gate.approval_satisfied)
        self.assertEqual(len(self.store.list_open()), 1)

    def test_repeated_request_is_idempotent(self) -> None:
        transition = preview_transition()
        first = request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        second = request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.store.load()), 1)

    def test_explicit_approve_satisfies_gate_without_authority(self) -> None:
        transition = preview_transition()
        request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        request = build_release_approval_request(transition)
        record = self.coordinator.resolve(
            request.decision_id,
            DecisionResponse(
                decision_id=request.decision_id,
                text="Approve this exact release transition.",
                selected_option="approve",
            ),
        )

        result = evaluate_release_approval(
            transition=transition,
            record=record,
        )
        self.assertEqual(
            result.disposition,
            ReleaseApprovalDisposition.APPROVED,
        )
        self.assertTrue(result.approval_satisfied)
        payload = result.canonical_dict()
        self.assertFalse(payload["deployment_authority"])
        self.assertFalse(payload["promotion_authority"])
        self.assertFalse(payload["auto_promote"])

    def test_explicit_reject_blocks_gate(self) -> None:
        transition = preview_transition()
        request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        request = build_release_approval_request(transition)
        record = self.coordinator.resolve(
            request.decision_id,
            DecisionResponse(
                decision_id=request.decision_id,
                text="Reject this release transition.",
                selected_option="reject",
            ),
        )

        result = evaluate_release_approval(
            transition=transition,
            record=record,
        )
        self.assertEqual(
            result.disposition,
            ReleaseApprovalDisposition.REJECTED,
        )
        self.assertFalse(result.approval_satisfied)

    def test_free_text_resolution_is_not_approval(self) -> None:
        transition = preview_transition()
        request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        request = build_release_approval_request(transition)
        record = self.coordinator.resolve(
            request.decision_id,
            DecisionResponse(
                decision_id=request.decision_id,
                text="Looks fine to me.",
                selected_option=None,
            ),
        )

        with self.assertRaisesRegex(
            ReleaseApprovalError,
            "explicit approve or reject",
        ):
            evaluate_release_approval(
                transition=transition,
                record=record,
            )

    def test_approval_for_one_transition_cannot_approve_another(self) -> None:
        first = preview_transition()
        request_release_approval(
            coordinator=self.coordinator,
            transition=first,
        )
        request = build_release_approval_request(first)
        record = self.coordinator.resolve(
            request.decision_id,
            DecisionResponse(
                decision_id=request.decision_id,
                text="Approve preview.",
                selected_option="approve",
            ),
        )

        with self.assertRaisesRegex(
            ReleaseApprovalError,
            "does not match exact release transition",
        ):
            evaluate_release_approval(
                transition=staging_transition(),
                record=record,
            )

    def test_open_record_remains_human_wait(self) -> None:
        transition = preview_transition()
        request_release_approval(
            coordinator=self.coordinator,
            transition=transition,
        )
        record = self.store.get(
            build_release_approval_request(transition).decision_id
        )
        self.assertIsNotNone(record)
        result = evaluate_release_approval(
            transition=transition,
            record=record,
        )
        self.assertEqual(
            result.disposition,
            ReleaseApprovalDisposition.HUMAN_WAIT,
        )
        self.assertFalse(result.approval_satisfied)


if __name__ == "__main__":
    unittest.main()
