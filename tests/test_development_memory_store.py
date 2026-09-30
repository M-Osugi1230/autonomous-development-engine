from __future__ import annotations

import copy
import unittest

from ade.development_memory import DevelopmentMemoryError, DevelopmentMemoryRecord, MemoryKind
from ade.development_memory_store import (
    DevelopmentMemoryStore,
    merge_memory_records,
)


def record(memory_id: str, statement: str = "Trusted runtime outcome.") -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository="owner/repo",
        source_sha="a" * 40,
        statement=statement,
        evidence_paths=(".autodev/runtime-verification/task/report.json",),
        evidence_fingerprints=("1" * 64,),
        tags=("feedback", "runtime", "verified"),
        task_id="task-001",
    )


class DevelopmentMemoryStoreTests(unittest.TestCase):
    def test_round_trip_and_fingerprint_are_strict(self) -> None:
        store = DevelopmentMemoryStore().canonical_dict()
        loaded = DevelopmentMemoryStore.from_dict(store)
        self.assertEqual(loaded.canonical_dict(), store)

        tampered = copy.deepcopy(store)
        tampered["ledger_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(DevelopmentMemoryError, "fingerprint"):
            DevelopmentMemoryStore.from_dict(tampered)

    def test_merge_is_idempotent(self) -> None:
        first = merge_memory_records(
            DevelopmentMemoryStore(),
            (record("memory-001"),),
        )
        self.assertTrue(first.changed)
        self.assertEqual(first.added_memory_ids, ("memory-001",))

        repeated = merge_memory_records(
            first.store,
            (record("memory-001"),),
        )
        self.assertFalse(repeated.changed)
        self.assertEqual(repeated.added_memory_ids, ())
        self.assertEqual(repeated.store.canonical_dict(), first.store.canonical_dict())

    def test_same_id_different_content_fails_closed(self) -> None:
        store = merge_memory_records(
            DevelopmentMemoryStore(),
            (record("memory-001"),),
        ).store
        with self.assertRaisesRegex(DevelopmentMemoryError, "collision"):
            merge_memory_records(
                store,
                (record("memory-001", "Different trusted runtime outcome."),),
            )

    def test_store_rejects_unknown_fields_and_record_count_drift(self) -> None:
        payload = merge_memory_records(
            DevelopmentMemoryStore(),
            (record("memory-001"),),
        ).store.canonical_dict()

        unknown = copy.deepcopy(payload)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(DevelopmentMemoryError, "unknown"):
            DevelopmentMemoryStore.from_dict(unknown)

        drift = copy.deepcopy(payload)
        drift["ledger"]["record_count"] = 99
        with self.assertRaisesRegex(DevelopmentMemoryError, "record_count"):
            DevelopmentMemoryStore.from_dict(drift)


if __name__ == "__main__":
    unittest.main()
