from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mission_control_probe.py"
SCRIPTS_DIR = SCRIPT_PATH.parent


def load_probe_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "mission_control_probe_test_module",
            SCRIPT_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load mission_control_probe.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class MissionControlProbeTests(unittest.TestCase):
    def test_probe_proves_safe_read_only_artifact(self) -> None:
        module = load_probe_module()
        result = module.run_probe()

        self.assertTrue(result["ok"])
        self.assertEqual(result["project_id"], "mission-control-probe")
        self.assertEqual(result["completed_tasks"], 3)
        self.assertEqual(result["failed_tasks"], 1)
        self.assertEqual(result["queue_depth"], 2)
        self.assertEqual(result["open_decision_id"], "decision-phase8-proof")
        self.assertGreaterEqual(result["warning_count"], 1)
        self.assertEqual(result["artifact_files"], ["index.html", "snapshot.json"])

    def test_main_emits_compact_json_and_returns_zero(self) -> None:
        module = load_probe_module()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main()

        self.assertEqual(code, 0)
        line = stdout.getvalue().strip()
        payload = json.loads(line)
        self.assertTrue(payload["ok"])
        self.assertNotIn("Traceback", line)
        self.assertNotIn(module.SECRET_LIKE_PROVIDER_VALUE, line)
        self.assertNotIn(module.RAW_DECISION_CONTEXT, line)


if __name__ == "__main__":
    unittest.main()
