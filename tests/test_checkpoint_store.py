from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ade.checkpoint import CheckpointState, TaskCheckpoint
from ade.checkpoint_store import CheckpointStore
from ade.repair import FailureKind


class CheckpointStoreTests(unittest.TestCase):
    def test_default_path(self) -> None:
        store = CheckpointStore()
        self.assertEqual(store.path, Path(".autodev/runtime/checkpoint.json"))

    def test_custom_path_injected(self) -> None:
        custom_path = Path("/tmp/custom_checkpoint.json")
        store = CheckpointStore(custom_path)
        self.assertEqual(store.path, custom_path)

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "checkpoint.json"
            store = CheckpointStore(checkpoint_path)

            chk = TaskCheckpoint(
                task_id="task-123",
                state=CheckpointState.PAUSED_QUOTA,
                attempt=2,
                replan_count=1,
                provider_session_id="sess-abc",
                last_failure_kind=FailureKind.PROVIDER_QUOTA,
                last_error="Rate limit exceeded",
                resume_after="2026-03-31T12:00:00Z",
            )

            store.save(chk)
            loaded = store.load()

            self.assertEqual(loaded, chk)
            self.assertEqual(loaded.task_id, "task-123")
            self.assertEqual(loaded.state, CheckpointState.PAUSED_QUOTA)
            self.assertEqual(loaded.attempt, 2)
            self.assertEqual(loaded.replan_count, 1)
            self.assertEqual(loaded.provider_session_id, "sess-abc")
            self.assertEqual(loaded.last_failure_kind, FailureKind.PROVIDER_QUOTA)
            self.assertEqual(loaded.last_error, "Rate limit exceeded")
            self.assertEqual(loaded.resume_after, "2026-03-31T12:00:00Z")

    def test_save_parent_directory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = Path(temp_dir) / "nested" / "sub" / "checkpoint.json"
            self.assertFalse(nested_path.parent.exists())

            store = CheckpointStore(nested_path)
            chk = TaskCheckpoint(
                task_id="task-parent-dir",
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=0,
            )

            store.save(chk)
            self.assertTrue(nested_path.exists())
            self.assertEqual(store.load(), chk)

    def test_save_format_deterministic_pretty_json_with_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "checkpoint.json"
            store = CheckpointStore(checkpoint_path)
            chk = TaskCheckpoint(
                task_id="task-format",
                state=CheckpointState.COMPLETED,
                attempt=1,
                replan_count=0,
            )

            store.save(chk)

            raw_text = checkpoint_path.read_text(encoding="utf-8")
            self.assertTrue(raw_text.endswith("\n"))

            parsed = json.loads(raw_text)
            expected_dict = chk.to_dict()
            self.assertEqual(parsed, expected_dict)

            expected_formatted = json.dumps(expected_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            self.assertEqual(raw_text, expected_formatted)

    def test_replacement_of_existing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "checkpoint.json"
            store = CheckpointStore(checkpoint_path)

            chk1 = TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.RUNNING,
                attempt=1,
                replan_count=0,
            )
            chk2 = TaskCheckpoint(
                task_id="task-1",
                state=CheckpointState.COMPLETED,
                attempt=1,
                replan_count=0,
            )

            store.save(chk1)
            self.assertEqual(store.load(), chk1)

            store.save(chk2)
            self.assertEqual(store.load(), chk2)

    def test_load_missing_file_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "nonexistent.json"
            store = CheckpointStore(checkpoint_path)

            with self.assertRaises(FileNotFoundError):
                store.load()

    def test_load_invalid_json_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "bad.json"
            checkpoint_path.write_text("invalid json {", encoding="utf-8")
            store = CheckpointStore(checkpoint_path)

            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                store.load()

    def test_load_non_object_json_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "array.json"
            checkpoint_path.write_text("[1, 2, 3]", encoding="utf-8")
            store = CheckpointStore(checkpoint_path)

            with self.assertRaisesRegex(ValueError, "JSON object"):
                store.load()

    def test_load_invalid_checkpoint_payload_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "invalid_payload.json"
            # Missing state field
            checkpoint_path.write_text(json.dumps({"task_id": "t1", "attempt": 0}), encoding="utf-8")
            store = CheckpointStore(checkpoint_path)

            with self.assertRaisesRegex(ValueError, "invalid task checkpoint payload"):
                store.load()

    def test_save_type_validation(self) -> None:
        store = CheckpointStore()
        with self.assertRaises(TypeError):
            store.save({"not": "a TaskCheckpoint"})  # type: ignore[arg-type]

    def test_temp_file_cleanup_on_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent_dir = Path(temp_dir) / "runtime"
            checkpoint_path = parent_dir / "checkpoint.json"
            store = CheckpointStore(checkpoint_path)

            chk = TaskCheckpoint(
                task_id="task-cleanup",
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=0,
            )

            # Simulate failure during os.replace
            with patch("os.replace", side_effect=RuntimeError("Simulated write failure")):
                with self.assertRaises(RuntimeError):
                    store.save(chk)

            # Check that no temporary files remain in parent_dir
            temp_files = list(parent_dir.glob(".*.tmp"))
            self.assertEqual(temp_files, [])


if __name__ == "__main__":
    unittest.main()
