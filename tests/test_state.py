from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade.models import ProjectState, ProjectStatus
from ade.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = StateStore(path)
            expected = ProjectState(
                schema_version=1,
                project_id="demo",
                status=ProjectStatus.READY,
                iteration=3,
            )

            store.save(expected)
            actual = store.load()

            self.assertEqual(actual, expected)
            self.assertTrue(path.exists())

    def test_non_object_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            store = StateStore(path)

            with self.assertRaisesRegex(ValueError, "JSON object"):
                store.load()


if __name__ == "__main__":
    unittest.main()
