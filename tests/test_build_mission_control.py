from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from ade import (
    CheckpointState,
    CheckpointStore,
    DecisionPriority,
    DecisionRecord,
    DecisionRequest,
    DecisionStore,
    TaskCheckpoint,
)


def load_build_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_mission_control.py"
    spec = importlib.util.spec_from_file_location("build_mission_control_test_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load build_mission_control.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MissionControlBuildCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "repo"
        self.autodev = self.root / ".autodev"
        (self.autodev / "runtime").mkdir(parents=True)
        self.output = Path(self.temp_dir.name) / "artifact" / "mission-control"
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: object) -> None:
        path = self.autodev / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_fixture(self) -> None:
        self.write_json(
            "state.json",
            {
                "schema_version": 1,
                "project_id": "mission-control-test",
                "status": "READY",
                "iteration": 2,
                "current_task_id": "task-2",
                "completed_task_ids": ["task-1"],
                "failed_task_ids": [],
                "provider": "jules",
                "updated_at": "2026-09-26T01:00:00+00:00",
                "metadata": {
                    "phase": "phase8-mission-control",
                    "milestone": "build-cli",
                    "queue_exhausted": False,
                },
            },
        )
        self.write_json(
            "task-queue.json",
            {
                "schema_version": 1,
                "tasks": [{"task_id": "task-3"}],
            },
        )
        self.write_json(
            "failures.json",
            {"schema_version": 1, "failures": []},
        )
        self.write_json(
            "metrics.json",
            {
                "schema_version": 1,
                "cycles_started": 0,
                "cycles_completed": 0,
                "repair_attempts": 0,
                "human_interrupts": 0,
                "quota_pauses": 0,
            },
        )

        CheckpointStore(self.autodev / "runtime" / "checkpoint.json").save(
            TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.COMPLETED,
                attempt=0,
                replan_count=0,
                provider_session_id="provider-session-must-not-leak",
            )
        )
        DecisionStore(self.autodev / "decisions.json").save(
            [
                DecisionRecord(
                    request=DecisionRequest(
                        decision_id="decision-1",
                        question="Approve the irreversible migration?",
                        options=("approve", "reject"),
                        priority=DecisionPriority.P0,
                        blocking_task_id="task-2",
                        context={"private": "raw-context-must-not-leak"},
                    )
                )
            ]
        )

    def test_build_writes_safe_html_and_snapshot(self) -> None:
        module = load_build_module()

        html_path, snapshot_path = module.build_artifacts(
            repo_root=self.root,
            output_dir=self.output,
        )

        self.assertEqual(html_path, self.output / "index.html")
        self.assertEqual(snapshot_path, self.output / "snapshot.json")
        self.assertTrue(html_path.exists())
        self.assertTrue(snapshot_path.exists())

        html = html_path.read_text(encoding="utf-8")
        snapshot_text = snapshot_path.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)

        self.assertTrue(snapshot_text.endswith("\n"))
        self.assertEqual(snapshot["project_id"], "mission-control-test")
        self.assertEqual(snapshot["queue_depth"], 1)
        self.assertEqual(snapshot["open_decisions"][0]["decision_id"], "decision-1")
        self.assertIn("Approve the irreversible migration?", html)

        combined = html + snapshot_text
        self.assertNotIn("raw-context-must-not-leak", combined)
        self.assertNotIn("provider-session-must-not-leak", combined)
        self.assertIn("telemetry metrics lag project iteration", combined)

    def test_repeated_build_is_deterministic(self) -> None:
        module = load_build_module()
        html_path, snapshot_path = module.build_artifacts(
            repo_root=self.root,
            output_dir=self.output,
        )
        first_html = html_path.read_bytes()
        first_snapshot = snapshot_path.read_bytes()

        html_path.write_text("stale-html", encoding="utf-8")
        snapshot_path.write_text("stale-json", encoding="utf-8")

        module.build_artifacts(
            repo_root=self.root,
            output_dir=self.output,
        )

        self.assertEqual(html_path.read_bytes(), first_html)
        self.assertEqual(snapshot_path.read_bytes(), first_snapshot)
        self.assertEqual(list(self.output.glob(".*.tmp")), [])

    def test_main_accepts_custom_paths_and_returns_zero(self) -> None:
        module = load_build_module()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(
                [
                    "--root",
                    str(self.root),
                    "--output-dir",
                    str(self.output),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("Mission Control HTML:", stdout.getvalue())
        self.assertTrue((self.output / "index.html").exists())

    def test_failure_is_concise_without_traceback(self) -> None:
        module = load_build_module()
        missing_root = Path(self.temp_dir.name) / "missing"
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            code = module.main(
                [
                    "--root",
                    str(missing_root),
                    "--output-dir",
                    str(self.output),
                ]
            )

        self.assertEqual(code, 1)
        message = stderr.getvalue()
        self.assertIn("Mission Control build failed:", message)
        self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
