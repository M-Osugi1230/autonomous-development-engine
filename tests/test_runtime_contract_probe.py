from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_probe():
    path = TRUSTED_DIR / "runtime_contract_probe.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_contract_probe_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_contract_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeContractProbeTests(unittest.TestCase):
    def test_trusted_probe_passes(self) -> None:
        module = load_probe()
        self.assertEqual(module.main(), 0)


if __name__ == "__main__":
    unittest.main()
