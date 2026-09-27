import unittest
from ade.repair import FailureKind, RepairPolicy
from ade.recovery import RecoveryAction, decide_recovery_action

class RecoveryTests(unittest.TestCase):
    def test_ci_failure_creates_bounded_repair_task(self):
        d=decide_recovery_action(FailureKind.CI_FAILURE,attempt=0,replan_count=0)
        self.assertEqual(d.action,RecoveryAction.REPAIR_TASK)
        exhausted=decide_recovery_action(FailureKind.CI_FAILURE,attempt=0,replan_count=1)
        self.assertEqual(exhausted.action,RecoveryAction.FAIL)

    def test_merge_conflict_rebases_and_replans(self):
        self.assertEqual(decide_recovery_action(FailureKind.MERGE_CONFLICT,attempt=0,replan_count=0).action,RecoveryAction.REBASE_REPLAN)

    def test_provider_error_retries_with_budget(self):
        p=RepairPolicy(max_retries=1,max_replans=0)
        self.assertEqual(decide_recovery_action(FailureKind.PROVIDER_ERROR,attempt=0,replan_count=0,policy=p).action,RecoveryAction.RETRY)
        self.assertEqual(decide_recovery_action(FailureKind.PROVIDER_ERROR,attempt=1,replan_count=0,policy=p).action,RecoveryAction.FAIL)

if __name__=="__main__": unittest.main()
