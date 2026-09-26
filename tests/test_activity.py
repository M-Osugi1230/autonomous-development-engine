from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import ActivityEvent, ActivityKind, ActivityStore


class ActivityEventTests(unittest.TestCase):
    def test_round_trip_and_timezone_validation(self) -> None:
        event = ActivityEvent(
            event_id="evt-1",
            kind=ActivityKind.TASK_COMPLETED,
            occurred_at="2026-09-26T01:30:00+00:00",
            summary="Completed task 27",
            task_id="vertical-slice-027",
        )
        self.assertEqual(ActivityEvent.from_dict(event.to_dict()), event)

        with self.assertRaises(ValueError):
            ActivityEvent(
                event_id="evt-2",
                kind=ActivityKind.SYSTEM,
                occurred_at="2026-09-26T01:30:00",
                summary="naive time",
            )

    def test_rejects_secret_and_traceback_text(self) -> None:
        with self.assertRaises(ValueError):
            ActivityEvent(
                event_id="evt-secret",
                kind=ActivityKind.SYSTEM,
                occurred_at="2026-09-26T01:30:00+00:00",
                summary="token ghp_123456789012345678901234567890123456",
            )
        with self.assertRaises(ValueError):
            ActivityEvent(
                event_id="evt-trace",
                kind=ActivityKind.SYSTEM,
                occurred_at="2026-09-26T01:30:00+00:00",
                summary="Traceback (most recent call last) ...",
            )


class ActivityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "nested" / "activity.json"
        self.store = ActivityStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def event(self, event_id: str, summary: str | None = None) -> ActivityEvent:
        return ActivityEvent(
            event_id=event_id,
            kind=ActivityKind.MILESTONE,
            occurred_at=f"2026-09-26T01:3{len(event_id)}:00+00:00",
            summary=summary or event_id,
        )

    def test_missing_store_is_empty_and_save_creates_parent(self) -> None:
        self.assertEqual(self.store.load(), ())
        event = self.event("a")
        self.store.save([event])
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.load(), (event,))

    def test_append_is_idempotent_and_conflicts_are_rejected(self) -> None:
        first = self.event("event-a", "first")
        self.assertEqual(self.store.append(first), first)
        self.assertEqual(self.store.append(first), first)
        self.assertEqual(self.store.load(), (first,))

        with self.assertRaises(ValueError):
            self.store.append(self.event("event-a", "changed"))

    def test_recent_returns_newest_first_without_mutating_store_order(self) -> None:
        events = [self.event(f"event-{index}") for index in range(4)]
        self.store.save(events)
        self.assertEqual(
            [event.event_id for event in self.store.recent(2)],
            ["event-3", "event-2"],
        )
        self.assertEqual(
            [event.event_id for event in self.store.load()],
            ["event-0", "event-1", "event-2", "event-3"],
        )

    def test_invalid_schema_duplicate_and_invalid_json_are_rejected(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"schema_version":2,"events":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

        event = self.event("dup")
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "events": [event.to_dict(), event.to_dict()],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text("{bad-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

    def test_atomic_replacement_leaves_no_temp_file(self) -> None:
        self.store.save([self.event("one")])
        self.store.save([self.event("two")])
        self.assertEqual(self.store.load()[0].event_id, "two")
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
