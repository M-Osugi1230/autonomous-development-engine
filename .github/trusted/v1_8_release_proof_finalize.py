from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.campaign import AutonomousCampaign
from ade.decisions import DecisionRecord
from ade.release_approval import (
    ReleaseApprovalDisposition,
    evaluate_release_approval,
)
from ade.release_candidate import (
    ReleaseCandidate,
    ReleaseEnvironment,
)
from ade.release_deployment import (
    ReleaseDeploymentAdapterRegistration,
    ReleaseDeploymentInvocation,
    ReleaseDeploymentObservation,
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
    TrustedReleaseDeploymentRegistry,
    arm_release_deployment,
    record_release_deployment_dispatch,
    record_release_deployment_observation,
)
from ade.release_observability import build_release_observability_snapshot
from ade.release_policy import ReleaseTransitionPlan
from ade.release_post_verification import (
    arm_release_post_verification,
    finalize_release_post_verification,
)
from ade.runtime_probe_registry import (
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_target_registry import (
    RuntimeTargetKind,
    RuntimeTargetObservation,
    RuntimeTargetRegistration,
    RuntimeTargetSpec,
    TrustedRuntimeTargetRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeStatus,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import (
    RuntimeVerificationPolicy,
    record_runtime_verification_dispatch,
)


PROOF_ID = "v1.8-autonomous-release-proof-001"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
PREVIEW_BRANCH = "ade-preview"
DEPLOYMENT_ID = "preview-ref-ade-preview"
TASK_ID = "v17ma1-001"
CONTROLLER_DISPATCH_PR = 239
CONTROLLER_DISPATCH_MERGE_SHA = (
    "2ad92d3b69b875956b2c9595e095f5f1271491d0"
)
CONTROLLER_DISPATCH_MERGED_AT = "2026-10-01T15:11:44Z"
TARGET_WORKFLOW_NAME = "Phase 1 and 2 checks"

PROOF_DIR = Path(".autodev/release/proof")
FINAL_DIR = Path(".autodev/release/finalized")
RESULT_PATH = Path(
    ".autodev/runtime/v1-8-release-proof-finalize-result.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _api_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ADE-v1.8-Release-Finalizer/1.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(
            f"GitHub HTTP {exc.code}: {detail[:400]}"
        ) from exc
    except URLError as exc:
        raise ValueError(
            f"GitHub network error: {exc.reason}"
        ) from exc
    return json.loads(raw.decode("utf-8"))


def _select_target_ci_run(
    runs: list[dict[str, Any]],
    *,
    dispatch_merged_at: str,
) -> dict[str, Any]:
    cutoff = _parse_time(
        dispatch_merged_at,
        field="dispatch_merged_at",
    )
    candidates: list[dict[str, Any]] = []
    for row in runs:
        if not isinstance(row, dict):
            continue
        if row.get("name") != TARGET_WORKFLOW_NAME:
            continue
        if row.get("event") != "push":
            continue
        if row.get("status") != "completed":
            continue
        if row.get("conclusion") != "success":
            continue
        if row.get("head_branch") != PREVIEW_BRANCH:
            continue
        if row.get("head_sha") != SOURCE_SHA:
            continue
        created = _parse_time(
            row.get("created_at"),
            field="target CI created_at",
        )
        if created <= cutoff:
            continue
        candidates.append(row)

    if not candidates:
        raise ValueError(
            "no successful post-dispatch preview CI run"
        )
    candidates.sort(
        key=lambda row: _parse_time(
            row.get("created_at"),
            field="target CI created_at",
        )
    )
    return candidates[0]


def _transition_from_payload(
    payload: dict[str, Any],
) -> ReleaseTransitionPlan:
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


def _deployment_invocation_from_payload(
    payload: dict[str, Any],
) -> ReleaseDeploymentInvocation:
    return ReleaseDeploymentInvocation(
        deployment_request_id=payload["deployment_request_id"],
        idempotency_key=payload["idempotency_key"],
        repository=payload["repository"],
        source_sha=payload["source_sha"],
        environment=ReleaseEnvironment(payload["environment"]),
        transition_id=payload["transition_id"],
        transition_fingerprint=payload["transition_fingerprint"],
        approval_fingerprint=payload["approval_fingerprint"],
        adapter_implementation_id=payload[
            "adapter_implementation_id"
        ],
        registry_fingerprint=payload["registry_fingerprint"],
    )


def _deployment_receipt_from_payload(
    payload: dict[str, Any],
) -> ReleaseDeploymentReceipt:
    return ReleaseDeploymentReceipt(
        deployment_request_id=payload["deployment_request_id"],
        idempotency_key=payload["idempotency_key"],
        repository=payload["repository"],
        source_sha=payload["source_sha"],
        environment=ReleaseEnvironment(payload["environment"]),
        transition_id=payload["transition_id"],
        transition_fingerprint=payload["transition_fingerprint"],
        approval_fingerprint=payload["approval_fingerprint"],
        adapter_implementation_id=payload[
            "adapter_implementation_id"
        ],
        registry_fingerprint=payload["registry_fingerprint"],
        status=ReleaseDeploymentStatus(payload["status"]),
        dispatch_count=payload["dispatch_count"],
        deployment_id=payload.get("deployment_id"),
        observation_fingerprint=payload.get(
            "observation_fingerprint"
        ),
    )


def _build_deployment_registry(
    *,
    invocation: ReleaseDeploymentInvocation,
) -> TrustedReleaseDeploymentRegistry:
    def forbidden_deployer(_):
        raise AssertionError(
            "release finalizer must not mutate target repository"
        )

    return TrustedReleaseDeploymentRegistry(
        (
            ReleaseDeploymentAdapterRegistration(
                repository=invocation.repository,
                environment=invocation.environment,
                implementation_id=(
                    invocation.adapter_implementation_id
                ),
                deployer=forbidden_deployer,
            ),
        )
    )


def _target_api_url(path: str) -> str:
    return (
        "https://api.github.com/repos/"
        + TARGET_REPOSITORY
        + path
    )


def build_final_proof(
    *,
    api_get: Callable[[str], Any] = _api_json,
) -> dict[str, Any]:
    candidate = ReleaseCandidate.from_dict(
        _load_json(PROOF_DIR / "candidate.json")
    )
    transition = _transition_from_payload(
        _load_json(PROOF_DIR / "transition.json")
    )
    decision = DecisionRecord.from_dict(
        _load_json(PROOF_DIR / "decision-record.json")
    )
    approval = evaluate_release_approval(
        transition=transition,
        record=decision,
    )
    if (
        approval.disposition
        is not ReleaseApprovalDisposition.APPROVED
        or not approval.approval_satisfied
    ):
        raise ValueError(
            "v1.8 release proof is not explicitly approved"
        )

    invocation = _deployment_invocation_from_payload(
        _load_json(PROOF_DIR / "deployment-invocation.json")
    )
    dispatched = _deployment_receipt_from_payload(
        _load_json(PROOF_DIR / "deployment-receipt.json")
    )
    if (
        dispatched.status
        is not ReleaseDeploymentStatus.DISPATCHED
        or dispatched.dispatch_count != 1
    ):
        raise ValueError(
            "v1.8 deployment was not durably dispatched"
        )

    deployment_registry = _build_deployment_registry(
        invocation=invocation,
    )
    activation = arm_release_deployment(
        transition=transition,
        approval=approval,
        registry=deployment_registry,
    )
    reconstructed_dispatch = record_release_deployment_dispatch(
        invocation=activation.invocation,
        receipt=activation.receipt,
    )
    if (
        activation.invocation.canonical_dict()
        != invocation.canonical_dict()
        or reconstructed_dispatch.receipt.canonical_dict()
        != dispatched.canonical_dict()
    ):
        raise ValueError(
            "v1.8 deployment dispatch reconstruction drift"
        )

    preview_ref = api_get(
        _target_api_url(
            f"/git/ref/heads/{PREVIEW_BRANCH}"
        )
    )
    if not isinstance(preview_ref, dict):
        raise ValueError("preview ref response is invalid")
    obj = preview_ref.get("object")
    if (
        preview_ref.get("ref")
        != f"refs/heads/{PREVIEW_BRANCH}"
        or not isinstance(obj, dict)
        or obj.get("sha") != SOURCE_SHA
    ):
        raise ValueError("preview ref does not bind exact source SHA")

    runs_payload = api_get(
        _target_api_url(
            f"/actions/runs?branch={PREVIEW_BRANCH}&per_page=50"
        )
    )
    if (
        not isinstance(runs_payload, dict)
        or not isinstance(runs_payload.get("workflow_runs"), list)
    ):
        raise ValueError("target workflow runs response is invalid")
    target_ci = _select_target_ci_run(
        runs_payload["workflow_runs"],
        dispatch_merged_at=CONTROLLER_DISPATCH_MERGED_AT,
    )

    target_ci_updated_at = _parse_time(
        target_ci.get("updated_at"),
        field="target CI updated_at",
    )
    observation = ReleaseDeploymentObservation(
        deployment_id=DEPLOYMENT_ID,
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
        environment=ReleaseEnvironment.PREVIEW,
        idempotency_key=invocation.idempotency_key,
    )
    deployment_completion = (
        record_release_deployment_observation(
            invocation=invocation,
            receipt=dispatched,
            observation=observation,
        )
    )
    deployed_receipt = deployment_completion.receipt

    policy = RuntimeVerificationPolicy(
        target_repository=TARGET_REPOSITORY,
        environment="preview",
        required_probe_ids=(
            "preview-ci-green",
            "preview-ref-exact",
        ),
        max_attempts=1,
        timeout_seconds=300,
    )

    def ref_probe(_):
        return RuntimeProbeObservation(
            status=RuntimeProbeStatus.PASS,
            detail_code="preview-ref-exact",
        )

    def ci_probe(_):
        return RuntimeProbeObservation(
            status=RuntimeProbeStatus.PASS,
            detail_code="preview-ci-green",
        )

    probe_registry = TrustedRuntimeProbeRegistry(
        (
            RuntimeProbeRegistration(
                probe_id="preview-ci-green",
                implementation_id="github-actions-preview-ci-v1",
                runner=ci_probe,
            ),
            RuntimeProbeRegistration(
                probe_id="preview-ref-exact",
                implementation_id="github-preview-ref-check-v1",
                runner=ref_probe,
            ),
        )
    )
    verification_activation = arm_release_post_verification(
        deployment_receipt=deployed_receipt,
        policy=policy,
        registry=probe_registry,
        task_id=TASK_ID,
    )
    verification_dispatch = (
        record_runtime_verification_dispatch(
            contract=verification_activation.binding.runtime_contract,
            registry=probe_registry,
            receipt=verification_activation.receipt,
        )
    )
    if (
        verification_dispatch.receipt.status != "DISPATCHED"
        or verification_dispatch.receipt.dispatch_count != 1
    ):
        raise ValueError(
            "release Runtime Verification was not dispatched exactly once"
        )

    target_spec = RuntimeTargetSpec(
        target_id="ade-preview",
        environment="preview",
        kind=RuntimeTargetKind.PREVIEW,
        max_age_seconds=86400,
        max_future_skew_seconds=60,
    )

    def target_observer(_):
        return RuntimeTargetObservation(
            source_sha=SOURCE_SHA,
            observed_at=target_ci_updated_at,
            deployment_id=DEPLOYMENT_ID,
        )

    target_registry = TrustedRuntimeTargetRegistry(
        (
            RuntimeTargetRegistration(
                target_repository=TARGET_REPOSITORY,
                spec=target_spec,
                implementation_id="github-preview-ref-observer-v1",
                observer=target_observer,
            ),
        )
    )
    target_resolution = target_registry.resolve(
        verification_activation.binding.runtime_contract,
        now=target_ci_updated_at,
    )

    results = tuple(
        probe_registry.execute(
            verification_activation.binding.runtime_contract,
            probe_id=probe_id,
        )
        for probe_id in policy.required_probe_ids
    )
    report = evaluate_runtime_verification(
        verification_activation.binding.runtime_contract,
        results,
    )

    state_payload = _load_json(
        Path(".autodev/multi-agent/proof/state.json")
    )
    campaign_payload = _load_json(
        Path(".autodev/multi-agent/proof/campaign.json")
    )
    campaign = AutonomousCampaign.from_dict(campaign_payload)
    if campaign.status.value != "COMPLETED":
        raise ValueError("source Campaign is no longer COMPLETED")

    finalization = finalize_release_post_verification(
        activation=verification_activation,
        target=target_resolution,
        dispatched_receipt=verification_dispatch.receipt,
        report=report,
        state_payload=state_payload,
        campaign_payload=campaign_payload,
    )
    if not finalization.promotion_verified:
        raise ValueError(
            "post-promotion Runtime Verification is not VERIFIED"
        )

    mission = build_release_observability_snapshot(
        candidate=candidate,
        transition=transition,
        approval=approval,
        deployment_receipt=deployed_receipt,
        finalization=finalization,
    )

    external_provenance = {
        "schema_version": 1,
        "proof_id": PROOF_ID,
        "controller_dispatch_pull_request": (
            CONTROLLER_DISPATCH_PR
        ),
        "controller_dispatch_merge_sha": (
            CONTROLLER_DISPATCH_MERGE_SHA
        ),
        "controller_dispatch_merged_at": (
            CONTROLLER_DISPATCH_MERGED_AT
        ),
        "target_repository": TARGET_REPOSITORY,
        "preview_ref": f"refs/heads/{PREVIEW_BRANCH}",
        "preview_source_sha": SOURCE_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "target_ci_run_id": target_ci.get("id"),
        "target_ci_workflow_name": target_ci.get("name"),
        "target_ci_event": target_ci.get("event"),
        "target_ci_head_branch": target_ci.get("head_branch"),
        "target_ci_head_sha": target_ci.get("head_sha"),
        "target_ci_created_at": target_ci.get("created_at"),
        "target_ci_updated_at": target_ci.get("updated_at"),
        "target_ci_conclusion": target_ci.get("conclusion"),
        "post_dispatch_ci": True,
        "force_update_used": False,
    }

    proof_state = dict(
        _load_json(PROOF_DIR / "state.json")
    )
    proof_state.update(
        {
            "state": "VERIFIED",
            "external_side_effect_executed": True,
            "deployment_status": "DEPLOYED",
            "deployment_id": DEPLOYMENT_ID,
            "deployment_receipt_fingerprint": (
                deployed_receipt.fingerprint()
            ),
            "deployment_observation_fingerprint": (
                observation.fingerprint()
            ),
            "post_verification_id": (
                verification_activation.binding.runtime_contract.verification_id
            ),
            "post_verification_report_fingerprint": (
                report.fingerprint()
            ),
            "post_verification_status": "VERIFIED",
            "target_ci_run_id": target_ci.get("id"),
            "target_ci_conclusion": target_ci.get("conclusion"),
            "next_environment_allowed": True,
            "auto_promote": False,
        }
    )

    campaign_evidence = {
        "schema_version": 1,
        "version": "v1.8",
        "proof_id": PROOF_ID,
        "target_repository": TARGET_REPOSITORY,
        "release_candidate_id": candidate.release_candidate_id,
        "source_sha": SOURCE_SHA,
        "target_environment": "preview",
        "approval": {
            "decision_id": approval.decision_id,
            "disposition": approval.disposition.value,
            "fingerprint": approval.fingerprint(),
        },
        "deployment": {
            "deployment_request_id": (
                deployed_receipt.deployment_request_id
            ),
            "deployment_id": DEPLOYMENT_ID,
            "receipt_fingerprint": deployed_receipt.fingerprint(),
            "dispatch_count": deployed_receipt.dispatch_count,
            "preview_ref": f"refs/heads/{PREVIEW_BRANCH}",
        },
        "post_promotion_runtime_verification": {
            "verification_id": (
                verification_activation.binding.runtime_contract.verification_id
            ),
            "report_fingerprint": report.fingerprint(),
            "disposition": report.disposition.value,
            "target_evidence_fingerprint": (
                target_resolution.evidence.fingerprint()
            ),
            "target_ci_run_id": target_ci.get("id"),
        },
        "promotion_verified": True,
        "auto_promoted_next_environment": False,
    }

    return {
        "deployment_observation": observation.canonical_dict(),
        "deployment_receipt": deployed_receipt.canonical_dict(),
        "external_provenance": external_provenance,
        "post_verification_policy": policy.canonical_dict(),
        "post_verification_probe_registry": (
            probe_registry.canonical_dict()
        ),
        "post_verification_activation": (
            verification_activation.canonical_dict()
        ),
        "post_verification_dispatch_receipt": (
            verification_dispatch.receipt.canonical_dict()
        ),
        "post_verification_target": (
            target_resolution.canonical_dict()
        ),
        "post_verification_report": {
            "schema_version": 1,
            "report": report.canonical_dict(),
            "report_fingerprint": report.fingerprint(),
        },
        "post_verification_finalization": (
            finalization.canonical_dict()
        ),
        "proof_state": proof_state,
        "mission_control": mission.canonical_dict(),
        "campaign_evidence": campaign_evidence,
    }


def persist_final_proof(bundle: dict[str, Any]) -> None:
    mapping = {
        "deployment-observation.json": bundle[
            "deployment_observation"
        ],
        "deployment-receipt.json": bundle[
            "deployment_receipt"
        ],
        "external-provenance.json": bundle[
            "external_provenance"
        ],
        "post-verification-policy.json": bundle[
            "post_verification_policy"
        ],
        "post-verification-probe-registry.json": bundle[
            "post_verification_probe_registry"
        ],
        "post-verification-activation.json": bundle[
            "post_verification_activation"
        ],
        "post-verification-dispatch-receipt.json": bundle[
            "post_verification_dispatch_receipt"
        ],
        "post-verification-target.json": bundle[
            "post_verification_target"
        ],
        "post-verification-report.json": bundle[
            "post_verification_report"
        ],
        "post-verification-finalization.json": bundle[
            "post_verification_finalization"
        ],
        "state.json": bundle["proof_state"],
        "mission-control.json": bundle["mission_control"],
        "campaign-evidence.json": bundle["campaign_evidence"],
    }
    for filename, payload in mapping.items():
        _write_json(FINAL_DIR / filename, payload)


def main() -> int:
    try:
        bundle = build_final_proof()
        persist_final_proof(bundle)
        result = {
            "schema_version": 1,
            "proof_id": PROOF_ID,
            "state": bundle["proof_state"]["state"],
            "source_sha": SOURCE_SHA,
            "preview_ref": f"refs/heads/{PREVIEW_BRANCH}",
            "deployment_id": DEPLOYMENT_ID,
            "target_ci_run_id": bundle[
                "external_provenance"
            ]["target_ci_run_id"],
            "post_verification_id": bundle[
                "proof_state"
            ]["post_verification_id"],
            "promotion_verified": True,
            "auto_promoted_next_environment": False,
        }
        _write_json(RESULT_PATH, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        result = {
            "schema_version": 1,
            "proof_id": PROOF_ID,
            "state": "FAILED",
            "error": (
                str(exc).splitlines()[0][:256]
                if str(exc).strip()
                else type(exc).__name__
            ),
        }
        _write_json(RESULT_PATH, result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
