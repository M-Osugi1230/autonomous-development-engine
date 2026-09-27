from __future__ import annotations
import unittest
from ade.recovery import RecoveryAction, RecoveryBudget, RecoveryFailure, RecoveryProgress, choose_recovery

class RecoveryPolicyTests(unittest.TestCase):
    def test_failure_classes_map_to_bounded_actions(self):
        self.assertEqual(choose_recovery(RecoveryFailure.INFRASTRUCTURE, RecoveryProgress()), RecoveryAction.RETRY)
        self.assertEqual(choose_recovery(RecoveryFailure.CI_FAILURE, RecoveryProgress()), RecoveryAction.REPAIR)
        self.assertEqual(choose_recovery(RecoveryFailure.MERGE_CONFLICT, RecoveryProgress()), RecoveryAction.REBASE)
        self.assertEqual(choose_recovery(RecoveryFailure.INVALID_IMPLEMENTATION, RecoveryProgress()), RecoveryAction.REPLAN)

    def test_budgets_stop_unbounded_recovery(self):
        exhausted=RecoveryProgress(retries=2, repairs=2, rebases=1, replans=1)
        self.assertEqual(choose_recovery(RecoveryFailure.INFRASTRUCTURE, exhausted), RecoveryAction.FAIL)
        self.assertEqual(choose_recovery(RecoveryFailure.CI_FAILURE, exhausted), RecoveryAction.FAIL)
        self.assertEqual(choose_recovery(RecoveryFailure.MERGE_CONFLICT, exhausted), RecoveryAction.HUMAN_WAIT)

    def test_repeated_identical_failure_escalates(self):
        self.assertEqual(choose_recovery(RecoveryFailure.CI_FAILURE, RecoveryProgress(repeated_failures=3)), RecoveryAction.HUMAN_WAIT)

if __name__ == "__main__":
    unittest.main()
