from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from .recovery import RecoveryAction, RecoveryFailure
from .recovery_runtime import RecoveryRecord, advance_recovery
from .runtime_verification import RuntimeVerificationReport
from .runtime_verification_trigger import RuntimeVerificationReceipt


@dataclass(frozen=True, slots=True)
class RuntimeFailureTransition:
    recovery: RecoveryRecord
    receipt: RuntimeVerificationReceipt
    state: dict[str, Any]
    campaign: dict[str, Any]


def runtime_failure_fingerprint(detail: str) -> str:
    if not isinstance(detail, str) or not detail.strip():
        raise ValueError("runtime failure detail must be non-empty")
    normalized = " ".join(detail.strip().split())[:512]
    return hashlib.sha256(("RUNTIME_VERIFICATION:" + normalized).encode()).hexdigest()


def contain_runtime_verification_failure(
    *,
    receipt: RuntimeVerificationReceipt,
    state_payload: dict[str, Any],
    campaign_payload: dict[str, Any],
    report: RuntimeVerificationReport | None = None,
    failure_fingerprint: str | None = None,
    previous_recovery: RecoveryRecord | None = None,
) -> RuntimeFailureTransition:
    if not isinstance(receipt, RuntimeVerificationReceipt):
        raise ValueError("receipt must be a RuntimeVerificationReceipt")
    if receipt.status != "FAILED":
        raise ValueError("runtime failure containment requires FAILED receipt")
    if report is None and failure_fingerprint is None:
        raise ValueError("report or failure_fingerprint is required")
    if report is not None:
        if not isinstance(report, RuntimeVerificationReport):
            raise ValueError("report must be a RuntimeVerificationReport")
        if report.verification_id != receipt.verification_id:
            raise ValueError("runtime failure report/receipt id mismatch")
        if report.source_sha != receipt.source_sha:
            raise ValueError("runtime failure report/receipt source mismatch")
        if report.contract_fingerprint != receipt.contract_fingerprint:
            raise ValueError("runtime failure report/receipt contract mismatch")
        resolved_fingerprint = report.fingerprint()
    else:
        resolved_fingerprint = failure_fingerprint
        if (
            not isinstance(resolved_fingerprint, str)
            or len(resolved_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in resolved_fingerprint)
        ):
            raise ValueError("failure_fingerprint must be a lowercase SHA-256 digest")
    if not isinstance(state_payload, dict):
        raise ValueError("state_payload must be an object")
    if not isinstance(campaign_payload, dict):
        raise ValueError("campaign_payload must be an object")

    task_ids = campaign_payload.get("task_ids")
    if not isinstance(task_ids, list) or receipt.task_id not in task_ids:
        raise ValueError("runtime failure task is not part of campaign")

    metadata = state_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    target_repository = metadata.get("target_repository")
    if (
        isinstance(target_repository, str)
        and target_repository
        and target_repository != receipt.target_repository
    ):
        raise ValueError("runtime failure target repository drift")

    recovery = advance_recovery(
        receipt.task_id,
        RecoveryFailure.RUNTIME_VERIFICATION,
        resolved_fingerprint,
        previous_recovery,
    )
    if recovery.action is not RecoveryAction.HUMAN_WAIT:
        raise RuntimeError("runtime verification failure must fail closed to HUMAN_WAIT")

    next_state = dict(state_payload)
    next_metadata = dict(metadata)
    next_metadata.update(
        {
            "recovery_action": recovery.action.value,
            "recovery_failure": recovery.failure.value,
            "runtime_verification_id": receipt.verification_id,
            "runtime_verification_source_sha": receipt.source_sha,
            "runtime_verification_failure_fingerprint": resolved_fingerprint,
            "next_required_human_action": "review-runtime-verification-failure",
            "next_system_action": None,
        }
    )
    next_state["status"] = "HUMAN_WAIT"
    next_state["current_task_id"] = receipt.task_id
    next_state["metadata"] = next_metadata

    next_campaign = dict(campaign_payload)
    next_campaign["status"] = "HUMAN_WAIT"

    human_wait_receipt = RuntimeVerificationReceipt(
        verification_id=receipt.verification_id,
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        source_sha=receipt.source_sha,
        contract_fingerprint=receipt.contract_fingerprint,
        registry_fingerprint=receipt.registry_fingerprint,
        policy_fingerprint=receipt.policy_fingerprint,
        status="HUMAN_WAIT",
        dispatch_count=receipt.dispatch_count,
    )

    return RuntimeFailureTransition(
        recovery=recovery,
        receipt=human_wait_receipt,
        state=next_state,
        campaign=next_campaign,
    )
