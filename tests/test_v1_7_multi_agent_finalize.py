from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "v1_7_multi_agent_finalize.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_7_multi_agent_finalize_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.7 Multi-Agent finalizer module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V17MultiAgentFinalizeTests(unittest.TestCase):
    def test_scheduled_target_gate_can_bind_post_review_merge(self) -> None:
        module = load_module()
        runs = [
            {
                "id": 401,
                "name": "ADE Remote PR Gate",
                "event": "workflow_run",
                "conclusion": "success",
                "created_at": "2026-10-01T00:24:44Z",
            },
            {
                "id": 402,
                "name": "ADE Remote PR Gate",
                "event": "schedule",
                "conclusion": "success",
                "created_at": "2026-10-01T00:39:08Z",
            },
        ]
        selected = module._select_target_gate_run(
            runs,
            ci_updated_at="2026-10-01T00:24:42Z",
            merged_at="2026-10-01T00:39:10Z",
        )
        self.assertEqual(selected["id"], 402)
        self.assertEqual(selected["event"], "schedule")

    def test_manual_target_gate_is_not_graduation_provenance(self) -> None:
        module = load_module()
        runs = [
            {
                "id": 501,
                "name": "ADE Remote PR Gate",
                "event": "workflow_dispatch",
                "conclusion": "success",
                "created_at": "2026-10-01T00:39:08Z",
            }
        ]
        with self.assertRaises(ValueError):
            module._select_target_gate_run(
                runs,
                ci_updated_at="2026-10-01T00:24:42Z",
                merged_at="2026-10-01T00:39:10Z",
            )

    def test_failed_or_unrelated_gate_is_rejected(self) -> None:
        module = load_module()
        runs = [
            {
                "id": 601,
                "name": "ADE Remote PR Gate",
                "event": "schedule",
                "conclusion": "failure",
                "created_at": "2026-10-01T00:39:08Z",
            },
            {
                "id": 602,
                "name": "Other Workflow",
                "event": "schedule",
                "conclusion": "success",
                "created_at": "2026-10-01T00:39:09Z",
            },
        ]
        with self.assertRaises(ValueError):
            module._select_target_gate_run(
                runs,
                ci_updated_at="2026-10-01T00:24:42Z",
                merged_at="2026-10-01T00:39:10Z",
            )


if __name__ == "__main__":
    unittest.main()
