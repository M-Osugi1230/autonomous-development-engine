from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_probe():
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        path = TRUSTED_DIR / "dag_dispatch_probe.py"
        spec = importlib.util.spec_from_file_location(
            "trusted_dag_dispatch_probe_test",
            path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load dag_dispatch_probe.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class TrustedDagDispatchProbeTests(unittest.TestCase):
    def test_probe_proves_dag_and_fifo_paths(self) -> None:
        module = load_probe()
        result = module.run_probe()

        self.assertTrue(result["ok"])
        self.assertEqual(result["dag_selected"], "independent")
        self.assertEqual(result["blocked_descendant"], "PENDING")
        self.assertEqual(result["human_wait"], "HUMAN_WAIT")
        self.assertEqual(result["blocked_project_status"], "BLOCKED")
        self.assertEqual(result["fifo_selected"], "fifo-next")

    def test_probe_main_returns_zero(self) -> None:
        module = load_probe()
        self.assertEqual(module.main(), 0)


if __name__ == "__main__":
    unittest.main()
