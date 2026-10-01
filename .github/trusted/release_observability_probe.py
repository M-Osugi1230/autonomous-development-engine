from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ade import (
    ActivityStore,
    DecisionStore,
    ReleaseApprovalViewState,
    ReleaseContainmentViewState,
    ReleaseDeploymentViewState,
    ReleaseEnvironment,
    ReleaseObservabilityError,
    ReleaseObservabilitySnapshot,
    ReleasePromotionViewState,
    ReleaseVerificationViewState,
    build_mission_control_snapshot,
    render_mission_control,
)


RAW_DEPLOYMENT_ID = "dep-private-must-not-render"
RAW_CREDENTIAL = "ghp_123456789012345678901234567890123456"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            autodev = root / ".autodev"
            autodev.mkdir(parents=True)

            _write_json(
                autodev / "state.json",
                {
                    "schema_version": 1,
                    "project_id": "release-observability-proof",
                    "status": "READY",
                    "iteration": 8,
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
            _write_json(
                autodev / "task-queue.json",
                {"schema_version": 1, "tasks": []},
            )
            _write_json(
                autodev / "failures.json",
                {"schema_version": 1, "failures": []},
            )
            _write_json(
                autodev / "metrics.json",
                {
                    "schema_version": 1,
                    "cycles_started": 8,
                    "cycles_completed": 8,
                    "repair_attempts": 0,
                    "human_interrupts": 1,
                    "quota_pauses": 0,
                },
            )
            DecisionStore(autodev / "decisions.json").save([])
            ActivityStore(autodev / "activity.json").save([])

            release = ReleaseObservabilitySnapshot(
                release_candidate_id="release-observability-proof-001",
                repository=(
                    "M-Osugi1230/one-minute-thought-experiments"
                ),
                source_sha="e" * 40,
                target_environment=ReleaseEnvironment.PREVIEW,
                approval_state=ReleaseApprovalViewState.APPROVED,
                promotion_state=ReleasePromotionViewState.VERIFIED,
                deployment_state=ReleaseDeploymentViewState.DEPLOYED,
                verification_state=(
                    ReleaseVerificationViewState.VERIFIED
                ),
                containment_state=ReleaseContainmentViewState.NONE,
                deployment_identity_present=True,
            )
            _write_json(
                autodev / "release" / "mission-control.json",
                release.canonical_dict(),
            )

            # Simulate sensitive trusted deployment evidence existing elsewhere.
            # Mission Control must not read or render this raw file.
            _write_json(
                autodev / "release" / "private-deployment.json",
                {
                    "deployment_id": RAW_DEPLOYMENT_ID,
                    "credential": RAW_CREDENTIAL,
                    "adapter_implementation_id": "private-adapter-v1",
                    "idempotency_key": "private-idempotency-key",
                },
            )

            snapshot = build_mission_control_snapshot(root)
            html = render_mission_control(snapshot)
            serialized = json.dumps(
                snapshot.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            )
            combined = serialized + "\n" + html

            if snapshot.release is None:
                raise AssertionError("release summary missing")
            if snapshot.release.promotion_state != "VERIFIED":
                raise AssertionError("release promotion state mismatch")
            if snapshot.release.verification_state != "VERIFIED":
                raise AssertionError("release verification state mismatch")
            if not snapshot.release.deployment_identity_present:
                raise AssertionError(
                    "deployment identity presence should be visible"
                )
            if "Release" not in html:
                raise AssertionError("release section missing from HTML")

            for forbidden_value in (
                RAW_DEPLOYMENT_ID,
                RAW_CREDENTIAL,
                "private-adapter-v1",
                "private-idempotency-key",
            ):
                if forbidden_value in combined:
                    raise AssertionError(
                        "sensitive release value leaked: "
                        + forbidden_value
                    )

            release_payload = snapshot.to_dict().get("release")
            if not isinstance(release_payload, dict):
                raise AssertionError("release payload missing")
            for forbidden_key in (
                "deployment_id",
                "adapter_implementation_id",
                "idempotency_key",
                "registry_fingerprint",
                "decision_context",
                "provider_session_id",
            ):
                if forbidden_key in release_payload:
                    raise AssertionError(
                        "sensitive release field exposed: "
                        + forbidden_key
                    )

            tampered = release.canonical_dict()
            tampered["deployment_token"] = RAW_CREDENTIAL
            try:
                ReleaseObservabilitySnapshot.from_dict(tampered)
            except ReleaseObservabilityError:
                pass
            else:
                raise AssertionError(
                    "unsafe release projection field must fail closed"
                )

            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "proof": "v1.8-release-mission-control-observability",
                        "release_candidate_id": (
                            snapshot.release.release_candidate_id
                        ),
                        "promotion_state": (
                            snapshot.release.promotion_state
                        ),
                        "verification_state": (
                            snapshot.release.verification_state
                        ),
                        "deployment_identity_present": (
                            snapshot.release.deployment_identity_present
                        ),
                        "raw_deployment_identity_exposed": False,
                        "decision_context_exposed": False,
                        "deployment_credentials_exposed": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
    except Exception as exc:
        message = (
            str(exc).splitlines()[0].strip()
            if str(exc).strip()
            else type(exc).__name__
        )
        print(
            json.dumps(
                {"ok": False, "error": message[:256]},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
