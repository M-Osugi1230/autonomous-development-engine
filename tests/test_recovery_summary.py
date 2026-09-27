import unittest

from ade.recovery import RecoveryAction, RecoveryFailure, RecoveryProgress
from ade.recovery_runtime import RecoveryRecord
from ade.recovery_summary import summarize_recovery, summarize_recovery_record


class RecoverySummaryTests(unittest.TestCase):
    def test_summarize_recovery_record_object(self) -> None:
        record = RecoveryRecord(
            task_id="task-42",
            failure=RecoveryFailure.CI_FAILURE,
            action=RecoveryAction.REPAIR,
            progress=RecoveryProgress(retries=1, repairs=2, rebases=0, replans=0, repeated_failures=1),
            fingerprint="secret_fingerprint_data",
        )
        summary = summarize_recovery(record)
        self.assertEqual(
            summary,
            {
                "task_id": "task-42",
                "failure": "CI_FAILURE",
                "action": "REPAIR",
                "retries": 1,
                "repairs": 2,
                "rebases": 0,
                "replans": 0,
                "repeated_failures": 1,
            },
        )
        # Ensure fingerprint / secret data is omitted
        self.assertNotIn("fingerprint", summary)

    def test_summarize_recovery_from_dict_and_alias(self) -> None:
        raw_dict = {
            "schema_version": 1,
            "task_id": "task-99",
            "failure": "INFRASTRUCTURE",
            "action": "RETRY",
            "fingerprint": "sensitive_hash_123",
            "progress": {
                "retries": 2,
                "repairs": 0,
                "rebases": 0,
                "replans": 0,
                "repeated_failures": 2,
            },
        }
        summary = summarize_recovery_record(raw_dict)
        self.assertEqual(summary["task_id"], "task-99")
        self.assertEqual(summary["failure"], "INFRASTRUCTURE")
        self.assertEqual(summary["action"], "RETRY")
        self.assertEqual(summary["retries"], 2)
        self.assertEqual(summary["repeated_failures"], 2)
        self.assertNotIn("fingerprint", summary)

    def test_invalid_type_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            summarize_recovery(12345)  # type: ignore[arg-type]

    def test_intentional_proof_failure(self) -> None:
        # INTENTIONAL RECOVERY PROOF: Exactly one test assertion intentionally fails on first implementation.
        # To repair on re-dispatch after CI failure, change 999 to 0.
        record = RecoveryRecord(
            task_id="task-proof",
            failure=RecoveryFailure.TIMEOUT,
            action=RecoveryAction.REPLAN,
            progress=RecoveryProgress(retries=0, repairs=0, rebases=0, replans=1, repeated_failures=1),
            fingerprint="fp-1",
        )
        summary = summarize_recovery(record)
        self.assertEqual(summary["retries"], 999)  # Intentionally failing assertion
