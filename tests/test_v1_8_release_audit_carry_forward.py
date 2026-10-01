from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_audit_module():
    path = ROOT / "scripts" / "v1_8_release_audit.py"
    spec = importlib.util.spec_from_file_location(
        "v1_8_release_audit_carry_forward_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.8 release audit")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V18ReleaseAuditCarryForwardTests(unittest.TestCase):
    def test_later_phase_state_does_not_invalidate_v18_graduation(self) -> None:
        module = load_audit_module()
        state = json.loads(
            (ROOT / ".autodev" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        state["status"] = "RUNNING"
        state["current_task_id"] = "v19-improvement-001"
        state["failed_task_ids"] = ["v19-prior-attempt"]
        state["metadata"]["phase"] = "v1.9-continuous-improvement"
        state["metadata"]["milestone"] = "v1.9-slice-999"
        state["metadata"]["next_system_action"] = (
            "continue-v1.9-work"
        )
        state["metadata"]["next_required_human_action"] = (
            "review-v1.9-only"
        )
        state["metadata"]["queue_exhausted"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            original = module.PROJECT_STATE_PATH
            module.PROJECT_STATE_PATH = path
            try:
                result = module.audit()
            finally:
                module.PROJECT_STATE_PATH = original

        self.assertTrue(result["graduated"])
        self.assertEqual(result["version"], "v1.8")
        self.assertEqual(
            result["proof_id"],
            "v1.8-autonomous-release-proof-001",
        )


if __name__ == "__main__":
    unittest.main()
