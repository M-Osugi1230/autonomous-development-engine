from __future__ import annotations
import unittest
from ade.goal_planner import GoalWorkItem, plan_goal

class GoalPlannerTests(unittest.TestCase):
    def test_goal_becomes_stable_valid_plan_without_task_prompts(self):
        items=(GoalWorkItem("Model","Add model",("src/ade/model.py",),("model tests pass",)),GoalWorkItem("Tests","Test model",("tests/test_model.py",),("coverage exists",),(1,)))
        a=plan_goal("Ship model",items,id_prefix="p16")
        b=plan_goal("Ship model",items,id_prefix="p16")
        self.assertEqual(a.fingerprint(),b.fingerprint())
        self.assertEqual(a.tasks[1].depends_on,("p16-001",))
        self.assertIn("Goal: Ship model",a.tasks[0].prompt)

    def test_forward_dependency_rejected(self):
        with self.assertRaisesRegex(ValueError,"earlier"):
            plan_goal("g",(GoalWorkItem("x","x",("src/x.py",),("x",),(1,)),))

if __name__=="__main__":
    unittest.main()
