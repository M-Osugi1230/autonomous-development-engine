from __future__ import annotations
import unittest
from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask

class AcceptedPlanTests(unittest.TestCase):
    def plan(self):
        return DevelopmentPlan("Build helpers",(PlannedTask("a","A","Add A",(),("src/ade/a.py",),("A passes",)),PlannedTask("b","B","Add B",("a",),("tests/test_a.py",),("B passes",))))

    def test_round_trip_preserves_fingerprint(self):
        accepted=AcceptedPlan.accept(self.plan())
        loaded=AcceptedPlan.from_dict(accepted.to_dict())
        self.assertEqual(loaded.fingerprint,accepted.fingerprint)
        self.assertEqual(loaded.plan.canonical_dict(),accepted.plan.canonical_dict())

    def test_tamper_is_rejected(self):
        payload=AcceptedPlan.accept(self.plan()).to_dict()
        payload["plan"]["goal"]="Changed goal"
        with self.assertRaisesRegex(ValueError,"fingerprint"):
            AcceptedPlan.from_dict(payload)

if __name__=="__main__":
    unittest.main()
