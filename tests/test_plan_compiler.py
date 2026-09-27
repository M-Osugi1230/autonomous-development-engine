from __future__ import annotations
import unittest
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.plan_compiler import compile_plan

class PlanCompilerTests(unittest.TestCase):
    def test_compile_preserves_goal_dependencies_scope_and_acceptance(self):
        plan=DevelopmentPlan("Ship safe helper",(
            PlannedTask("g1","Helper","Add helper",(),("src/ade/helper.py",),("helper tests pass",)),
            PlannedTask("g2","Tests","Add tests",("g1",),("tests/test_helper.py",),("tests cover helper",)),
        ))
        campaign,graph=compile_plan(plan,campaign_id="goal-1")
        self.assertEqual(campaign.task_ids,("g1","g2"))
        self.assertEqual(graph.tasks[1].depends_on,("g1",))
        self.assertIn("Allowed paths: tests/test_helper.py",graph.tasks[1].task.prompt)
        self.assertIn("Acceptance: tests cover helper",graph.tasks[1].task.prompt)
        self.assertIn("Do not modify files outside",graph.tasks[1].task.prompt)

    def test_invalid_plan_never_compiles(self):
        plan=DevelopmentPlan("unsafe",(PlannedTask("g1","x","x",(),(".autodev/state.json",),("x",)),))
        with self.assertRaises(ValueError):
            compile_plan(plan,campaign_id="goal-unsafe")

if __name__=="__main__":
    unittest.main()
