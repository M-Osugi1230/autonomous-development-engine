from __future__ import annotations

import copy
import unittest

from ade.development_memory import DevelopmentMemoryError, MemoryKind
from ade.development_memory_feedback import (
    build_verified_runtime_feedback_record,
    runtime_report_from_wrapper,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


SHA = "a" * 40
HASH_B = "2" * 64
HASH_C = "3" * 64


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-test",
        target_repository="owner/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


def report():
    c = contract()
    return evaluate_runtime_verification(
        c,
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


def receipt() -> RuntimeVerificationReceipt:
    c = contract()
    return RuntimeVerificationReceipt(
        verification_id=c.verification_id,
        task_id="task-001",
        target_repository=c.target_repository,
        source_sha=c.source_sha,
        contract_fingerprint=c.fingerprint(),
        registry_fingerprint=HASH_B,
        policy_fingerprint=HASH_C,
        status="VERIFIED",
        dispatch_count=1,
    )


def wrapper() -> dict:
    r = report()
    return {
        "schema_version": 1,
        "report": r.canonical_dict(),
        "report_fingerprint": r.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


class DevelopmentMemoryFeedbackTests(unittest.TestCase):
    def test_report_wrapper_round_trip_and_feedback_record(self) -> None:
        parsed = runtime_report_from_wrapper(wrapper())
        self.assertEqual(parsed.canonical_dict(), report().canonical_dict())

        record = build_verified_runtime_feedback_record(
            contract=contract(),
            receipt=receipt(),
            report=parsed,
            contract_path=".autodev/runtime-verification/task/contract.json",
            receipt_path=".autodev/runtime-verification/task/receipt.json",
            report_path=".autodev/runtime-verification/task/report.json",
        )
        self.assertEqual(record.kind, MemoryKind.VERIFIED_OUTCOME)
        self.assertEqual(record.repository, "owner/target")
        self.assertEqual(record.source_sha, SHA)
        self.assertEqual(record.task_id, "task-001")
        self.assertEqual(record.tags, ("feedback", "runtime", "verified"))
        self.assertEqual(len(record.evidence_fingerprints), 3)

    def test_tampered_wrapper_and_failed_receipt_are_rejected(self) -> None:
        tampered = copy.deepcopy(wrapper())
        tampered["report"]["results"][0]["status"] = "FAIL"
        with self.assertRaisesRegex(DevelopmentMemoryError, "fingerprint"):
            runtime_report_from_wrapper(tampered)

        bad_receipt = receipt()
        object.__setattr__(bad_receipt, "status", "FAILED")
        with self.assertRaisesRegex(DevelopmentMemoryError, "VERIFIED receipt"):
            build_verified_runtime_feedback_record(
                contract=contract(),
                receipt=bad_receipt,
                report=report(),
                contract_path=".autodev/runtime-verification/task/contract.json",
                receipt_path=".autodev/runtime-verification/task/receipt.json",
                report_path=".autodev/runtime-verification/task/report.json",
            )

    def test_report_must_match_trusted_re_evaluation(self) -> None:
        c = contract()
        r = report()
        object.__setattr__(r, "contract_fingerprint", "f" * 64)
        with self.assertRaisesRegex(DevelopmentMemoryError, "trusted evaluation"):
            build_verified_runtime_feedback_record(
                contract=c,
                receipt=receipt(),
                report=r,
                contract_path=".autodev/runtime-verification/task/contract.json",
                receipt_path=".autodev/runtime-verification/task/receipt.json",
                report_path=".autodev/runtime-verification/task/report.json",
            )


if __name__ == "__main__":
    unittest.main()
