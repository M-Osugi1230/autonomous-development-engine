from __future__ import annotations

import unittest

from ade.health import health_snapshot
from ade.models import ProjectState, ProjectStatus


class HealthTests(unittest.TestCase):
    def test_health_snapshot_basic_ready_state(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="proj-123",
            status=ProjectStatus.READY,
            iteration=2,
            current_task_id=None,
            completed_task_ids=["task-1", "task-2"],
            failed_task_ids=["task-0"],
        )

        snapshot = health_snapshot(state)

        self.assertEqual(
            snapshot,
            {
                "project_id": "proj-123",
                "status": "READY",
                "iteration": 2,
                "current_task_id": None,
                "completed_tasks": 2,
                "failed_tasks": 1,
            },
        )
        self.assertIsInstance(snapshot["status"], str)
        self.assertIsInstance(snapshot["completed_tasks"], int)
        self.assertIsInstance(snapshot["failed_tasks"], int)

    def test_health_snapshot_running_state(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="proj-456",
            status=ProjectStatus.RUNNING,
            iteration=5,
            current_task_id="task-3",
            completed_task_ids=["task-1", "task-2"],
            failed_task_ids=[],
        )

        snapshot = health_snapshot(state)

        self.assertEqual(
            snapshot,
            {
                "project_id": "proj-456",
                "status": "RUNNING",
                "iteration": 5,
                "current_task_id": "task-3",
                "completed_tasks": 2,
                "failed_tasks": 0,
            },
        )

    def test_health_snapshot_invalid_state_raises(self) -> None:
        state = ProjectState(
            schema_version=1,
            project_id="proj-789",
            status=ProjectStatus.RUNNING,
            current_task_id=None,  # Invalid: RUNNING requires current_task_id
        )

        with self.assertRaisesRegex(ValueError, "RUNNING state requires current_task_id"):
            health_snapshot(state)


if __name__ == "__main__":
    unittest.main()
