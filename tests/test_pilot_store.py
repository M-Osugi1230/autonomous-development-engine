from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ade import (
    PilotAcceptanceCheck,
    PilotAction,
    PilotContract,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
)
from ade.pilot_store import PilotContractStore


def build_contract() -> PilotContract:
    return PilotContract(
        pilot_id="pilot-store-test",
        target=PilotTarget(
            repository="owner/repo",
            base_branch="main",
            baseline_sha="b" * 40,
        ),
        goal="Persist the pilot contract safely.",
        safety=PilotSafetyEnvelope(
            allowed_path_prefixes=("src", "tests"),
            forbidden_path_prefixes=(".github", ".autodev"),
            allowed_actions=(
                PilotAction.READ,
                PilotAction.MODIFY_FILES,
                PilotAction.RUN_VALIDATION,
                PilotAction.OPEN_PULL_REQUEST,
            ),
        ),
        provider_policy=PilotProviderPolicy(
            allowed_provider_ids=("jules", "github-copilot"),
            preferred_provider_ids=("jules", "github-copilot"),
        ),
        acceptance_checks=(
            PilotAcceptanceCheck(
                check_id="unit-tests",
                command="python -m unittest",
            ),
        ),
    )


class PilotContractStoreTests(unittest.TestCase):
    def test_save_load_round_trip_and_parent_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "pilot" / "contract.json"
            store = PilotContractStore(path)
            contract = build_contract()

            store.save(contract)

            self.assertTrue(path.exists())
            self.assertEqual(store.load(), contract)
            raw = path.read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("\n"))
            self.assertEqual(json.loads(raw), contract.to_dict())

    def test_save_replaces_existing_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "contract.json"
            store = PilotContractStore(path)
            first = build_contract()
            store.save(first)

            second_payload = first.to_dict()
            second_payload["goal"] = "Updated bounded pilot goal."
            second = PilotContract.from_dict(second_payload)
            store.save(second)

            self.assertEqual(store.load(), second)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), second.to_dict())

    def test_missing_file_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PilotContractStore(Path(temp_dir) / "missing.json")
            with self.assertRaises(FileNotFoundError):
                store.load()

    def test_invalid_json_and_non_object_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "contract.json"
            store = PilotContractStore(path)

            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

    def test_invalid_contract_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "contract.json"
            path.write_text(
                json.dumps({"schema_version": 1, "pilot_id": "missing-fields"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                PilotContractStore(path).load()

    def test_wrong_save_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PilotContractStore(Path(temp_dir) / "contract.json")
            with self.assertRaises(TypeError):
                store.save(object())  # type: ignore[arg-type]

    def test_temp_file_is_cleaned_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "contract.json"
            store = PilotContractStore(path)

            with patch("ade.pilot_store.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    store.save(build_contract())

            leftovers = list(path.parent.glob(f".{path.name}.*.tmp"))
            self.assertEqual(leftovers, [])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
