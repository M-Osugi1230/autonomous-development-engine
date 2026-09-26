from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ade import (
    ProviderAvailability,
    ProviderAvailabilityRecord,
    ProviderAvailabilityState,
    ProviderAvailabilityStore,
    evaluate_availability,
    evaluate_provider_availability_state,
)


class ProviderAvailabilityModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def test_quota_pause_before_due_and_due(self) -> None:
        due = (self.now + timedelta(hours=1)).isoformat()
        record = ProviderAvailabilityRecord(
            provider_id="jules",
            availability=ProviderAvailability.QUOTA_PAUSED,
            resume_after=due,
            last_error="rolling quota reached",
        )

        before = evaluate_availability(record, now=self.now)
        self.assertEqual(
            before.availability,
            ProviderAvailability.QUOTA_PAUSED,
        )

        after = evaluate_availability(
            record,
            now=self.now + timedelta(hours=2),
        )
        self.assertEqual(
            after.availability,
            ProviderAvailability.AVAILABLE,
        )
        self.assertEqual(after.reason, "cooldown expired")

    def test_temporary_unavailable_before_due_and_due(self) -> None:
        due = (self.now + timedelta(minutes=10)).isoformat()
        record = ProviderAvailabilityRecord(
            provider_id="backup",
            availability=ProviderAvailability.TEMPORARILY_UNAVAILABLE,
            resume_after=due,
            last_error="transient provider outage",
        )

        before = evaluate_availability(record, now=self.now)
        self.assertEqual(
            before.availability,
            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
        )

        due_snapshot = evaluate_availability(
            record,
            now=self.now + timedelta(minutes=10),
        )
        self.assertEqual(
            due_snapshot.availability,
            ProviderAvailability.AVAILABLE,
        )

    def test_unauthorized_never_auto_recovers(self) -> None:
        record = ProviderAvailabilityRecord(
            provider_id="provider",
            availability=ProviderAvailability.UNAUTHORIZED,
            last_error="authorization failed",
        )
        snapshot = evaluate_availability(
            record,
            now=self.now + timedelta(days=365),
        )
        self.assertEqual(
            snapshot.availability,
            ProviderAvailability.UNAUTHORIZED,
        )

    def test_invalid_or_naive_resume_after_rejected(self) -> None:
        for value in ("not-a-time", "2026-09-26T12:00:00"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ProviderAvailabilityRecord(
                        provider_id="jules",
                        availability=ProviderAvailability.QUOTA_PAUSED,
                        resume_after=value,
                    )

    def test_cooldown_states_require_resume_after(self) -> None:
        for availability in (
            ProviderAvailability.QUOTA_PAUSED,
            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
        ):
            with self.subTest(availability=availability):
                with self.assertRaises(ValueError):
                    ProviderAvailabilityRecord(
                        provider_id="jules",
                        availability=availability,
                    )

    def test_non_cooldown_states_reject_resume_after(self) -> None:
        for availability in (
            ProviderAvailability.AVAILABLE,
            ProviderAvailability.UNAUTHORIZED,
            ProviderAvailability.DISABLED,
        ):
            with self.subTest(availability=availability):
                with self.assertRaises(ValueError):
                    ProviderAvailabilityRecord(
                        provider_id="jules",
                        availability=availability,
                        resume_after=(
                            self.now + timedelta(hours=1)
                        ).isoformat(),
                    )

    def test_secret_like_error_is_rejected(self) -> None:
        secret = "ghp_" + ("A" * 36)
        with self.assertRaises(ValueError):
            ProviderAvailabilityRecord(
                provider_id="jules",
                availability=ProviderAvailability.UNAUTHORIZED,
                last_error=f"credential leaked: {secret}",
            )

    def test_state_round_trip_sorting_and_upsert(self) -> None:
        state = ProviderAvailabilityState(
            records=(
                ProviderAvailabilityRecord(
                    provider_id="zeta",
                    availability=ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilityRecord(
                    provider_id="alpha",
                    availability=ProviderAvailability.UNAUTHORIZED,
                    last_error="authorization failed",
                ),
            )
        )
        self.assertEqual(
            [record.provider_id for record in state.records],
            ["alpha", "zeta"],
        )
        restored = ProviderAvailabilityState.from_dict(
            state.to_dict()
        )
        self.assertEqual(restored, state)

        updated = state.upsert(
            ProviderAvailabilityRecord(
                provider_id="alpha",
                availability=ProviderAvailability.AVAILABLE,
            )
        )
        self.assertEqual(
            updated.get("alpha").availability,
            ProviderAvailability.AVAILABLE,
        )
        self.assertEqual(
            state.get("alpha").availability,
            ProviderAvailability.UNAUTHORIZED,
        )

    def test_duplicate_provider_records_rejected(self) -> None:
        record = ProviderAvailabilityRecord(
            provider_id="jules",
            availability=ProviderAvailability.AVAILABLE,
        )
        with self.assertRaises(ValueError):
            ProviderAvailabilityState(records=(record, record))

    def test_evaluate_state_is_deterministic_and_validates_now(self) -> None:
        state = ProviderAvailabilityState(
            records=(
                ProviderAvailabilityRecord(
                    provider_id="b",
                    availability=ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilityRecord(
                    provider_id="a",
                    availability=ProviderAvailability.UNAUTHORIZED,
                    last_error="authorization failed",
                ),
            )
        )
        first = evaluate_provider_availability_state(
            state,
            now=self.now,
        )
        second = evaluate_provider_availability_state(
            state,
            now=self.now,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [item.provider_id for item in first],
            ["a", "b"],
        )

        with self.assertRaises(ValueError):
            evaluate_provider_availability_state(
                state,
                now=datetime(2026, 9, 26, 12, 0),
            )


class ProviderAvailabilityStoreTests(unittest.TestCase):
    def test_save_load_round_trip_and_parent_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "availability.json"
            store = ProviderAvailabilityStore(path)
            state = ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord(
                        provider_id="jules",
                        availability=ProviderAvailability.AVAILABLE,
                    ),
                )
            )

            store.save(state)
            self.assertTrue(path.exists())
            self.assertEqual(store.load(), state)
            self.assertTrue(
                path.read_text(encoding="utf-8").endswith("\n")
            )

    def test_load_or_empty_only_swallows_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "availability.json"
            store = ProviderAvailabilityStore(path)
            self.assertEqual(
                store.load_or_empty(),
                ProviderAvailabilityState(),
            )

            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load_or_empty()

    def test_invalid_json_and_non_object_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "availability.json"
            store = ProviderAvailabilityStore(path)

            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

    def test_existing_state_is_atomically_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "availability.json"
            store = ProviderAvailabilityStore(path)

            first = ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord(
                        provider_id="jules",
                        availability=ProviderAvailability.AVAILABLE,
                    ),
                )
            )
            second = first.upsert(
                ProviderAvailabilityRecord(
                    provider_id="jules",
                    availability=ProviderAvailability.UNAUTHORIZED,
                    last_error="authorization failed",
                )
            )

            store.save(first)
            store.save(second)
            self.assertEqual(store.load(), second)

    def test_temp_file_is_cleaned_if_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "availability.json"
            store = ProviderAvailabilityStore(path)
            state = ProviderAvailabilityState()

            with patch(
                "ade.provider_availability_store.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    store.save(state)

            leftovers = list(
                path.parent.glob(f".{path.name}.*.tmp")
            )
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
