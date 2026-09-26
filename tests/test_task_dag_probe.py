from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "task_dag_probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("task_dag_probe_test_module", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load task_dag_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TaskDagProbeTests(unittest.TestCase):
    def test_human_wait_blocks_only_its_descendants(self) -> None:
        module = load_probe()
        result = module.run_probe()

        self.assertTrue(result["ok"])
        self.assertEqual(result["waiting_branch"], "branch-a")
        self.assertTrue(result["independent_completed"])
        self.assertEqual(result["blocked_child"], "branch-a-child")
        self.assertEqual(
            result["unlocked_after_resolution"],
            ["branch-a-child"],
        )
        self.assertEqual(result["decision_id"], "decision-a")

    def test_main_emits_compact_json_without_traceback(self) -> None:
        module = load_probe()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main()

        self.assertEqual(code, 0)
        line = stdout.getvalue().strip()
        payload = json.loads(line)
        self.assertTrue(payload["ok"])
        self.assertNotIn("Traceback", line)


if __name__ == "__main__":
    unittest.main()
