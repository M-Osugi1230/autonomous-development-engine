from __future__ import annotations
import unittest
from scripts.v1_1_zero_touch_fixture import build_fixture

class V11ZeroTouchFixtureTests(unittest.TestCase):
    def test_fixture_matches_frozen_real_campaign(self):
        payload=build_fixture()
        self.assertEqual(payload["accepted"]["status"],"ACCEPTED")
        self.assertEqual(payload["accepted"]["fingerprint"],"8a28b3354e54c690d7ab3103fe0450b87d0bf68db2ef2ad19d295dbc099f747e")
        self.assertEqual(payload["campaign"]["campaign_id"],"v1.1-zero-touch-proof-001")
        self.assertEqual(payload["campaign"]["status"],"RUNNING")
        self.assertEqual(payload["graph"]["tasks"][0]["status"],"RUNNING")
        self.assertEqual(payload["graph"]["tasks"][1]["status"],"PENDING")
        self.assertEqual(payload["graph"]["tasks"][1]["depends_on"],["v1-1-zero-touch-001"])
        self.assertEqual(payload["cycle_task"]["task_id"],"v1-1-zero-touch-001")

if __name__=="__main__":
    unittest.main()
