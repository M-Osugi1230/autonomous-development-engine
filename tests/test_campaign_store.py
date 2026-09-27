from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ade.campaign import AutonomousCampaign, CampaignStatus
from ade.campaign_store import CampaignStore, DEFAULT_CAMPAIGN_PATH


class CampaignStoreTests(unittest.TestCase):
    def test_default_path(self) -> None:
        store = CampaignStore()
        self.assertEqual(store.path, DEFAULT_CAMPAIGN_PATH)
        self.assertEqual(store.path, Path(".autodev/campaign.json"))

    def test_custom_path_injected(self) -> None:
        custom_path = Path("/tmp/custom_campaign.json")
        store = CampaignStore(custom_path)
        self.assertEqual(store.path, custom_path)

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            store = CampaignStore(path)

            campaign = AutonomousCampaign(
                campaign_id="camp-101",
                goal="Refactor authentication pipeline",
                task_ids=("task-1", "task-2", "task-3"),
                status=CampaignStatus.RUNNING,
                completed_task_ids=("task-1",),
            )

            store.save(campaign)
            loaded = store.load()

            self.assertEqual(loaded, campaign)
            self.assertEqual(loaded.campaign_id, "camp-101")
            self.assertEqual(loaded.goal, "Refactor authentication pipeline")
            self.assertEqual(loaded.task_ids, ("task-1", "task-2", "task-3"))
            self.assertEqual(loaded.status, CampaignStatus.RUNNING)
            self.assertEqual(loaded.completed_task_ids, ("task-1",))
            self.assertEqual(loaded.progress, (1, 3))

    def test_save_parent_directory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = Path(temp_dir) / "sub" / "dir" / "campaign.json"
            self.assertFalse(nested_path.parent.exists())

            store = CampaignStore(nested_path)
            campaign = AutonomousCampaign(
                campaign_id="camp-dir",
                goal="Create directories",
                task_ids=("t1",),
            )

            store.save(campaign)
            self.assertTrue(nested_path.exists())
            self.assertEqual(store.load(), campaign)

    def test_save_format_deterministic_pretty_json_with_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            store = CampaignStore(path)
            campaign = AutonomousCampaign(
                campaign_id="camp-fmt",
                goal="Pretty format",
                task_ids=("t1", "t2"),
                status=CampaignStatus.COMPLETED,
                completed_task_ids=("t1", "t2"),
            )

            store.save(campaign)

            raw_text = path.read_text(encoding="utf-8")
            self.assertTrue(raw_text.endswith("\n"))

            parsed = json.loads(raw_text)
            expected_dict = campaign.to_dict()
            self.assertEqual(parsed, expected_dict)

            expected_formatted = (
                json.dumps(expected_dict, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n"
            )
            self.assertEqual(raw_text, expected_formatted)

    def test_replacement_of_existing_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            store = CampaignStore(path)

            c1 = AutonomousCampaign(
                campaign_id="c1",
                goal="Initial goal",
                task_ids=("t1", "t2"),
                status=CampaignStatus.RUNNING,
                completed_task_ids=(),
            )
            c2 = AutonomousCampaign(
                campaign_id="c1",
                goal="Initial goal",
                task_ids=("t1", "t2"),
                status=CampaignStatus.COMPLETED,
                completed_task_ids=("t1", "t2"),
            )

            store.save(c1)
            self.assertEqual(store.load(), c1)

            store.save(c2)
            self.assertEqual(store.load(), c2)

    def test_load_missing_file_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nonexistent.json"
            store = CampaignStore(path)

            with self.assertRaises(FileNotFoundError):
                store.load()

    def test_load_invalid_json_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{ incomplete json ...", encoding="utf-8")
            store = CampaignStore(path)

            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                store.load()

    def test_load_non_object_json_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.json"
            path.write_text('["camp-1"]', encoding="utf-8")
            store = CampaignStore(path)

            with self.assertRaisesRegex(ValueError, "JSON object"):
                store.load()

    def test_load_invalid_campaign_payload_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid_payload.json"

            # Test invalid schema version
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 99,
                        "campaign_id": "c1",
                        "goal": "g",
                        "task_ids": ["t1"],
                    }
                ),
                encoding="utf-8",
            )
            store = CampaignStore(path)
            with self.assertRaisesRegex(ValueError, "invalid campaign payload"):
                store.load()

            # Test invalid completed task ID not in task_ids
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "c1",
                        "goal": "g",
                        "task_ids": ["t1"],
                        "completed_task_ids": ["t99"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid campaign payload"):
                store.load()

    def test_save_type_validation(self) -> None:
        store = CampaignStore()
        with self.assertRaises(TypeError):
            store.save({"not": "a campaign"})  # type: ignore[arg-type]

    def test_atomic_replacement_and_cleanup_on_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent_dir = Path(temp_dir) / "store"
            path = parent_dir / "campaign.json"
            store = CampaignStore(path)

            campaign = AutonomousCampaign(
                campaign_id="c-atomic",
                goal="Atomic update",
                task_ids=("t1",),
            )

            # Save once successfully
            store.save(campaign)

            # Simulate failure during os.replace
            with patch(
                "os.replace", side_effect=RuntimeError("Simulated write failure")
            ):
                with self.assertRaises(RuntimeError):
                    store.save(campaign)

            # Check that original file content remains untouched
            self.assertEqual(store.load(), campaign)

            # Check that no temporary files remain in parent_dir
            temp_files = list(parent_dir.glob(".*.tmp"))
            self.assertEqual(temp_files, [])

    def test_no_caller_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            store = CampaignStore(path)

            payload = {
                "schema_version": 1,
                "campaign_id": "c-mutation",
                "goal": "Mutation test",
                "task_ids": ["t1", "t2"],
                "status": "RUNNING",
                "completed_task_ids": ["t1"],
            }
            payload_copy = json.loads(json.dumps(payload))

            campaign = AutonomousCampaign.from_dict(payload)
            self.assertEqual(payload, payload_copy)  # from_dict did not mutate input payload

            store.save(campaign)

            # Mutate local dict that was passed
            payload["task_ids"].append("t3")
            self.assertEqual(campaign.task_ids, ("t1", "t2"))

            # Ensure loaded object is separate and unmutated
            loaded = store.load()
            loaded_dict = loaded.to_dict()
            loaded_dict["task_ids"].append("t4")

            reloaded = store.load()
            self.assertEqual(reloaded.task_ids, ("t1", "t2"))


if __name__ == "__main__":
    unittest.main()
