from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    ActivityStore,
    DecisionStore,
    ImprovementCycleViewState,
    ImprovementObservabilitySnapshot,
    build_mission_control_snapshot,
    render_mission_control,
)


SOURCE_SHA = "a" * 40


class MissionControlImprovementObservabilityTests(unittest.TestCase):
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
                "project_id": "ade-v19-observability",
                "status": "READY",
                "iteration": 9,
                "current_task_id": None,
                "completed_task_ids": ["task-final"],
                "failed_task_ids": [],
                "provider": "jules",
                "updated_at": "2026-10-02T11:00:00+00:00",
                "metadata": {
                    "phase": "v1.9-continuous-improvement",
                    "milestone": "v1.9-slice-007",
                    "queue_exhausted": True,
                },
            },
        )
        self.write_json(
            "task-queue.json",
            {"schema_version": 1, "tasks": []},
        )
        self.write_json(
            "failures.json",
            {"schema_version": 1, "failures": []},
        )
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": 9,
                "cycles_completed": 9,
                "repair_attempts": 1,
                "human_interrupts": 0,
                "quota_pauses": 0,
            },
        )
        DecisionStore(self.autodev / "decisions.json").save([])
        ActivityStore(self.autodev / "activity.json").save([])

    def improvement_snapshot(self) -> ImprovementObservabilitySnapshot:
        return ImprovementObservabilitySnapshot(
            release_candidate_id="release-observability-v19-001",
            repository="M-Osugi1230/one-minute-thought-experiments",
            source_sha=SOURCE_SHA,
            release_environment="preview",
            signal_count=3,
            observation_only_count=1,
            current_count=1,
            cooldown_count=1,
            superseded_count=0,
            conflicted_count=0,
            cycle_limit_count=0,
            retired_count=0,
            current_signal_id="improve-current-v19",
            current_signal_kind="RUNTIME_GAP",
            cycle_state=ImprovementCycleViewState.HANDED_OFF,
            cycle_index=1,
            handoff_count=1,
            lineage_retirement_count=0,
            latest_retirement_id=None,
        )

    def test_snapshot_loads_safe_improvement_projection(self) -> None:
        self.write_json(
            "improvement/mission-control.json",
            self.improvement_snapshot().canonical_dict(),
        )
        snapshot = build_mission_control_snapshot(self.root)
        self.assertIsNotNone(snapshot.improvement)
        assert snapshot.improvement is not None
        self.assertEqual(
            snapshot.improvement.release_candidate_id,
            "release-observability-v19-001",
        )
        self.assertEqual(snapshot.improvement.signal_count, 3)
        self.assertEqual(snapshot.improvement.current_count, 1)
        self.assertEqual(snapshot.improvement.cooldown_count, 1)
        self.assertEqual(
            snapshot.improvement.current_signal_kind,
            "RUNTIME_GAP",
        )
        self.assertEqual(
            snapshot.improvement.cycle_state,
            "HANDED_OFF",
        )

        payload = snapshot.to_dict()
        improvement = payload["improvement"]
        assert isinstance(improvement, dict)
        serialized = json.dumps(improvement, sort_keys=True)
        for forbidden in (
            "statement",
            "evidence_refs",
            "evidence_paths",
            "detail_fingerprint",
            "provider_session_id",
            "registry_fingerprint",
            "decision_context",
            "raw_telemetry",
            "github_pat_",
            "ghp_",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_html_renders_safe_improvement_card(self) -> None:
        self.write_json(
            "improvement/mission-control.json",
            self.improvement_snapshot().canonical_dict(),
        )
        html = render_mission_control(
            build_mission_control_snapshot(self.root)
        )
        self.assertIn("Continuous Improvement", html)
        self.assertIn("release-observability-v19-001", html)
        self.assertIn("RUNTIME_GAP", html)
        self.assertIn("HANDED_OFF", html)
        self.assertIn("improve-current-v19", html)
        self.assertNotIn("evidence_refs", html)
        self.assertNotIn("provider_session_id", html)
        self.assertNotIn("raw_telemetry", html)
        self.assertNotIn("ghp_", html)

    def test_malformed_improvement_projection_fails_closed(self) -> None:
        payload = self.improvement_snapshot().canonical_dict()
        payload["raw_telemetry"] = "provider-private-output"
        self.write_json(
            "improvement/mission-control.json",
            payload,
        )
        with self.assertRaisesRegex(
            ValueError,
            "unknown improvement observability fields",
        ):
            build_mission_control_snapshot(self.root)

    def test_absent_projection_preserves_legacy_snapshot(self) -> None:
        snapshot = build_mission_control_snapshot(self.root)
        self.assertIsNone(snapshot.improvement)
        html = render_mission_control(snapshot)
        self.assertIn(
            "No Continuous Improvement state.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
