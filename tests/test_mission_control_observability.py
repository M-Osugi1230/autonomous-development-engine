from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    ActivityEvent,
    ActivityKind,
    ActivityStore,
    DecisionStore,
    MissionActivitySummary,
    MissionControlSnapshot,
    MissionPreviewSummary,
    MissionTelemetrySummary,
    PreviewKind,
    PreviewManifest,
    PreviewStore,
    build_mission_control_snapshot,
    render_mission_control,
)


class MissionControlObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "repo"
        self.autodev = self.root / ".autodev"
        self.autodev.mkdir(parents=True)
        self._write_base()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: object) -> None:
        path = self.autodev / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_base(self) -> None:
        self.write_json(
            "state.json",
            {
                "schema_version": 1,
                "project_id": "ade-observability",
                "status": "READY",
                "iteration": 2,
                "current_task_id": None,
                "completed_task_ids": ["task-1", "task-2"],
                "failed_task_ids": [],
                "provider": "jules",
                "updated_at": "2026-09-26T01:40:00+00:00",
                "metadata": {
                    "phase": "phase8-mission-control",
                    "milestone": "activity-preview",
                    "queue_exhausted": True,
                },
            },
        )
        self.write_json("task-queue.json", {"schema_version": 1, "tasks": []})
        self.write_json("failures.json", {"schema_version": 1, "failures": []})
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": 2,
                "cycles_completed": 2,
                "repair_attempts": 0,
                "human_interrupts": 0,
                "quota_pauses": 0,
            },
        )
        DecisionStore(self.autodev / "decisions.json").save([])

    def test_snapshot_loads_recent_activity_and_preview(self) -> None:
        activity = ActivityStore(self.autodev / "activity.json")
        activity.save(
            [
                ActivityEvent(
                    event_id="evt-1",
                    kind=ActivityKind.TASK_STARTED,
                    occurred_at="2026-09-26T01:38:00+00:00",
                    summary="Started task 2",
                    task_id="task-2",
                ),
                ActivityEvent(
                    event_id="evt-2",
                    kind=ActivityKind.TASK_COMPLETED,
                    occurred_at="2026-09-26T01:39:00+00:00",
                    summary="Completed task 2",
                    task_id="task-2",
                ),
            ]
        )
        PreviewStore(self.autodev / "preview.json").save(
            PreviewManifest(
                preview_id="preview-pr-34",
                kind=PreviewKind.PULL_REQUEST,
                title="Review PR #34",
                url="https://github.com/M-Osugi1230/autonomous-development-engine/pull/34",
                task_id="task-2",
                updated_at="2026-09-26T01:39:30+00:00",
            )
        )

        snapshot = build_mission_control_snapshot(self.root)

        self.assertEqual(
            [event.event_id for event in snapshot.activity],
            ["evt-2", "evt-1"],
        )
        self.assertIsNotNone(snapshot.preview)
        assert snapshot.preview is not None
        self.assertEqual(snapshot.preview.preview_id, "preview-pr-34")
        self.assertEqual(snapshot.preview.kind, "PULL_REQUEST")
        serialized = snapshot.to_dict()
        self.assertEqual(serialized["activity"][0]["event_id"], "evt-2")
        self.assertEqual(serialized["preview"]["task_id"], "task-2")

    def test_renderer_exposes_only_validated_github_preview_link_and_activity(self) -> None:
        snapshot = MissionControlSnapshot(
            project_id="ade-observability",
            project_status="READY",
            iteration=2,
            current_task_id=None,
            state_updated_at="2026-09-26T01:40:00+00:00",
            phase="phase8-mission-control",
            milestone="activity-preview",
            completed_tasks=2,
            failed_tasks=0,
            queue_depth=0,
            queue_exhausted=True,
            failure_ledger_count=0,
            checkpoint=None,
            open_decisions=(),
            telemetry=MissionTelemetrySummary(
                cycles_started=2,
                cycles_completed=2,
                repair_attempts=0,
                human_interrupts=0,
                quota_pauses=0,
            ),
            warnings=(),
            activity=(
                MissionActivitySummary(
                    event_id="evt-2",
                    kind="TASK_COMPLETED",
                    occurred_at="2026-09-26T01:39:00+00:00",
                    summary="Completed task 2",
                    task_id="task-2",
                ),
            ),
            preview=MissionPreviewSummary(
                preview_id="preview-pr-34",
                kind="PULL_REQUEST",
                title="Review PR #34",
                url="https://github.com/M-Osugi1230/autonomous-development-engine/pull/34",
                task_id="task-2",
                updated_at="2026-09-26T01:39:30+00:00",
            ),
        )

        html = render_mission_control(snapshot)
        lowered = html.lower()

        self.assertIn("Latest output", html)
        self.assertIn("Activity", html)
        self.assertIn("Completed task 2", html)
        self.assertIn(
            'href="https://github.com/M-Osugi1230/autonomous-development-engine/pull/34"',
            html,
        )
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("javascript:", lowered)
        self.assertNotIn("<link", lowered)
        self.assertNotIn(" src=", lowered)
        self.assertNotIn("@import", lowered)

    def test_direct_preview_summary_rejects_untrusted_url(self) -> None:
        with self.assertRaises(ValueError):
            MissionPreviewSummary(
                preview_id="preview-bad",
                kind="BUILD",
                title="Bad preview",
                url="https://example.com/build/1",
                task_id="task-2",
                updated_at="2026-09-26T01:39:30+00:00",
            )


if __name__ == "__main__":
    unittest.main()
