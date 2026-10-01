from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".autodev" / "release" / "proof"
FINAL_DIR = PROOF_DIR / "final"
CAMPAIGN_EVIDENCE_PATH = (
    ROOT
    / ".autodev"
    / "campaign-evidence"
    / "v1.8-autonomous-release-proof-001.json"
)
PROJECT_STATE_PATH = ROOT / ".autodev" / "state.json"
ACCEPTANCE_PATH = ROOT / "ACCEPTANCE.md"

PROOF_ID = "v1.8-autonomous-release-proof-001"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_CANDIDATE_ID = "release-a4cd075b270b6ad434ae2602"
DECISION_ID = "release-approval-ea7386c7ca3d03d5d54fb3f7"
DEPLOYMENT_ID = "preview-ref-ade-preview"
POST_VERIFICATION_ID = "release-rv-2c0dd1ac3dd567d46444aa8a"
TARGET_CI_RUN_ID = 36882390659
FINALIZER_RUN_ID = 36883246706
FINALIZER_ARTIFACT_ID = 11171907360


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_finalizer():
    path = ROOT / ".github" / "trusted" / "v1_8_release_proof_finalize.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_8_release_graduation_audit",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.8 release finalizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frozen_api(provenance: dict[str, Any]):
    def api_get(url: str):
        if "/git/ref/heads/ade-preview" in url:
            return {
                "ref": provenance["preview_ref"],
                "object": {
                    "sha": provenance["preview_source_sha"],
                    "type": "commit",
                },
            }
        if "/actions/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "id": provenance["target_ci_run_id"],
                        "name": provenance["target_ci_workflow_name"],
                        "event": provenance["target_ci_event"],
                        "status": "completed",
                        "conclusion": provenance["target_ci_conclusion"],
                        "head_branch": provenance["target_ci_head_branch"],
                        "head_sha": provenance["target_ci_head_sha"],
                        "created_at": provenance["target_ci_created_at"],
                        "updated_at": provenance["target_ci_updated_at"],
                        "run_attempt": 1,
                    }
                ]
            }
        raise AssertionError(f"unexpected frozen GitHub API URL: {url}")

    return api_get


def _assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise ValueError(f"v1.8 Graduation evidence drift: {label}")


