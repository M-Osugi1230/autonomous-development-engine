from __future__ import annotations

import unittest

from ade.models import ProjectState, ProjectStatus


class ProjectStateTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="demo",
            status=ProjectStatus.READY,
            iteration=2,
            completed_task_ids=["t1"],
            metadata={"phase": "phase0"},
        )
        restored = ProjectState.from_dict(state.to_dict())
        self.assertEqual(restored, state)

    def test_running_requires_current_task(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="demo",
            status=ProjectStatus.RUNNING,
        )
        with self.assertRaisesRegex(ValueError, "current_task_id"):
            state.validate()

    def test_completed_and_failed_overlap_is_rejected(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="demo",
            status=ProjectStatus.READY,
            completed_task_ids=["t1"],
            failed_task_ids=["t1"],
        )
        with self.assertRaisesRegex(ValueError, "both completed and failed"):
            state.validate()


if __name__ == "__main__":
    unittest.main()
