from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    DecisionPriority,
    DecisionRecord,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    DecisionStore,
)


class DecisionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = self.root / "nested" / "decisions.json"
        self.store = DecisionStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_record(self, decision_id: str = "dec-1") -> DecisionRecord:
        request = DecisionRequest(
            decision_id=decision_id,
            question="Approve the irreversible migration?",
            options=("approve", "reject"),
            priority=DecisionPriority.P0,
            blocking_task_id="task-1",
            context={"scope": "database"},
        )
        return DecisionRecord(request=request)

    def test_missing_store_loads_as_empty_and_parent_is_created(self) -> None:
        self.assertEqual(self.store.load(), ())
        self.assertFalse(self.path.parent.exists())

        record = self.make_record()
        self.store.enqueue(record)

        self.assertTrue(self.path.exists())
        self.assertTrue(self.path.parent.exists())
        self.assertEqual(self.store.load(), (record,))

    def test_round_trip_and_deterministic_ordering(self) -> None:
        first = self.make_record("dec-1")
        second = self.make_record("dec-2")

        self.store.enqueue(first)
        self.store.enqueue(second)

        self.assertEqual(self.store.load(), (first, second))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            [item["request"]["decision_id"] for item in payload["decisions"]],
            ["dec-1", "dec-2"],
        )

    def test_idempotent_enqueue_same_record_does_not_duplicate(self) -> None:
        record = self.make_record()
        first = self.store.enqueue(record)
        second = self.store.enqueue(record)

        self.assertEqual(first, second)
        self.assertEqual(self.store.load(), (record,))

    def test_enqueue_rejects_conflicting_duplicate_id(self) -> None:
        original = self.make_record("dec-1")
        conflicting = DecisionRecord(
            request=DecisionRequest(
                decision_id="dec-1",
                question="Different question?",
                options=("yes", "no"),
                priority=DecisionPriority.P1,
                blocking_task_id="task-2",
            )
        )
        self.store.enqueue(original)

        with self.assertRaises(ValueError):
            self.store.enqueue(conflicting)

        self.assertEqual(self.store.load(), (original,))

    def test_list_open_filters_resolved_records(self) -> None:
        first = self.make_record("dec-1")
        second = self.make_record("dec-2")
        self.store.enqueue(first)
        self.store.enqueue(second)
        self.store.resolve(
            "dec-1",
            DecisionResponse(
                decision_id="dec-1",
                text="Approved.",
                selected_option="approve",
            ),
        )

        open_records = self.store.list_open()
        self.assertEqual(tuple(record.decision_id for record in open_records), ("dec-2",))

    def test_resolve_persists_valid_response(self) -> None:
        record = self.make_record()
        self.store.enqueue(record)
        response = DecisionResponse(
            decision_id="dec-1",
            text="Approved after backup verification.",
            selected_option="approve",
        )

        resolved = self.store.resolve("dec-1", response)

        self.assertEqual(resolved.status, DecisionStatus.RESOLVED)
        self.assertEqual(resolved.response, response)
        reloaded = self.store.get("dec-1")
        self.assertEqual(reloaded, resolved)

    def test_repeated_or_conflicting_resolution_is_rejected(self) -> None:
        self.store.enqueue(self.make_record())
        response = DecisionResponse(
            decision_id="dec-1",
            text="Approved.",
            selected_option="approve",
        )
        self.store.resolve("dec-1", response)

        with self.assertRaises(ValueError):
            self.store.resolve("dec-1", response)

        with self.assertRaises(ValueError):
            self.store.resolve(
                "dec-1",
                DecisionResponse(
                    decision_id="dec-1",
                    text="Rejected.",
                    selected_option="reject",
                ),
            )

    def test_resolution_rejects_mismatched_response_id(self) -> None:
        self.store.enqueue(self.make_record())
        with self.assertRaises(ValueError):
            self.store.resolve(
                "dec-1",
                DecisionResponse(
                    decision_id="different",
                    text="Approved.",
                    selected_option="approve",
                ),
            )

    def test_resolution_rejects_unknown_decision(self) -> None:
        with self.assertRaises(KeyError):
            self.store.resolve(
                "missing",
                DecisionResponse(
                    decision_id="missing",
                    text="No record.",
                ),
            )

    def test_invalid_json_and_schema_are_rejected(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text(
            json.dumps({"schema_version": 2, "decisions": []}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text(
            json.dumps({"schema_version": 1, "decisions": {}}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.store.load()

    def test_duplicate_ids_in_file_are_rejected(self) -> None:
        record = self.make_record()
        payload = {
            "schema_version": 1,
            "decisions": [record.to_dict(), record.to_dict()],
        }
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(ValueError):
            self.store.load()

    def test_atomic_replacement_updates_existing_file_without_temp_leaks(self) -> None:
        first = self.make_record("dec-1")
        second = self.make_record("dec-2")
        self.store.save([first])
        original_text = self.path.read_text(encoding="utf-8")

        self.store.save([first, second])
        updated_text = self.path.read_text(encoding="utf-8")

        self.assertNotEqual(original_text, updated_text)
        self.assertEqual(self.store.load(), (first, second))
        temp_files = list(self.path.parent.glob(f".{self.path.name}.*.tmp"))
        self.assertEqual(temp_files, [])

    def test_secret_or_traceback_payload_is_rejected(self) -> None:
        secret_record = DecisionRecord(
            request=DecisionRequest(
                decision_id="dec-secret",
                question="Proceed?",
                options=("yes", "no"),
                priority=DecisionPriority.P1,
                blocking_task_id="task-secret",
                context={"detail": "bearer abc.def-ghi"},
            )
        )
        with self.assertRaises(ValueError):
            self.store.enqueue(secret_record)

        traceback_record = DecisionRecord(
            request=DecisionRequest(
                decision_id="dec-trace",
                question="Proceed?",
                options=("yes", "no"),
                priority=DecisionPriority.P1,
                blocking_task_id="task-trace",
                context={"detail": "Traceback (most recent call last): boom"},
            )
        )
        with self.assertRaises(ValueError):
            self.store.enqueue(traceback_record)


if __name__ == "__main__":
    unittest.main()
