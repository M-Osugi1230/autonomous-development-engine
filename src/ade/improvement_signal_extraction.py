from __future__ import annotations

import hashlib
import json
from typing import Any

from .improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignal,
    ImprovementSignalKind,
    build_improvement_signal,
)


class ImprovementSignalExtractionError(ValueError):
    """Trusted post-release improvement extraction failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ImprovementSignalExtractionError(
            f"{field} must be a JSON object"
        )
    return value


def _require_exact_keys(
    payload: dict[str, Any],
    *,
    allowed: set[str],
    field: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ImprovementSignalExtractionError(
            f"unknown {field} fields: {sorted(unknown)}"
        )


def _require_sha40(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ImprovementSignalExtractionError(
            f"{field} must be lowercase SHA40"
        )
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ImprovementSignalExtractionError(
            f"{field} must be sha256"
        )
    return value


def _require_nonempty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImprovementSignalExtractionError(
            f"{field} must be non-empty"
        )
    return value


def _verified_release_identity(
    *,
    campaign_evidence_payload: object,
    finalization_payload: object,
    target_payload: object,
) -> dict[str, str]:
    campaign = _object(
        campaign_evidence_payload,
        field="release campaign evidence",
    )
    _require_exact_keys(
        campaign,
        allowed={
            "schema_version",
            "version",
            "proof_id",
            "target_repository",
            "release_candidate_id",
            "source_sha",
            "target_environment",
            "approval",
            "deployment",
            "post_promotion_runtime_verification",
            "promotion_verified",
            "auto_promoted_next_environment",
        },
        field="release campaign evidence",
    )
    if campaign.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "release campaign evidence schema_version drift"
        )
    if campaign.get("promotion_verified") is not True:
        raise ImprovementSignalExtractionError(
            "release feedback requires verified promotion"
        )
    if campaign.get("auto_promoted_next_environment") is not False:
        raise ImprovementSignalExtractionError(
            "release feedback cannot originate from auto-promoted evidence"
        )

    repository = _require_nonempty(
        campaign.get("target_repository"),
        field="target_repository",
    )
    source_sha = _require_sha40(
        campaign.get("source_sha"),
        field="source_sha",
    )
    release_candidate_id = _require_nonempty(
        campaign.get("release_candidate_id"),
        field="release_candidate_id",
    )
    environment = campaign.get("target_environment")
    if environment not in {"preview", "staging", "production"}:
        raise ImprovementSignalExtractionError(
            "target_environment is invalid"
        )

    approval = _object(
        campaign.get("approval"),
        field="release approval evidence",
    )
    _require_exact_keys(
        approval,
        allowed={
            "decision_id",
            "disposition",
            "fingerprint",
        },
        field="release approval evidence",
    )
    if approval.get("disposition") != "APPROVED":
        raise ImprovementSignalExtractionError(
            "release feedback requires explicit APPROVED promotion"
        )
    _require_sha256(
        approval.get("fingerprint"),
        field="approval fingerprint",
    )

    deployment = _object(
        campaign.get("deployment"),
        field="release deployment evidence",
    )
    _require_exact_keys(
        deployment,
        allowed={
            "deployment_request_id",
            "deployment_id",
            "receipt_fingerprint",
            "dispatch_count",
            "preview_ref",
        },
        field="release deployment evidence",
    )
    deployment_id = _require_nonempty(
        deployment.get("deployment_id"),
        field="deployment_id",
    )
    if deployment.get("dispatch_count") != 1:
        raise ImprovementSignalExtractionError(
            "release feedback requires single deployment dispatch"
        )
    _require_sha256(
        deployment.get("receipt_fingerprint"),
        field="deployment receipt fingerprint",
    )

    runtime = _object(
        campaign.get("post_promotion_runtime_verification"),
        field="post-promotion runtime evidence",
    )
    _require_exact_keys(
        runtime,
        allowed={
            "verification_id",
            "report_fingerprint",
            "target_evidence_fingerprint",
            "target_ci_run_id",
            "disposition",
        },
        field="post-promotion runtime evidence",
    )
    if runtime.get("disposition") != "VERIFIED":
        raise ImprovementSignalExtractionError(
            "release feedback requires VERIFIED post-promotion runtime"
        )
    verification_id = _require_nonempty(
        runtime.get("verification_id"),
        field="verification_id",
    )
    report_fingerprint = _require_sha256(
        runtime.get("report_fingerprint"),
        field="runtime report fingerprint",
    )
    target_evidence_fingerprint = _require_sha256(
        runtime.get("target_evidence_fingerprint"),
        field="target evidence fingerprint",
    )

    finalization = _object(
        finalization_payload,
        field="post-verification finalization",
    )
    _require_exact_keys(
        finalization,
        allowed={
            "schema_version",
            "outcome",
            "outcome_fingerprint",
            "receipt",
            "recovery",
            "promotion_verified",
            "next_environment_allowed",
            "automatic_rollback",
            "auto_promote_next_environment",
        },
        field="post-verification finalization",
    )
    if finalization.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "post-verification finalization schema_version drift"
        )
    if (
        finalization.get("promotion_verified") is not True
        or finalization.get("recovery") is not None
        or finalization.get("automatic_rollback") is not False
        or finalization.get("auto_promote_next_environment") is not False
    ):
        raise ImprovementSignalExtractionError(
            "release feedback finalization is not a clean VERIFIED outcome"
        )

    outcome = _object(
        finalization.get("outcome"),
        field="release verification outcome",
    )
    _require_exact_keys(
        outcome,
        allowed={
            "schema_version",
            "binding_fingerprint",
            "target_evidence_fingerprint",
            "runtime_report_fingerprint",
            "disposition",
            "deployment_id",
            "environment",
            "failure_fingerprint",
            "promotion_verified",
            "next_required_human_action",
            "rollback_authority",
            "auto_promote_next_environment",
        },
        field="release verification outcome",
    )
    if outcome.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "release verification outcome schema_version drift"
        )
    if (
        outcome.get("disposition") != "VERIFIED"
        or outcome.get("promotion_verified") is not True
        or outcome.get("environment") != environment
        or outcome.get("deployment_id") != deployment_id
        or outcome.get("runtime_report_fingerprint")
        != report_fingerprint
        or outcome.get("target_evidence_fingerprint")
        != target_evidence_fingerprint
    ):
        raise ImprovementSignalExtractionError(
            "release verification outcome identity drift"
        )

    receipt = _object(
        finalization.get("receipt"),
        field="release verification receipt",
    )
    _require_exact_keys(
        receipt,
        allowed={
            "schema_version",
            "verification_id",
            "task_id",
            "target_repository",
            "source_sha",
            "contract_fingerprint",
            "registry_fingerprint",
            "policy_fingerprint",
            "status",
            "dispatch_count",
        },
        field="release verification receipt",
    )
    if receipt.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "release verification receipt schema_version drift"
        )
    if (
        receipt.get("status") != "VERIFIED"
        or receipt.get("dispatch_count") != 1
        or receipt.get("target_repository") != repository
        or receipt.get("source_sha") != source_sha
        or receipt.get("verification_id") != verification_id
    ):
        raise ImprovementSignalExtractionError(
            "release verification receipt identity drift"
        )

    target = _object(
        target_payload,
        field="runtime target evidence",
    )
    _require_exact_keys(
        target,
        allowed={
            "schema_version",
            "spec",
            "evidence",
            "evidence_fingerprint",
            "registry_fingerprint",
        },
        field="runtime target evidence",
    )
    if target.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "runtime target evidence schema_version drift"
        )
    spec = _object(
        target.get("spec"),
        field="runtime target spec",
    )
    _require_exact_keys(
        spec,
        allowed={
            "schema_version",
            "target_id",
            "environment",
            "kind",
            "deployment_required",
            "max_age_seconds",
            "max_future_skew_seconds",
        },
        field="runtime target spec",
    )
    evidence = _object(
        target.get("evidence"),
        field="runtime target observation",
    )
    _require_exact_keys(
        evidence,
        allowed={
            "schema_version",
            "target_id",
            "kind",
            "target_repository",
            "environment",
            "source_sha",
            "observed_at",
            "provenance_id",
            "deployment_id",
        },
        field="runtime target observation",
    )
    if (
        spec.get("schema_version") != 1
        or spec.get("deployment_required") is not True
        or spec.get("environment") != environment
        or spec.get("kind") != environment
        or spec.get("target_id") != evidence.get("target_id")
        or evidence.get("schema_version") != 1
        or evidence.get("kind") != environment
    ):
        raise ImprovementSignalExtractionError(
            "runtime target spec/observation drift"
        )
    if (
        evidence.get("target_repository") != repository
        or evidence.get("source_sha") != source_sha
        or evidence.get("environment") != environment
        or evidence.get("deployment_id") != deployment_id
    ):
        raise ImprovementSignalExtractionError(
            "runtime target observation identity drift"
        )
    computed_target_fingerprint = _fingerprint(evidence)
    if (
        target.get("evidence_fingerprint")
        != computed_target_fingerprint
        or computed_target_fingerprint
        != target_evidence_fingerprint
    ):
        raise ImprovementSignalExtractionError(
            "runtime target evidence fingerprint drift"
        )

    return {
        "repository": repository,
        "source_sha": source_sha,
        "release_candidate_id": release_candidate_id,
        "release_environment": environment,
        "deployment_id": deployment_id,
        "verification_id": verification_id,
        "campaign_evidence_fingerprint": _fingerprint(campaign),
        "finalization_fingerprint": _fingerprint(finalization),
        "target_evidence_fingerprint": computed_target_fingerprint,
    }


def extract_verified_release_followup_signal(
    *,
    campaign_evidence_payload: object,
    finalization_payload: object,
    target_payload: object,
    campaign_evidence_path: str,
    finalization_path: str,
    target_path: str,
) -> ImprovementSignal:
    identity = _verified_release_identity(
        campaign_evidence_payload=campaign_evidence_payload,
        finalization_payload=finalization_payload,
        target_payload=target_payload,
    )
    return build_improvement_signal(
        repository=identity["repository"],
        source_sha=identity["source_sha"],
        release_candidate_id=identity["release_candidate_id"],
        release_environment=identity["release_environment"],
        kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
        statement=(
            "Verified "
            + identity["release_environment"]
            + " release completed exact-deployment Runtime Verification; "
            "retain one bounded observation for trusted improvement resolution."
        ),
        evidence_refs=(
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path=campaign_evidence_path,
                fingerprint=identity[
                    "campaign_evidence_fingerprint"
                ],
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.POST_VERIFICATION,
                path=finalization_path,
                fingerprint=identity[
                    "finalization_fingerprint"
                ],
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RUNTIME_TARGET,
                path=target_path,
                fingerprint=identity[
                    "target_evidence_fingerprint"
                ],
            ),
        ),
        tags=(
            identity["release_environment"],
            "observation",
            "release",
            "verified",
        ),
    )


def extract_actionable_release_gap_signal(
    *,
    campaign_evidence_payload: object,
    finalization_payload: object,
    target_payload: object,
    campaign_evidence_path: str,
    finalization_path: str,
    target_path: str,
    gap_kind: ImprovementSignalKind,
    gap_evidence_kind: ImprovementEvidenceKind,
    gap_evidence_payload: object,
    gap_evidence_path: str,
) -> ImprovementSignal:
    if gap_kind is ImprovementSignalKind.RELEASE_FOLLOWUP:
        raise ImprovementSignalExtractionError(
            "actionable gap extraction requires a gap signal kind"
        )
    if gap_evidence_kind not in {
        ImprovementEvidenceKind.RECOVERY,
        ImprovementEvidenceKind.TELEMETRY,
    }:
        raise ImprovementSignalExtractionError(
            "actionable gap requires trusted RECOVERY or TELEMETRY evidence"
        )

    identity = _verified_release_identity(
        campaign_evidence_payload=campaign_evidence_payload,
        finalization_payload=finalization_payload,
        target_payload=target_payload,
    )
    gap_payload = _object(
        gap_evidence_payload,
        field="trusted gap evidence",
    )
    _require_exact_keys(
        gap_payload,
        allowed={
            "schema_version",
            "repository",
            "source_sha",
            "release_candidate_id",
            "release_environment",
            "signal_kind",
            "detail_fingerprint",
        },
        field="trusted gap evidence",
    )
    if gap_payload.get("schema_version") != 1:
        raise ImprovementSignalExtractionError(
            "trusted gap evidence schema_version drift"
        )
    if gap_payload.get("repository") != identity["repository"]:
        raise ImprovementSignalExtractionError(
            "trusted gap evidence repository drift"
        )
    if gap_payload.get("source_sha") != identity["source_sha"]:
        raise ImprovementSignalExtractionError(
            "trusted gap evidence source SHA drift"
        )
    if (
        gap_payload.get("release_candidate_id")
        != identity["release_candidate_id"]
    ):
        raise ImprovementSignalExtractionError(
            "trusted gap evidence release candidate drift"
        )
    if (
        gap_payload.get("release_environment")
        != identity["release_environment"]
    ):
        raise ImprovementSignalExtractionError(
            "trusted gap evidence environment drift"
        )
    if gap_payload.get("signal_kind") != gap_kind.value:
        raise ImprovementSignalExtractionError(
            "trusted gap evidence signal kind drift"
        )
    _require_sha256(
        gap_payload.get("detail_fingerprint"),
        field="trusted gap detail fingerprint",
    )

    source_label = (
        "recovery"
        if gap_evidence_kind
        is ImprovementEvidenceKind.RECOVERY
        else "telemetry"
    )
    return build_improvement_signal(
        repository=identity["repository"],
        source_sha=identity["source_sha"],
        release_candidate_id=identity["release_candidate_id"],
        release_environment=identity["release_environment"],
        kind=gap_kind,
        statement=(
            "Trusted post-release "
            + source_label
            + " evidence identifies one bounded "
            + gap_kind.value.casefold().replace("_", " ")
            + " after the verified release."
        ),
        evidence_refs=(
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path=campaign_evidence_path,
                fingerprint=identity[
                    "campaign_evidence_fingerprint"
                ],
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.POST_VERIFICATION,
                path=finalization_path,
                fingerprint=identity[
                    "finalization_fingerprint"
                ],
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RUNTIME_TARGET,
                path=target_path,
                fingerprint=identity[
                    "target_evidence_fingerprint"
                ],
            ),
            ImprovementEvidenceRef(
                kind=gap_evidence_kind,
                path=gap_evidence_path,
                fingerprint=_fingerprint(gap_payload),
            ),
        ),
        tags=(
            gap_kind.value.casefold().replace("_", "-"),
            identity["release_environment"],
            source_label,
            "verified-release",
        ),
    )
