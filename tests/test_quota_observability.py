from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_cycle_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "jules_cycle.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_jules_cycle_quota_observability_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load jules_cycle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    def __init__(self) -> None:
        self.state = {
            "schema_version": 1,
            "project_id": "ade-test",
            "status": "READY",
            "iteration": 1,
            "current_task_id": "task-1",
            "completed_task_ids": [],
            "failed_task_ids": [],
            "provider": "jules",
            "updated_at": None,
            "metadata": {
                "next_system_action": "zero-touch-start",
                "next_required_human_action": None,
            },
        }
        self.upserts: list[tuple[str, dict]] = []
        self.puts: list[tuple[str, dict]] = []

    def upsert_json_file(self, path: str, payload: dict, *, message: str, branch: str = "main") -> None:
        self.upserts.append((path, dict(payload)))

    def get_json_file(self, path: str, *, ref: str = "main"):
        if path != ".autodev/state.json":
            raise AssertionError(f"unexpected read: {path}")
        return dict(self.state), "a" * 40

    def put_json_file(
        self,
        path: str,
        payload: dict,
        *,
        sha: str | None,
        message: str,
        branch: str = "main",
    ) -> None:
        if path != ".autodev/state.json":
            raise AssertionError(f"unexpected write: {path}")
        self.state = dict(payload)
        self.puts.append((path, dict(payload)))


class QuotaObservabilityTests(unittest.TestCase):
    def test_quota_pause_records_cloud_resume_as_next_system_action(self) -> None:
        module = load_cycle_module()
        fake = FakeGitHub()
        captured: list[dict] = []
        module._write_result = lambda payload: captured.append(dict(payload))
        resume_at = datetime(2026, 9, 30, 6, 56, 17, tzinfo=UTC)

        result = module._quota_pause(
            fake,
            task_id="task-1",
            session_id=None,
            exc=RuntimeError("quota reached"),
            resume_at=resume_at,
        )

        self.assertEqual(result, 20)
        self.assertEqual(fake.state["status"], "PAUSED_QUOTA")
        metadata = fake.state["metadata"]
        self.assertEqual(metadata["pause_reason"], "jules-rolling-quota")
        self.assertEqual(metadata["resume_after"], resume_at.isoformat())
        self.assertEqual(
            metadata["next_system_action"],
            "resume-after-provider-quota",
        )
        self.assertIsNone(metadata["next_required_human_action"])
        self.assertEqual(fake.upserts[0][0], ".autodev/runtime/checkpoint.json")
        self.assertEqual(fake.upserts[0][1]["state"], "PAUSED_QUOTA")
        self.assertEqual(captured[0]["state"], "PAUSED_QUOTA")


if __name__ == "__main__":
    unittest.main()
