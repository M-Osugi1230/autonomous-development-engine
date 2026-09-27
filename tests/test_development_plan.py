from __future__ import annotations
import unittest
from ade.development_plan import DevelopmentPlan, PlannedTask

def task(i, deps=(), paths=("src/ade/example.py",)):
    return PlannedTask(f"p{i}",f"Task {i}",f"Implement task {i}",tuple(deps),tuple(paths),(f"task {i} passes tests",))

class DevelopmentPlanTests(unittest.TestCase):
    def test_stable_fingerprint(self):
        a=DevelopmentPlan("  Add   feature ",(task(1),task(2,("p1",))))
        b=DevelopmentPlan("Add feature",(task(1),task(2,("p1",))))
        self.assertEqual(a.fingerprint(),b.fingerprint())

    def test_cycle_rejected(self):
        with self.assertRaisesRegex(ValueError,"cyclic"):
            DevelopmentPlan("g",(task(1,("p2",)),task(2,("p1",)))).validate()

    def test_unsafe_scope_rejected(self):
        with self.assertRaisesRegex(ValueError,"unsafe"):
            DevelopmentPlan("g",(task(1,paths=(".github/workflows/ci.yml",)),)).validate()

    def test_overbroad_plan_rejected(self):
        with self.assertRaises(ValueError):
            DevelopmentPlan("g",tuple(task(i) for i in range(13))).validate()

if __name__=="__main__":
    unittest.main()
