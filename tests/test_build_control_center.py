from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ade.mission_control import MissionControlSnapshot, MissionTelemetrySummary
from scripts.build_control_center import (
    _parse_project_spec,
    build_artifacts,
    main,
)


class BuildControlCenterTests(unittest.TestCase):
    def snapshot(self, project_id: str) -> MissionControlSnapshot:
        return MissionControlSnapshot(
            project_id=project_id,
            project_status="RUNNING",
            iteration=1,
            current_task_id="task-1",
            state_updated_at="2026-10-06T08:00:00+00:00",
            phase="control-center",
            milestone="live-aggregation",
            completed_tasks=1,
            failed_tasks=0,
            queue_depth=1,
            queue_exhausted=False,
            failure_ledger_count=0,
            checkpoint=None,
            open_decisions=(),
            telemetry=MissionTelemetrySummary(
                cycles_started=1,
                cycles_completed=1,
                repair_attempts=0,
                human_interrupts=0,
                quota_pauses=0,
            ),
            warnings=(),
            lifecycle_status="RUNNING",
            next_system_action="monitor-provider-session",
        )

    def test_parse_project_spec_requires_label_and_root(self) -> None:
        self.assertEqual(
            _parse_project_spec("J-Quants=/tmp/jq"),
            ("J-Quants", Path("/tmp/jq")),
        )
        for invalid in ("", "J-Quants", "=/tmp/jq", "J-Quants="):
            with self.assertRaises(ValueError):
                _parse_project_spec(invalid)

    def test_build_artifacts_writes_bounded_portfolio_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "dist"
            snapshots = {
                Path("/fake/jq"): self.snapshot("internal-jq"),
                Path("/fake/ck"): self.snapshot("internal-ck"),
            }

            with patch(
                "scripts.build_control_center.build_mission_control_snapshot",
                side_effect=lambda root: snapshots[Path(root)],
            ):
                html_path, snapshot_path = build_artifacts(
                    projects=(
                        ("J-Quants", "/fake/jq"),
                        ("Chu-kei Insight", "/fake/ck"),
                    ),
                    output_dir=output,
                )

            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")

            self.assertEqual(payload["project_count"], 2)
            self.assertEqual(
                {project["project_id"] for project in payload["projects"]},
                {"J-Quants", "Chu-kei Insight"},
            )
            self.assertIn("J-Quants", html)
            self.assertIn("Chu-kei Insight", html)
            serialized = json.dumps(payload).lower()
            self.assertNotIn("provider_session_id", serialized)
            self.assertNotIn("activity", serialized)
            self.assertNotIn("telemetry", serialized)

    def test_duplicate_project_labels_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_artifacts(
                projects=(("same", "/a"), ("same", "/b")),
                output_dir="/tmp/not-used",
            )

    def test_main_returns_failure_for_invalid_project_spec(self) -> None:
        self.assertEqual(main(["--project", "invalid"]), 1)

    def test_build_requires_at_least_one_project(self) -> None:
        with self.assertRaises(ValueError):
            build_artifacts(projects=(), output_dir="/tmp/not-used")


if __name__ == "__main__":
    unittest.main()
