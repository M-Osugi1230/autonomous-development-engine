from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .autonomous_backlog import (
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
    build_candidate_id,
)
from .recovery import RecoveryAction, RecoveryFailure
from .recovery_runtime import RecoveryRecord
from .runtime_verification import RuntimeVerificationContract
from .runtime_verification_trigger import RuntimeVerificationReceipt


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def evidence_fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _object(payload: object, *, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AutonomousBacklogError(f"{field} must be a JSON object")
    return payload


def _validated_recovery_record(payload: object) -> tuple[RecoveryRecord, dict[str, Any]]:
    raw = _object(payload, field="recovery evidence")
    allowed = {
        "schema_version",
        "task_id",
        "failure",
        "action",
        "fingerprint",
        "progress",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise AutonomousBacklogError(
            f"unknown recovery evidence fields: {sorted(unknown)}"
        )
    if raw.get("schema_version") != 1:
        raise AutonomousBacklogError("recovery evidence schema_version must be 1")
    fingerprint = raw.get("fingerprint")
    if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
        raise AutonomousBacklogError("recovery failure fingerprint must be sha256")
    progress = raw.get("progress")
    if not isinstance(progress, dict):
        raise AutonomousBacklogError("recovery progress must be an object")
    allowed_progress = {
        "retries",
        "repairs",
        "rebases",
        "replans",
        "repeated_failures",
    }
    if set(progress) != allowed_progress:
        raise AutonomousBacklogError("recovery progress fields are invalid")
    try:
        record = RecoveryRecord.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise AutonomousBacklogError("recovery evidence is invalid") from exc
    if record.task_id != raw.get("task_id"):
        raise AutonomousBacklogError("recovery task identity is invalid")
    return record, raw


def extract_recovery_candidate(
    *,
    evidence_path: str,
    recovery_payload: object,
    repository: str,
    source_sha: str,
    source_phase: str | None = None,
) -> BacklogCandidate:
    record, raw = _validated_recovery_record(recovery_payload)
    fingerprint = evidence_fingerprint(raw)

    if record.failure is RecoveryFailure.RUNTIME_VERIFICATION:
        kind = BacklogCandidateKind.RUNTIME_GAP
    else:
        kind = BacklogCandidateKind.VERIFIED_REMEDIATION

    human_only = record.action in {
        RecoveryAction.HUMAN_WAIT,
        RecoveryAction.FAIL,
    }
    statement = (
        f"Trusted recovery classified {record.failure.value} and selected "
        f"{record.action.value}; preserve the bounded follow-up without granting "
        "execution authority."
    )
    candidate_id = build_candidate_id(
        kind=kind,
        repository=repository,
        source_sha=source_sha,
        statement=statement,
        evidence_fingerprints=(fingerprint,),
    )
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=repository,
        source_sha=source_sha,
        statement=statement,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(fingerprint,),
        tags=(
            "recovery",
            record.failure.value.casefold().replace("_", "-"),
            record.action.value.casefold().replace("_", "-"),
        ),
        source_phase=source_phase,
        human_only=human_only,
    )


def extract_runtime_gap_candidate(
    *,
    contract_path: str,
    contract_payload: object,
    receipt_path: str,
    receipt_payload: object,
    source_phase: str | None = None,
) -> BacklogCandidate:
    raw_contract = _object(contract_payload, field="runtime contract")
    raw_receipt = _object(receipt_payload, field="runtime receipt")
    try:
        contract = RuntimeVerificationContract.from_dict(raw_contract)
        receipt = RuntimeVerificationReceipt.from_dict(raw_receipt)
    except (KeyError, TypeError, ValueError) as exc:
        raise AutonomousBacklogError("runtime verification evidence is invalid") from exc

    if receipt.status not in {"FAILED", "HUMAN_WAIT"}:
        raise AutonomousBacklogError(
            "runtime gap extraction requires FAILED or HUMAN_WAIT receipt"
        )
    if receipt.verification_id != contract.verification_id:
        raise AutonomousBacklogError("runtime verification identity mismatch")
    if receipt.target_repository != contract.target_repository:
        raise AutonomousBacklogError("runtime verification repository mismatch")
    if receipt.source_sha != contract.source_sha:
        raise AutonomousBacklogError("runtime verification source SHA mismatch")
    if receipt.contract_fingerprint != contract.fingerprint():
        raise AutonomousBacklogError("runtime verification contract fingerprint mismatch")

    fingerprints = (
        evidence_fingerprint(raw_contract),
        evidence_fingerprint(raw_receipt),
    )
    statement = (
        f"Trusted runtime verification ended {receipt.status} for task "
        f"{receipt.task_id}; preserve the source-bound gap as human-only until "
        "trusted evidence resolves it."
    )
    candidate_id = build_candidate_id(
        kind=BacklogCandidateKind.RUNTIME_GAP,
        repository=contract.target_repository,
        source_sha=contract.source_sha,
        statement=statement,
        evidence_fingerprints=fingerprints,
    )
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=BacklogCandidateKind.RUNTIME_GAP,
        repository=contract.target_repository,
        source_sha=contract.source_sha,
        statement=statement,
        evidence_paths=(contract_path, receipt_path),
        evidence_fingerprints=fingerprints,
        tags=("runtime", "unresolved", receipt.status.casefold().replace("_", "-")),
        source_phase=source_phase,
        human_only=True,
    )