def audit() -> dict[str, Any]:
    finalizer = _load_finalizer()

    preapproval = _load_json(
        PROOF_DIR / "preapproval" / "state.json"
    )
    if (
        preapproval.get("state") != "HUMAN_WAIT"
        or preapproval.get("approval_disposition") != "HUMAN_WAIT"
        or preapproval.get("external_side_effect_executed") is not False
    ):
        raise ValueError("v1.8 preapproval HUMAN_WAIT evidence drift")

    human_input = _load_json(
        PROOF_DIR / "human-approval-input.json"
    )
    if (
        human_input.get("decision_id") != DECISION_ID
        or human_input.get("selected_option") != "approve"
        or human_input.get("source_sha") != SOURCE_SHA
        or human_input.get("target_environment") != "preview"
    ):
        raise ValueError("v1.8 explicit approval evidence drift")

    dispatch_receipt = _load_json(
        PROOF_DIR / "dispatch" / "deployment-receipt.json"
    )
    dispatch_state = _load_json(
        PROOF_DIR / "dispatch" / "state.json"
    )
    if (
        dispatch_receipt.get("status") != "DISPATCHED"
        or dispatch_receipt.get("dispatch_count") != 1
        or dispatch_receipt.get("deployment_id") is not None
        or dispatch_state.get("external_side_effect_executed") is not False
    ):
        raise ValueError("v1.8 durable pre-side-effect dispatch evidence drift")

    provenance = _load_json(
        FINAL_DIR / "external-provenance.json"
    )
    if (
        provenance.get("proof_id") != PROOF_ID
        or provenance.get("preview_ref") != "refs/heads/ade-preview"
        or provenance.get("preview_source_sha") != SOURCE_SHA
        or provenance.get("target_ci_run_id") != TARGET_CI_RUN_ID
        or provenance.get("target_ci_conclusion") != "success"
        or provenance.get("post_dispatch_ci") is not True
        or provenance.get("force_update_used") is not False
    ):
        raise ValueError("v1.8 external preview provenance drift")

    bundle = finalizer.build_final_proof(
        api_get=_frozen_api(provenance)
    )
    final_mapping = {
        "deployment-observation.json": "deployment_observation",
        "deployment-receipt.json": "deployment_receipt",
        "external-provenance.json": "external_provenance",
        "post-verification-policy.json": "post_verification_policy",
        "post-verification-probe-registry.json": (
            "post_verification_probe_registry"
        ),
        "post-verification-activation.json": (
            "post_verification_activation"
        ),
        "post-verification-dispatch-receipt.json": (
            "post_verification_dispatch_receipt"
        ),
        "post-verification-target.json": "post_verification_target",
        "post-verification-report.json": "post_verification_report",
        "post-verification-finalization.json": (
            "post_verification_finalization"
        ),
        "state.json": "proof_state",
        "mission-control.json": "mission_control",
        "campaign-evidence.json": "campaign_evidence",
    }
    for filename, key in final_mapping.items():
        _assert_equal(
            _load_json(FINAL_DIR / filename),
            bundle[key],
            label=filename,
        )

    final_state = bundle["proof_state"]
    if (
        final_state.get("state") != "VERIFIED"
        or final_state.get("external_side_effect_executed") is not True
        or final_state.get("deployment_id") != DEPLOYMENT_ID
        or final_state.get("deployment_status") != "DEPLOYED"
        or final_state.get("post_verification_id") != POST_VERIFICATION_ID
        or final_state.get("post_verification_status") != "VERIFIED"
        or final_state.get("target_ci_run_id") != TARGET_CI_RUN_ID
        or final_state.get("auto_promote") is not False
    ):
        raise ValueError("v1.8 final release state drift")

    finalization = bundle["post_verification_finalization"]
    if (
        finalization.get("promotion_verified") is not True
        or finalization.get("next_environment_allowed") is not True
        or finalization.get("automatic_rollback") is not False
        or finalization.get("auto_promote_next_environment") is not False
        or finalization.get("receipt", {}).get("status") != "VERIFIED"
        or finalization.get("recovery") is not None
    ):
        raise ValueError("v1.8 post-promotion finalization drift")

    campaign_evidence = bundle["campaign_evidence"]
    if (
        campaign_evidence.get("release_candidate_id")
        != RELEASE_CANDIDATE_ID
        or campaign_evidence.get("promotion_verified") is not True
        or campaign_evidence.get("auto_promoted_next_environment") is not False
    ):
        raise ValueError("v1.8 campaign evidence drift")
    _assert_equal(
        _load_json(CAMPAIGN_EVIDENCE_PATH),
        campaign_evidence,
        label="graduation campaign evidence",
    )

    current_proof_state = _load_json(
        PROOF_DIR / "state.json"
    )
    _assert_equal(
        current_proof_state,
        bundle["proof_state"],
        label="current release proof state",
    )
    current_mission = _load_json(
        ROOT / ".autodev" / "release" / "mission-control.json"
    )
    _assert_equal(
        current_mission,
        bundle["mission_control"],
        label="current Mission Control release summary",
    )

    finalizer_provenance = _load_json(
        FINAL_DIR / "finalization-provenance.json"
    )
    if (
        finalizer_provenance.get("proof_id") != PROOF_ID
        or finalizer_provenance.get("workflow_run_id")
        != FINALIZER_RUN_ID
        or finalizer_provenance.get("artifact_id")
        != FINALIZER_ARTIFACT_ID
        or finalizer_provenance.get("finalizer_conclusion") != "success"
        or finalizer_provenance.get("target_ci_run_id")
        != TARGET_CI_RUN_ID
        or finalizer_provenance.get("external_write_after_preview_creation")
        is not False
    ):
        raise ValueError("v1.8 finalizer provenance drift")

    project_state = _load_json(PROJECT_STATE_PATH)
    metadata = project_state.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("project state metadata is invalid")
    expected_metadata = {
        "milestone": "v1.8-graduated",
        "v1_8_graduated": True,
        "v1_8_graduation_evidence": (
            ".autodev/campaign-evidence/"
            "v1.8-autonomous-release-proof-001.json"
        ),
        "v1_8_release_candidate_id": RELEASE_CANDIDATE_ID,
        "v1_8_release_approval_decision_id": DECISION_ID,
        "v1_8_proof_target_final_sha": SOURCE_SHA,
        "v1_8_target_environment": "preview",
        "v1_8_preview_ref": "refs/heads/ade-preview",
        "v1_8_deployment_id": DEPLOYMENT_ID,
        "v1_8_target_ci_run_id": TARGET_CI_RUN_ID,
        "v1_8_post_verification_id": POST_VERIFICATION_ID,
        "v1_8_finalizer_workflow_run_id": FINALIZER_RUN_ID,
        "v1_8_finalizer_artifact_id": FINALIZER_ARTIFACT_ID,
        "v1_8_auto_promoted_next_environment": False,
        "next_required_human_action": None,
        "next_system_action": None,
        "queue_exhausted": True,
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise ValueError(
                f"v1.8 project state metadata drift: {key}"
            )
    if (
        project_state.get("status") != "READY"
        or project_state.get("current_task_id") is not None
        or project_state.get("failed_task_ids") != []
    ):
        raise ValueError("v1.8 graduated ProjectState is not stable READY")

    acceptance = ACCEPTANCE_PATH.read_text(encoding="utf-8")
    required_checks = (
        "- [x] A real external-repository proof demonstrates verified Campaign -> release candidate -> approved promotion -> post-promotion Runtime Verification.",
        "- [x] A dedicated v1.8 Graduation audit reconstructs the release proof end to end.",
    )
    for check in required_checks:
        if check not in acceptance:
            raise ValueError(
                "v1.8 Acceptance graduation check is incomplete"
            )

    return {
        "schema_version": 1,
        "version": "v1.8",
        "proof_id": PROOF_ID,
        "release_candidate_id": RELEASE_CANDIDATE_ID,
        "source_sha": SOURCE_SHA,
        "decision_id": DECISION_ID,
        "deployment_id": DEPLOYMENT_ID,
        "target_ci_run_id": TARGET_CI_RUN_ID,
        "post_verification_id": POST_VERIFICATION_ID,
        "promotion_verified": True,
        "graduated": True,
        "auto_promoted_next_environment": False,
    }


def main() -> int:
    try:
        result = audit()
        print(json.dumps(result, sort_keys=True))
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
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
