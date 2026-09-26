from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ade import (
    CheckpointState,
    CheckpointStore,
    CycleTask,
    ProviderAvailability,
    ProviderAvailabilityRecord,
    ProviderAvailabilityState,
    ProviderCapability,
    ProviderDescriptor,
    ProviderRegistry,
    RoutingRequest,
    RoutedExecutionOutcome,
    TaskCheckpoint,
    run_routed_cycle,
)


class FakeProvider:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.create_calls = 0
        self.get_calls = 0

    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        self.create_calls += 1
        return {"id": self.session_id}

    def get_session(self, session_id):
        self.get_calls += 1
        if session_id != self.session_id:
            raise AssertionError("unexpected session")
        return {"state": "COMPLETED", "outputs": []}

    def list_activities(self, session_id):
        return []

    def send_message(self, session_id, prompt):
        return None

    def approve_plan(self, session_id):
        return None


def descriptor(provider_id: str, priority: int) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        capabilities=(
            ProviderCapability.GITHUB_SOURCE,
            ProviderCapability.RESUME_SESSION,
        ),
        priority=priority,
    )


class RoutedExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
        self.task = CycleTask(
            task_id="route-task",
            title="route",
            prompt="route",
            timeout_seconds=60,
            poll_interval_seconds=5,
        )
        self.primary = FakeProvider("primary-session")
        self.fallback = FakeProvider("fallback-session")
        self.registry = ProviderRegistry.from_pairs(
            [
                (descriptor("primary", 10), self.primary),
                (descriptor("fallback", 20), self.fallback),
            ]
        )
        self.request = RoutingRequest(
            required_capabilities=(ProviderCapability.GITHUB_SOURCE,),
            preferred_provider_ids=("primary", "fallback"),
        )

    def store(self, directory: str) -> CheckpointStore:
        return CheckpointStore(Path(directory) / "checkpoint.json")

    def test_primary_provider_executes_and_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord("primary", ProviderAvailability.AVAILABLE),
                        ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=store,
            )
            self.assertEqual(result.outcome, RoutedExecutionOutcome.EXECUTED)
            self.assertEqual(result.provider_id, "primary")
            self.assertEqual(self.primary.create_calls, 1)
            self.assertEqual(self.fallback.create_calls, 0)
            self.assertEqual(store.load().provider_id, "primary")

    def test_quota_paused_primary_falls_back_before_session_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord(
                            "primary",
                            ProviderAvailability.QUOTA_PAUSED,
                            resume_after=(self.now + timedelta(hours=1)).isoformat(),
                        ),
                        ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=self.store(directory),
            )
            self.assertEqual(result.provider_id, "fallback")
            self.assertEqual(self.primary.create_calls, 0)
            self.assertEqual(self.fallback.create_calls, 1)

    def test_sticky_resume_never_creates_fallback_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save(
                TaskCheckpoint(
                    task_id=self.task.task_id,
                    state=CheckpointState.RUNNING,
                    attempt=0,
                    replan_count=0,
                    provider_session_id="primary-session",
                    provider_id="primary",
                )
            )
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord("primary", ProviderAvailability.AVAILABLE),
                        ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=store,
            )
            self.assertEqual(result.provider_id, "primary")
            self.assertEqual(self.primary.create_calls, 0)
            self.assertEqual(self.primary.get_calls, 1)
            self.assertEqual(self.fallback.create_calls, 0)

    def test_unavailable_sticky_provider_waits_instead_of_migrating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save(
                TaskCheckpoint(
                    task_id=self.task.task_id,
                    state=CheckpointState.RUNNING,
                    attempt=0,
                    replan_count=0,
                    provider_session_id="primary-session",
                    provider_id="primary",
                )
            )
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord(
                            "primary",
                            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                            resume_after=(self.now + timedelta(hours=1)).isoformat(),
                        ),
                        ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=store,
            )
            self.assertEqual(result.outcome, RoutedExecutionOutcome.WAIT)
            self.assertEqual(result.provider_id, "primary")
            self.assertEqual(self.primary.create_calls, 0)
            self.assertEqual(self.fallback.create_calls, 0)

    def test_legacy_session_without_provider_identity_requires_replan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save(
                TaskCheckpoint(
                    task_id=self.task.task_id,
                    state=CheckpointState.RUNNING,
                    attempt=0,
                    replan_count=0,
                    provider_session_id="legacy-session",
                )
            )
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord("primary", ProviderAvailability.AVAILABLE),
                        ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=store,
            )
            self.assertEqual(result.outcome, RoutedExecutionOutcome.REPLAN)
            self.assertEqual(self.primary.create_calls, 0)
            self.assertEqual(self.fallback.create_calls, 0)

    def test_no_provider_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_routed_cycle(
                self.registry,
                self.request,
                ProviderAvailabilityState(
                    records=(
                        ProviderAvailabilityRecord(
                            "primary",
                            ProviderAvailability.QUOTA_PAUSED,
                            resume_after=(self.now + timedelta(hours=1)).isoformat(),
                        ),
                        ProviderAvailabilityRecord(
                            "fallback",
                            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                            resume_after=(self.now + timedelta(hours=2)).isoformat(),
                        ),
                    )
                ),
                now=self.now,
                task=self.task,
                source_name="source",
                store=self.store(directory),
            )
            self.assertEqual(result.outcome, RoutedExecutionOutcome.NO_PROVIDER)
            self.assertIsNone(result.provider_id)
            self.assertEqual(self.primary.create_calls, 0)
            self.assertEqual(self.fallback.create_calls, 0)


if __name__ == "__main__":
    unittest.main()
