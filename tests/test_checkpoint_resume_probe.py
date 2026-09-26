from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_probe_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "checkpoint_resume_probe.py"
    spec = importlib.util.spec_from_file_location("checkpoint_resume_probe_test_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load checkpoint_resume_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CheckpointResumeProbeTests(unittest.TestCase):
    def test_crash_restart_reuses_same_provider_session(self) -> None:
        module = load_probe_module()
        result = module.run_probe()

        self.assertTrue(result["ok"])
        self.assertEqual(result["create_session_calls"], 1)
        self.assertEqual(result["get_session_calls"], 1)
        self.assertEqual(result["intermediate_state"], "RUNNING")
        self.assertEqual(result["final_state"], "COMPLETED")
        self.assertEqual(result["session_id"], "probe-session-1")

    def test_main_emits_success_and_returns_zero(self) -> None:
        module = load_probe_module()
        self.assertEqual(module.main(), 0)


if __name__ == "__main__":
    unittest.main()
