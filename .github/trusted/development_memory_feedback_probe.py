from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.development_memory_feedback import (
    build_verified_runtime_feedback_record,
)
from ade.development_memory_store import DevelopmentMemoryStore
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from development_memory_feedback import (
    STORE_PATH,
    persist_verified_runtime_feedback,
)


SHA = "a" * 40


class FakeApi:
    def __init__(self) -> None:
        self.payload = DevelopmentMemoryStore().canonical_dict()
        self.writes: list[tuple[str, dict, str]] = []

    def get_json_file(self, path: str):
        if path != STORE_PATH:
            raise AssertionError(path)
        return self.payload, "fake-sha"

    def upsert_json_file(self, path: str, payload: dict, *, message: str):
        if path != STORE_PATH:
            raise AssertionError(path)
        self.payload = payload
        self.writes.append((path, payload, message))


class FailWriteApi(FakeApi):
    def upsert_json_file(self, path: str, payload: dict, *, message: str):
        raise RuntimeError("simulated memory-store write failure")


def values():
    contract = RuntimeVerificationContract(
        verification_id="rv-feedback-proof",
        target_repository="owner/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )
    report = evaluate_runtime_verification(
        contract,
        (
            RuntimeProbeResult(
                probe_id="offline-cli-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
                attempt=1,
                detail_code="offline-cli-pass",
            ),
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
                attempt=1,
                detail_code="production-import-pass",
            ),
        ),
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="task-001",
        target_repository=contract.target_repository,
        source_sha=contract.source_sha,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )
    return contract, receipt, report


def main() -> int:
    contract, receipt, report = values()
    record = build_verified_runtime_feedback_record(
        contract=contract,
        receipt=receipt,
        report=report,
        contract_path=".autodev/runtime-verification/task-001/contract.json",
        receipt_path=".autodev/runtime-verification/task-001/receipt.json",
        report_path=".autodev/runtime-verification/task-001/report.json",
    )

    api = FakeApi()
    first = persist_verified_runtime_feedback(
        api,
        contract=contract,
        receipt=receipt,
        report=report,
        contract_path=".autodev/runtime-verification/task-001/contract.json",
        receipt_path=".autodev/runtime-verification/task-001/receipt.json",
        report_path=".autodev/runtime-verification/task-001/report.json",
    )
    assert first["state"] == "ADDED"
    assert first["memory_id"] == record.memory_id
    assert len(api.writes) == 1

    second = persist_verified_runtime_feedback(
        api,
        contract=contract,
        receipt=receipt,
        report=report,
        contract_path=".autodev/runtime-verification/task-001/contract.json",
        receipt_path=".autodev/runtime-verification/task-001/receipt.json",
        report_path=".autodev/runtime-verification/task-001/report.json",
    )
    assert second["state"] == "UNCHANGED"
    assert len(api.writes) == 1

    stored = DevelopmentMemoryStore.from_dict(api.payload)
    assert len(stored.ledger.records) == 1
    assert stored.ledger.records[0].source_sha == SHA

    print(json.dumps({
        "ok": True,
        "runtime_feedback_record_source_bound": True,
        "store_persistence_idempotent": True,
        "duplicate_write_suppressed": True,
        "record_count": len(stored.ledger.records),
        "memory_id": record.memory_id,
        "store_fingerprint": stored.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
