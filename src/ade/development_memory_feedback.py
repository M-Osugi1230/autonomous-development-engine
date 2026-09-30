from __future__ import annotations

import hashlib
import json
from typing import Any

from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from .runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationReport,
    evaluate_runtime_verification,
)
from .runtime_verification_trigger import RuntimeVerificationReceipt


def _sha256(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def runtime_report_from_wrapper(payload: object) -> RuntimeVerificationReport:
    if not isinstance(payload, dict):
        raise DevelopmentMemoryError("runtime report wrapper must be an object")
    allowed = {
        "schema_version",
        "report",
        "report_fingerprint",
        "attempts_by_probe",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise DevelopmentMemoryError(
            f"unknown runtime report wrapper fields: {sorted(unknown)}"
        )
    if payload.get("schema_version") != 1:
        raise DevelopmentMemoryError("runtime report wrapper schema_version must be 1")
    report_payload = payload.get("report")
    if not isinstance(report_payload, dict):
        raise DevelopmentMemoryError("runtime report must be an object")
    allowed_report = {
        "schema_version",
        "verification_id",
        "contract_fingerprint",
        "source_sha",
        "disposition",
        "results",
        "missing_probe_ids",
    }
    unknown_report = set(report_payload) - allowed_report
    if unknown_report:
        raise DevelopmentMemoryError(
            f"unknown runtime report fields: {sorted(unknown_report)}"
        )
    if report_payload.get("schema_version") != 1:
        raise DevelopmentMemoryError("runtime report schema_version must be 1")
    raw_results = report_payload.get("results")
    raw_missing = report_payload.get("missing_probe_ids")
    if not isinstance(raw_results, list) or not isinstance(raw_missing, list):
        raise DevelopmentMemoryError("runtime report results/missing_probe_ids are invalid")

    results: list[RuntimeProbeResult] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise DevelopmentMemoryError("runtime probe result must be an object")
        allowed_result = {
            "schema_version",
            "probe_id",
            "status",
            "source_sha",
            "attempt",
            "detail_code",
        }
        unknown_result = set(raw) - allowed_result
        if unknown_result:
            raise DevelopmentMemoryError(
                f"unknown runtime probe result fields: {sorted(unknown_result)}"
            )
        results.append(
            RuntimeProbeResult(
                schema_version=raw.get("schema_version", 0),
                probe_id=raw.get("probe_id", ""),
                status=RuntimeProbeStatus(raw.get("status")),
                source_sha=raw.get("source_sha", ""),
                attempt=raw.get("attempt", 0),
                detail_code=raw.get("detail_code"),
            )
        )
    try:
        disposition = RuntimeVerificationDisposition(
            report_payload.get("disposition")
        )
    except (TypeError, ValueError) as exc:
        raise DevelopmentMemoryError("runtime report disposition is invalid") from exc

    report = RuntimeVerificationReport(
        schema_version=1,
        verification_id=report_payload.get("verification_id", ""),
        contract_fingerprint=report_payload.get("contract_fingerprint", ""),
        source_sha=report_payload.get("source_sha", ""),
        disposition=disposition,
        results=tuple(results),
        missing_probe_ids=tuple(str(item) for item in raw_missing),
    )
    if payload.get("report_fingerprint") != report.fingerprint():
        raise DevelopmentMemoryError("runtime report fingerprint mismatch")
    return report


def build_verified_runtime_feedback_record(
    *,
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
    report: RuntimeVerificationReport,
    contract_path: str,
    receipt_path: str,
    report_path: str,
) -> DevelopmentMemoryRecord:
    if receipt.status != "VERIFIED":
        raise DevelopmentMemoryError("runtime feedback requires VERIFIED receipt")
    if receipt.verification_id != contract.verification_id:
        raise DevelopmentMemoryError("runtime feedback verification id mismatch")
    if receipt.target_repository != contract.target_repository:
        raise DevelopmentMemoryError("runtime feedback repository mismatch")
    if receipt.source_sha != contract.source_sha:
        raise DevelopmentMemoryError("runtime feedback receipt source mismatch")
    if receipt.contract_fingerprint != contract.fingerprint():
        raise DevelopmentMemoryError("runtime feedback contract fingerprint mismatch")

    evaluated = evaluate_runtime_verification(contract, report.results)
    if evaluated.canonical_dict() != report.canonical_dict():
        raise DevelopmentMemoryError(
            "runtime feedback report does not match trusted evaluation"
        )
    if report.disposition is not RuntimeVerificationDisposition.VERIFIED:
        raise DevelopmentMemoryError("runtime feedback report is not VERIFIED")

    receipt_fingerprint = _sha256(receipt.canonical_dict())
    identity = _sha256(
        {
            "kind": "runtime-feedback",
            "verification_id": receipt.verification_id,
            "task_id": receipt.task_id,
            "contract_fingerprint": contract.fingerprint(),
            "report_fingerprint": report.fingerprint(),
        }
    )
    return DevelopmentMemoryRecord(
        memory_id="mem-" + identity[:24],
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=contract.target_repository,
        source_sha=contract.source_sha,
        statement=(
            "Trusted runtime verification completed with every required probe passing "
            "against the exact source SHA."
        ),
        task_id=receipt.task_id,
        evidence_paths=(contract_path, receipt_path, report_path),
        evidence_fingerprints=(
            contract.fingerprint(),
            receipt_fingerprint,
            report.fingerprint(),
        ),
        tags=("feedback", "runtime", "verified"),
    )
