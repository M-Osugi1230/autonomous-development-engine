from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


class RunJulesCycleImportTests(unittest.TestCase):
    def test_operational_script_imports_without_side_effects(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_jules_cycle.py"
        spec = importlib.util.spec_from_file_location("ade_run_jules_cycle_import_test", script_path)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertIsNotNone(spec.loader)
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)

        self.assertTrue(callable(module.main))
        self.assertTrue(callable(module.write_result))


if __name__ == "__main__":
    unittest.main()
