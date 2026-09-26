from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_cycle_module():
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        path = TRUSTED_DIR / "jules_cycle.py"
        spec = importlib.util.spec_from_file_location("trusted_jules_cycle_state_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load trusted jules_cycle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class FakeGitHub:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.put_calls = []

    def get_json_file(self, path, *, ref="main"):
        return copy.deepcopy(self.state), "state-sha"

    def put_json_file(self, path, payload, *, sha, message, branch="main"):
        self.put_calls.append(
            {
                "path": path,
                "payload": copy.deepcopy(payload),
                "sha": sha,
                "message": message,
                "branch": branch,
            }
        )
        self.state = copy.deepcopy(payload)


class TrustedProjectStateSyncTests(unittest.TestCase):
    def test_running_clears_pause_metadata(self) -> None:
        module = load_cycle_module()
        gh = FakeGitHub(
            {
                "schema_version": 1,
                "project_id": "ade",
                "status": "PAUSED_QUOTA",
                "current_task_id": "task-1",
                "metadata": {
                    "phase": "phase7-human-decision",
                    "pause_reason": "jules-rolling-quota",
                    "resume_after": "2026-09-27T00:00:00+00:00",
                },
            }
        )

        module._set_project_status(
            gh,
            task_id="task-1",
            status="RUNNING",
            clear_pause_metadata=True,
        )

        self.assertEqual(gh.state["status"], "RUNNING")
        self.assertNotIn("pause_reason", gh.state["metadata"])
        self.assertNotIn("resume_after", gh.state["metadata"])
        self.assertEqual(len(gh.put_calls), 1)

    def test_pause_metadata_is_persisted(self) -> None:
        module = load_cycle_module()
        gh = FakeGitHub(
            {
                "schema_version": 1,
                "project_id": "ade",
                "status": "RUNNING",
                "current_task_id": "task-1",
                "metadata": {"phase": "phase7-human-decision"},
            }
        )

        module._set_project_status(
            gh,
            task_id="task-1",
            status="PAUSED_QUOTA",
            metadata_updates={
                "pause_reason": "jules-rolling-quota",
                "resume_after": "2026-09-27T00:00:00+00:00",
            },
        )

        self.assertEqual(gh.state["status"], "PAUSED_QUOTA")
        self.assertEqual(gh.state["metadata"]["pause_reason"], "jules-rolling-quota")
        self.assertEqual(
            gh.state["metadata"]["resume_after"],
            "2026-09-27T00:00:00+00:00",
        )

    def test_task_mismatch_is_rejected_without_write(self) -> None:
        module = load_cycle_module()
        gh = FakeGitHub(
            {
                "schema_version": 1,
                "project_id": "ade",
                "status": "READY",
                "current_task_id": "task-other",
                "metadata": {},
            }
        )

        with self.assertRaises(RuntimeError):
            module._set_project_status(
                gh,
                task_id="task-1",
                status="RUNNING",
            )

        self.assertEqual(gh.put_calls, [])


if __name__ == "__main__":
    unittest.main()
