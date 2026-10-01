from __future__ import annotations

import json
import unittest
from pathlib import Path

from ade.decisions import DecisionRecord
from ade.release_approval import (
    ReleaseApprovalDisposition,
    evaluate_release_approval,
)
from ade.release_candidate import ReleaseEnvironment
from ade.release_deployment import (
    ReleaseDeploymentAdapterRegistration,
    ReleaseDeploymentObservation,
    TrustedReleaseDeploymentRegistry,
    arm_release_deployment,
    record_release_deployment_dispatch,
)
from ade.release_policy import ReleaseTransitionPlan


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / ".autodev" / "release" / "proof"


def load_json(name: str):
    with (PROOF / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def transition_from_payload(payload: dict) -> ReleaseTransitionPlan:
    return ReleaseTransitionPlan(
        transition_id=payload["transition_id"],
        release_candidate_id=payload["release_candidate_id"],
        release_candidate_fingerprint=payload[
            "release_candidate_fingerprint"
        ],
        repository=payload["repository"],
        source_sha=payload["source_sha"],
        from_environment=(
            ReleaseEnvironment(payload["from_environment"])
            if payload["from_environment"] is not None
            else None
        ),
        to_environment=ReleaseEnvironment(
            payload["to_environment"]
        ),
        policy_fingerprint=payload["policy_fingerprint"],
    )


class V18ReleaseApprovedDispatchTests(unittest.TestCase):
    def test_explicit_human_approval_reconstructs_exact_dispatch(self) -> None:
        human_input = load_json("human-approval-input.json")
        self.assertEqual(
            human_input,
            {
                "schema_version": 1,
                "decision_id": (
                    "release-approval-ea7386c7ca3d03d5d54fb3f7"
                ),
                "selected_option": "approve",
                "response_text": "approve",
                "provenance": "explicit-user-approval",
                "transition_id": (
                    "promotion-ec00d85452f6e71181590bdb"
                ),
                "transition_fingerprint": (
                    "ea7386c7ca3d03d5d54fb3f7dd84292"
                    "a5f2fadb0a900eb9467f857d2f38e10d9"
                ),
                "release_candidate_id": (
                    "release-a4cd075b270b6ad434ae2602"
                ),
                "source_sha": (
                    "726431b60db8b25cdd4bc15bb1493a0060f36327"
                ),
                "target_environment": "preview",
            },
        )

        transition = transition_from_payload(
            load_json("transition.json")
        )
        decision = DecisionRecord.from_dict(
            load_json("decision-record.json")
        )
        approval = evaluate_release_approval(
            transition=transition,
            record=decision,
        )
        self.assertEqual(
            approval.disposition,
            ReleaseApprovalDisposition.APPROVED,
        )
        self.assertTrue(approval.approval_satisfied)
        self.assertEqual(approval.selected_option, "approve")
        self.assertEqual(
            approval.canonical_dict(),
            load_json("approval.json"),
        )
        self.assertEqual(
            approval.fingerprint(),
            "d54edd1dbdba8e7ded1506a5fd52a720"
            "4a758c43828d0bdf79e2f18573ab22d1",
        )

        def forbidden_execution(_):
            raise AssertionError(
                "dispatch proof must not execute external deployment"
            )

        registration = ReleaseDeploymentAdapterRegistration(
            repository=transition.repository,
            environment=transition.to_environment,
            implementation_id="github-preview-ref-v1",
            deployer=forbidden_execution,
        )
        registry = TrustedReleaseDeploymentRegistry(
            (registration,)
        )
        self.assertEqual(
            registry.canonical_dict(),
            load_json("deployment-registry.json"),
        )
        self.assertEqual(
            registry.fingerprint(),
            "5f0d1ca69e2ff6e0bd9cde384329c727"
            "bc7c52c54b354423f98a10ccb4b459da",
        )

        activation = arm_release_deployment(
            transition=transition,
            approval=approval,
            registry=registry,
        )
        self.assertTrue(activation.should_dispatch)
        self.assertEqual(
            activation.invocation.canonical_dict(),
            load_json("deployment-invocation.json"),
        )
        dispatched = record_release_deployment_dispatch(
            invocation=activation.invocation,
            receipt=activation.receipt,
        )
        self.assertTrue(dispatched.changed)
        self.assertEqual(
            dispatched.receipt.canonical_dict(),
            load_json("deployment-receipt.json"),
        )
        self.assertEqual(
            dispatched.receipt.fingerprint(),
            "1248351016d1fe7d58dae72bf83e80dc"
            "fffe1705ed8f271f30907daff8c6588c",
        )

    def test_dispatch_is_exactly_preview_and_has_not_executed_yet(self) -> None:
        invocation = load_json("deployment-invocation.json")
        receipt = load_json("deployment-receipt.json")
        state = load_json("state.json")

        self.assertEqual(
            invocation["repository"],
            "M-Osugi1230/one-minute-thought-experiments",
        )
        self.assertEqual(
            invocation["source_sha"],
            "726431b60db8b25cdd4bc15bb1493a0060f36327",
        )
        self.assertEqual(invocation["environment"], "preview")
        self.assertFalse(invocation["provider_defined"])
        self.assertFalse(invocation["contains_credentials"])

        self.assertEqual(receipt["status"], "DISPATCHED")
        self.assertEqual(receipt["dispatch_count"], 1)
        self.assertIsNone(receipt["deployment_id"])
        self.assertIsNone(receipt["observation_fingerprint"])

        self.assertEqual(
            state["state"],
            "DEPLOYMENT_DISPATCHED",
        )
        self.assertEqual(
            state["approval_disposition"],
            "APPROVED",
        )
        self.assertFalse(
            state["external_side_effect_executed"]
        )
        self.assertFalse(state["auto_promote"])
        self.assertFalse(state["deployment_authority"])
        self.assertFalse(state["promotion_authority"])


if __name__ == "__main__":
    unittest.main()
