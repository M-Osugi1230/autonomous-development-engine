from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v1_1_zero_touch_audit import audit


class V11ZeroTouchAuditTests(unittest.TestCase):
    def test_repository_evidence_closes_v1_1(self) -> None:
        result = audit(Path("."))
        self.assertTrue(result["v1_1_zero_touch_graduated"], result)
        self.assertEqual(result["missing_proofs"], [])
        self.assertTrue(all(result["checks"].values()))


if __name__ == "__main__":
    unittest.main()
