from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_probe():
    path = Path(__file__).resolve().parents[1] / "scripts" / "multi_provider_probe.py"
    spec = importlib.util.spec_from_file_location("multi_provider_probe_test_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load multi_provider_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MultiProviderProbeTests(unittest.TestCase):
    def test_probe_proves_failover_and_sticky_resume(self) -> None:
        module = load_probe()
        result = module.run_probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["preferred"], "primary")
        self.assertEqual(result["quota_fallback"], "fallback")
        self.assertEqual(result["sticky_resume"], "primary")
        self.assertEqual(result["post_session_failover"], "blocked")
        self.assertEqual(result["no_provider"], "NO_PROVIDER")

    def test_main_returns_zero(self) -> None:
        module = load_probe()
        self.assertEqual(module.main(), 0)


if __name__ == "__main__":
    unittest.main()
