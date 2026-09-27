from __future__ import annotations
import unittest
from scripts.phase17_graduation_fixture import build

class GraduationFixtureTests(unittest.TestCase):
    def test_three_task_generated_campaign(self):
        payload=build()
        self.assertEqual(payload["campaign"]["campaign_id"],"phase17-production-graduation-001")
        self.assertEqual(len(payload["campaign"]["task_ids"]),3)
        tasks=payload["graph"]["tasks"]
        self.assertEqual(tasks[0]["depends_on"],[])
        self.assertEqual(tasks[1]["depends_on"],["phase17-final-001"])
        self.assertEqual(tasks[2]["depends_on"],["phase17-final-001","phase17-final-002"])
        self.assertEqual(payload["accepted"]["status"],"ACCEPTED")
if __name__=="__main__": unittest.main()
