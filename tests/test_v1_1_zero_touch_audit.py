from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v1_1_zero_touch_audit import audit


class V11ZeroTouchAuditTests(unittest.TestCase):
    def test_repository_evidence_closes_v1_1(self) -> None:
        result = audit(Path("."))
        self.assertTrue(result["v1_1_zero_touch_graduated"], result)
        self.assertEqual(result["missing_proofs"], [])
        self.assertTrue(all(result["checks"].values()))

    def test_audit_does_not_depend_on_current_live_autodev_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in (
                ".autodev/campaign-evidence/v1.1-zero-touch-proof-001.json",
                ".github/workflows/ci.yml",
                ".github/workflows/zero-touch-start.yml",
                "src/ade/mission_control.py",
            ):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(relative), destination)

            # Deliberately do not copy current AcceptedPlan/Campaign/DAG/state
            # or runtime receipt. Graduation must be reproducible from the
            # immutable terminal snapshot plus current proof definitions.
            result = audit(root)
            self.assertTrue(result["v1_1_zero_touch_graduated"], result)


if __name__ == "__main__":
    unittest.main()
