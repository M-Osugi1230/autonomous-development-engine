from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_probe_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "human_decision_probe.py"
    spec = importlib.util.spec_from_file_location("human_decision_probe_test_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load human_decision_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HumanDecisionProbeTests(unittest.TestCase):
    def test_phase7_lifecycle_probe(self) -> None:
        module = load_probe_module()
        result = module.run_probe()

        self.assertTrue(result["ok"])
        self.assertEqual(result["routine"], "PROCEED")
        self.assertEqual(result["destructive"], "HUMAN_WAIT")
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["final_status"], "RESOLVED")
        self.assertEqual(result["selected_option"], "reject")

    def test_probe_main_returns_zero(self) -> None:
        module = load_probe_module()
        self.assertEqual(module.main(), 0)


if __name__ == "__main__":
    unittest.main()
