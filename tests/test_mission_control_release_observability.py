from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    ActivityStore,
    DecisionStore,
    ReleaseApprovalViewState,
    ReleaseContainmentViewState,
    ReleaseDeploymentViewState,
    ReleaseEnvironment,
    ReleaseObservabilitySnapshot,
    ReleasePromotionViewState,
    ReleaseVerificationViewState,
    build_mission_control_snapshot,
    render_mission_control,
)


SOURCE_SHA = "e" * 40


class MissionControlReleaseObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "repo"
        self.autodev = self.root / ".autodev"
        self.autodev.mkdir(parents=True)
        self._write_base()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: object) -> None:
        path = self.autodev / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_base(self) -> None:
        self.write_json(
            "state.json",
            {
                "schema_version": 1,
                "project_id": "ade-release-observability",
                "status": "READY",
                "iteration": 7,
                "current_task_id": None,
                "completed_task_ids": ["task-final"],
                "failed_task_ids": [],
                "provider": "jules",
                "updated_at": "2026-10-01T05:10:00+00:00",
                "metadata": {
                    "phase": "v1.8-release-orchestration",
                    "milestone": "release-observability",
                    "queue_exhausted": True,
                },
            },
        )
        self.write_json(
            "task-queue.json",
            {"schema_version": 1, "tasks": []},
        )
        self.write_json(
            "failures.json",
            {"schema_version": 1, "failures": []},
        )
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": 7,
                "cycles_completed": 7,
                "repair_attempts": 0,
                "human_interrupts": 1,
                "quota_pauses": 0,
            },
        )
        DecisionStore(self.autodev / "decisions.json").save([])
        ActivityStore(self.autodev / "activity.json").save([])

    def release_snapshot(
        self,
        *,
        promotion_state: ReleasePromotionViewState = (
            ReleasePromotionViewState.VERIFIED
        ),
        verification_state: ReleaseVerificationViewState = (
            ReleaseVerificationViewState.VERIFIED
        ),
        containment_state: ReleaseContainmentViewState = (
            ReleaseContainmentViewState.NONE
        ),
        next_required_human_action: str | None = None,
    ) -> ReleaseObservabilitySnapshot:
        return ReleaseObservabilitySnapshot(
            release_candidate_id="release-observability-proof-001",
            repository="M-Osugi1230/one-minute-thought-experiments",
            source_sha=SOURCE_SHA,
            target_environment=ReleaseEnvironment.PREVIEW,
            approval_state=ReleaseApprovalViewState.APPROVED,
            promotion_state=promotion_state,
            deployment_state=ReleaseDeploymentViewState.DEPLOYED,
            verification_state=verification_state,
            containment_state=containment_state,
            deployment_identity_present=True,
            next_required_human_action=next_required_human_action,
        )

    def test_snapshot_loads_safe_release_projection(self) -> None:
        self.write_json(
            "release/mission-control.json",
            self.release_snapshot().canonical_dict(),
        )

        snapshot = build_mission_control_snapshot(self.root)
        self.assertIsNotNone(snapshot.release)
        assert snapshot.release is not None
        self.assertEqual(
            snapshot.release.release_candidate_id,
            "release-observability-proof-001",
        )
        self.assertEqual(snapshot.release.target_environment, "preview")
        self.assertEqual(snapshot.release.approval_state, "APPROVED")
        self.assertEqual(snapshot.release.promotion_state, "VERIFIED")
        self.assertEqual(snapshot.release.deployment_state, "DEPLOYED")
        self.assertEqual(
            snapshot.release.verification_state,
            "VERIFIED",
        )
        self.assertEqual(snapshot.release.containment_state, "NONE")
        self.assertTrue(snapshot.release.deployment_identity_present)

        serialized_payload = snapshot.to_dict()
        release_payload = serialized_payload["release"]
        assert isinstance(release_payload, dict)
        for forbidden_key in (
            "deployment_id",
            "decision_context",
            "idempotency_key",
            "adapter_implementation_id",
            "registry_fingerprint",
            "provider_session_id",
        ):
            self.assertNotIn(forbidden_key, release_payload)
        serialized = json.dumps(serialized_payload, sort_keys=True)
        self.assertNotIn("dep-preview-private-001", serialized)

    def test_html_renders_release_state_without_deployment_identity(self) -> None:
        self.write_json(
            "release/mission-control.json",
            self.release_snapshot().canonical_dict(),
        )
        snapshot = build_mission_control_snapshot(self.root)
        html = render_mission_control(snapshot)

        self.assertIn("Release", html)
        self.assertIn("release-observability-proof-001", html)
        self.assertIn("preview", html)
        self.assertIn("APPROVED", html)
        self.assertIn("VERIFIED", html)
        self.assertIn("Deployment identity", html)
        self.assertIn(">present<", html)
        self.assertNotIn("dep-preview-private-001", html)
        self.assertNotIn("adapter_implementation_id", html)
        self.assertNotIn("idempotency_key", html)

    def test_release_containment_drives_lifecycle_and_human_action(self) -> None:
        self.write_json(
            "release/mission-control.json",
            self.release_snapshot(
                promotion_state=ReleasePromotionViewState.HUMAN_WAIT,
                verification_state=(
                    ReleaseVerificationViewState.HUMAN_WAIT
                ),
                containment_state=ReleaseContainmentViewState.HUMAN_WAIT,
                next_required_human_action=(
                    "review-release-runtime-verification-failure"
                ),
            ).canonical_dict(),
        )
        snapshot = build_mission_control_snapshot(self.root)

        self.assertEqual(snapshot.lifecycle_status, "HUMAN_WAIT")
        self.assertEqual(
            snapshot.next_required_human_action,
            "review-release-runtime-verification-failure",
        )
        assert snapshot.release is not None
        self.assertEqual(snapshot.release.containment_state, "HUMAN_WAIT")

    def test_malformed_release_projection_fails_closed(self) -> None:
        payload = self.release_snapshot().canonical_dict()
        payload["deployment_token"] = "ghp_1234567890"
        self.write_json("release/mission-control.json", payload)
        with self.assertRaisesRegex(
            ValueError,
            "unknown release observability fields",
        ):
            build_mission_control_snapshot(self.root)

    def test_absent_release_projection_preserves_legacy_snapshot(self) -> None:
        snapshot = build_mission_control_snapshot(self.root)
        self.assertIsNone(snapshot.release)
        html = render_mission_control(snapshot)
        self.assertIn("No release orchestration state.", html)


if __name__ == "__main__":
    unittest.main()
