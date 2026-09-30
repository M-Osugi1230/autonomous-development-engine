from __future__ import annotations

import hashlib
from typing import Any

from ade.development_memory import DevelopmentMemoryError
from ade.development_memory_extraction import extract_recovery_memory
from ade.development_memory_feedback import (
    build_verified_runtime_feedback_record,
)
from ade.development_memory_store import (
    DevelopmentMemoryStore,
    merge_memory_records,
)
from ade.recovery_runtime import RecoveryRecord
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationReport,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from github_client import GitHubClient, GitHubError


STORE_PATH = ".autodev/development-memory.json"


def _safe_error_fingerprint(exc: BaseException) -> str:
    detail = str(exc).splitlines()[0].strip()[:256] or type(exc).__name__
    return hashlib.sha256(detail.encode("utf-8")).hexdigest()


def load_memory_store(api: GitHubClient) -> DevelopmentMemoryStore:
    try:
        payload, _ = api.get_json_file(STORE_PATH)
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return DevelopmentMemoryStore()
        raise
    return DevelopmentMemoryStore.from_dict(payload)


def _persist_record(
    api: GitHubClient,
    record,
    *,
    message: str,
) -> dict[str, Any]:
    current = load_memory_store(api)
    update = merge_memory_records(current, (record,))
    if update.changed:
        api.upsert_json_file(
            STORE_PATH,
            update.store.canonical_dict(),
            message=message,
        )
    return {
        "schema_version": 1,
        "state": "ADDED" if update.changed else "UNCHANGED",
        "memory_id": record.memory_id,
        "memory_kind": record.kind.value,
        "repository": record.repository,
        "source_sha": record.source_sha,
        "store_fingerprint": update.store.fingerprint(),
        "record_count": len(update.store.ledger.records),
    }


def persist_verified_runtime_feedback(
    api: GitHubClient,
    *,
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
    report: RuntimeVerificationReport,
    contract_path: str,
    receipt_path: str,
    report_path: str,
) -> dict[str, Any]:
    record = build_verified_runtime_feedback_record(
        contract=contract,
        receipt=receipt,
        report=report,
        contract_path=contract_path,
        receipt_path=receipt_path,
        report_path=report_path,
    )
    return _persist_record(
        api,
        record,
        message=f"memory: runtime verified {receipt.task_id}",
    )


def persist_recovery_feedback(
    api: GitHubClient,
    *,
    recovery: RecoveryRecord,
    repository: str,
    source_sha: str,
) -> dict[str, Any]:
    record = extract_recovery_memory(
        evidence_path=".autodev/runtime/recovery.json",
        recovery_payload=recovery.to_dict(),
        repository=repository,
        source_sha=source_sha,
    )
    return _persist_record(
        api,
        record,
        message=f"memory: recovery {recovery.task_id}",
    )


def feedback_failure(exc: BaseException) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "FAILED",
        "error_fingerprint": _safe_error_fingerprint(exc),
        "error_type": type(exc).__name__,
    }
