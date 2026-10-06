from __future__ import annotations

import unittest

from ade.control_center import (
    ControlCenterPortfolioSnapshot,
    ControlCenterProjectSummary,
)
from ade.mission_control import MissionControlSnapshot, MissionTelemetrySummary


class ControlCenterPortfolioTests(unittest.TestCase):
    def snapshot(
        self,
        project_id: str,
        *,
        lifecycle: str = "RUNNING",
        completed: int = 1,
        queue_depth: int = 1,
        current_task: str | None = "task-2",
        human_action: str | None = None,
        warnings: tuple[str, ...] = (),
        campaign: dict[str, object] | None = None,
    ) -> MissionControlSnapshot:
        return MissionControlSnapshot(
            project_id=project_id,
            project_status="RUNNING" if current_task else "READY",
            iteration=completed,
            current_task_id=current_task,
            state_updated_at="2026-10-06T08:00:00+00:00",
            phase="control-center-v0.2",
            milestone="portfolio",
            completed_tasks=completed,
            failed_tasks=0,
            queue_depth=queue_depth,
            queue_exhausted=queue_depth == 0 and current_task is None,
            failure_ledger_count=0,
            checkpoint=None,
            open_decisions=(),
            telemetry=MissionTelemetrySummary(
                cycles_started=completed,
                cycles_completed=completed,
                repair_attempts=0,
                human_interrupts=0,
                quota_pauses=0,
            ),
            warnings=warnings,
            campaign=campaign,
            lifecycle_status=lifecycle,
            next_system_action="continue trusted execution",
            next_required_human_action=human_action,
        )

    def test_project_summary_derives_safe_operational_fields(self) -> None:
        summary = ControlCenterProjectSummary.from_mission_control(
            self.snapshot("j-quants", warnings=("quota nearing limit",))
        )

        self.assertEqual(summary.project_id, "j-quants")
        self.assertEqual(summary.current_task_id, "task-2")
        self.assertEqual(summary.completed_tasks, 1)
        self.assertEqual(summary.total_tasks, 2)
        self.assertEqual(summary.progress_percent, 50)
        self.assertEqual(summary.warning_count, 1)
        self.assertFalse(summary.human_action_required)
        self.assertEqual(summary.next_system_action, "continue trusted execution")

    def test_campaign_progress_is_preferred_when_available(self) -> None:
        summary = ControlCenterProjectSummary.from_mission_control(
            self.snapshot(
                "chu-kei",
                completed=7,
                queue_depth=2,
                campaign={"completed_tasks": 3, "total_tasks": 5},
            )
        )

        self.assertEqual(summary.completed_tasks, 3)
        self.assertEqual(summary.total_tasks, 5)
        self.assertEqual(summary.progress_percent, 60)

    def test_human_action_projects_sort_before_running_projects(self) -> None:
        portfolio = ControlCenterPortfolioSnapshot.from_mission_control_snapshots(
            (
                self.snapshot("j-quants"),
                self.snapshot(
                    "jichi",
                    lifecycle="HUMAN_WAIT",
                    human_action="Approve production promotion",
                ),
                self.snapshot("chu-kei", lifecycle="RECOVERING"),
            )
        )

        self.assertEqual(
            [project.project_id for project in portfolio.projects],
            ["jichi", "chu-kei", "j-quants"],
        )
        self.assertEqual(portfolio.attention_required_count, 1)
        self.assertEqual(portfolio.active_count, 3)

    def test_duplicate_project_ids_fail_closed(self) -> None:
        summary = ControlCenterProjectSummary.from_mission_control(
            self.snapshot("duplicate")
        )
        with self.assertRaises(ValueError):
            ControlCenterPortfolioSnapshot(projects=(summary, summary))

    def test_serialization_contains_summary_only(self) -> None:
        portfolio = ControlCenterPortfolioSnapshot.from_mission_control_snapshots(
            (self.snapshot("j-quants"),)
        )
        payload = portfolio.to_dict()

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["project_count"], 1)
        self.assertEqual(payload["projects"][0]["project_id"], "j-quants")
        self.assertNotIn("telemetry", payload["projects"][0])
        self.assertNotIn("activity", payload["projects"][0])
        self.assertNotIn("preview", payload["projects"][0])

    def test_renderer_input_type_is_separate_from_model(self) -> None:
        with self.assertRaises(ValueError):
            ControlCenterProjectSummary.from_mission_control(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
