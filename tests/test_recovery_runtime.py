from __future__ import annotations
import unittest
from ade.recovery import RecoveryAction, RecoveryFailure
from ade.recovery_runtime import RecoveryRecord, advance_recovery

class RecoveryRuntimeTests(unittest.TestCase):
    def test_round_trip_preserves_budget_progress(self):
        first=advance_recovery("t1", RecoveryFailure.INFRASTRUCTURE, "timeout")
        loaded=RecoveryRecord.from_dict(first.to_dict())
        second=advance_recovery("t1", RecoveryFailure.INFRASTRUCTURE, "timeout", loaded)
        self.assertEqual(second.action, RecoveryAction.RETRY)
        self.assertEqual(second.progress.retries, 2)
        self.assertEqual(second.progress.repeated_failures, 2)

    def test_third_identical_failure_enters_human_wait(self):
        one=advance_recovery("t1", RecoveryFailure.CI_FAILURE, "same-ci")
        two=advance_recovery("t1", RecoveryFailure.CI_FAILURE, "same-ci", one)
        three=advance_recovery("t1", RecoveryFailure.CI_FAILURE, "same-ci", two)
        self.assertEqual(three.action, RecoveryAction.HUMAN_WAIT)
        self.assertEqual(three.progress.repairs, 2)

    def test_changed_fingerprint_resets_repeat_counter_not_budget(self):
        one=advance_recovery("t1", RecoveryFailure.CI_FAILURE, "lint")
        two=advance_recovery("t1", RecoveryFailure.CI_FAILURE, "unit-test", one)
        self.assertEqual(two.progress.repeated_failures, 1)
        self.assertEqual(two.progress.repairs, 2)

if __name__ == "__main__":
    unittest.main()
