from __future__ import annotations

import unittest

from ade.recovery import RecoveryAction, RecoveryFailure
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    evaluate_runtime_verification,
)
from ade.runtime_verification_recovery import (
    contain_runtime_verification_failure,
    runtime_failure_fingerprint,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


SHA = "a" * 40
HASH = "b" * 64


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + SHA,
        target_repository="example/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("runtime-smoke",),
        max_attempts=1,
        timeout_seconds=30,
    )


def failed_report():
    c = contract()
    return evaluate_runtime_verification(
        c,
        [
            RuntimeProbeResult(
                probe_id="runtime-smoke",
                status=RuntimeProbeStatus.FAIL,
                source_sha=SHA,
                detail_code="runtime-failed",
            )
        ],
    )


def failed_receipt() -> RuntimeVerificationReceipt:
    c = contract()
    return RuntimeVerificationReceipt(
        verification_id=c.verification_id,
        task_id="task-002",
        target_repository=c.target_repository,
        source_sha=c.source_sha,
        contract_fingerprint=c.fingerprint(),
        registry_fingerprint=HASH,
        policy_fingerprint="c" * 64,
        status="FAILED",
        dispatch_count=1,
    )


class RuntimeVerificationRecoveryTests(unittest.TestCase):
    def test_failed_runtime_verification_reopens_terminal_campaign_as_human_wait(self) -> None:
        report = failed_report()
        self.assertEqual(report.disposition, RuntimeVerificationDisposition.FAILED)
        transition = contain_runtime_verification_failure(
            receipt=failed_receipt(),
            report=report,
            state_payload={
                "schema_version": 1,
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
                "metadata": {"target_repository": "example/target"},
            },
            campaign_payload={
                "schema_version": 1,
                "campaign_id": "campaign-001",
                "goal": "ship feature",
                "task_ids": ["task-001", "task-002"],
                "completed_task_ids": ["task-001", "task-002"],
                "status": "COMPLETED",
            },
        )
        self.assertEqual(transition.recovery.failure, RecoveryFailure.RUNTIME_VERIFICATION)
        self.assertEqual(transition.recovery.action, RecoveryAction.HUMAN_WAIT)
        self.assertEqual(transition.receipt.status, "HUMAN_WAIT")
        self.assertEqual(transition.state["status"], "HUMAN_WAIT")
        self.assertEqual(transition.state["current_task_id"], "task-002")
        self.assertEqual(transition.campaign["status"], "HUMAN_WAIT")
        self.assertEqual(
            transition.campaign["completed_task_ids"],
            ["task-001", "task-002"],
        )
        metadata = transition.state["metadata"]
        self.assertEqual(
            metadata["next_required_human_action"],
            "review-runtime-verification-failure",
        )
        self.assertIsNone(metadata["next_system_action"])
        self.assertEqual(
            metadata["runtime_verification_failure_fingerprint"],
            report.fingerprint(),
        )

    def test_adapter_error_uses_secret_free_fingerprint_only(self) -> None:
        detail = "deployment adapter failed bearer super-secret-value"
        fingerprint = runtime_failure_fingerprint(detail)
        transition = contain_runtime_verification_failure(
            receipt=failed_receipt(),
            failure_fingerprint=fingerprint,
            state_payload={
                "status": "READY",
                "current_task_id": None,
                "metadata": {"target_repository": "example/target"},
            },
            campaign_payload={
                "campaign_id": "campaign-001",
                "task_ids": ["task-002"],
                "completed_task_ids": ["task-002"],
                "status": "COMPLETED",
            },
        )
        metadata_text = str(transition.state["metadata"])
        self.assertNotIn("super-secret-value", metadata_text)
        self.assertEqual(
            transition.state["metadata"]["runtime_verification_failure_fingerprint"],
            fingerprint,
        )

    def test_repository_drift_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "repository drift"):
            contain_runtime_verification_failure(
                receipt=failed_receipt(),
                report=failed_report(),
                state_payload={
                    "status": "READY",
                    "current_task_id": None,
                    "metadata": {"target_repository": "other/target"},
                },
                campaign_payload={
                    "campaign_id": "campaign-001",
                    "task_ids": ["task-002"],
                    "completed_task_ids": ["task-002"],
                    "status": "COMPLETED",
                },
            )

    def test_nonfailed_receipt_is_rejected(self) -> None:
        receipt = failed_receipt()
        verified = RuntimeVerificationReceipt(
            **{**receipt.canonical_dict(), "status": "VERIFIED"}
        )
        with self.assertRaisesRegex(ValueError, "FAILED receipt"):
            contain_runtime_verification_failure(
                receipt=verified,
                report=failed_report(),
                state_payload={"metadata": {}},
                campaign_payload={"task_ids": ["task-002"]},
            )


if __name__ == "__main__":
    unittest.main()
