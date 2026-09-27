from __future__ import annotations
import json, subprocess, sys, unittest

class Phase16GoalFixtureTests(unittest.TestCase):
    def test_fixture_emits_valid_two_task_goal_campaign(self):
        out=subprocess.check_output([sys.executable,"scripts/phase16_goal_fixture.py"],text=True)
        payload=json.loads(out)
        self.assertEqual(payload["accepted"]["status"],"ACCEPTED")
        self.assertEqual(len(payload["campaign"]["task_ids"]),2)
        self.assertEqual(payload["graph"]["tasks"][0]["status"],"PENDING")
        self.assertEqual(payload["graph"]["tasks"][1]["depends_on"],["phase16-goal-001"])
        self.assertEqual(payload["accepted"]["fingerprint"],payload["accepted"]["fingerprint"].lower())

if __name__=="__main__":
    unittest.main()
