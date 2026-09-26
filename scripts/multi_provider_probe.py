from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
    RoutedExecutionOutcome,
    RoutingRequest,
    TaskCheckpoint,
    run_routed_cycle,
)


class FakeProvider:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.create_calls = 0
        self.get_calls = 0

    def list_sources(self) -> list[dict[str, Any]]:
        return []

    def create_session(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls += 1
        return {"id": self.session_id}

    def get_session(self, session_id: str) -> dict[str, Any]:
        self.get_calls += 1
        if session_id != self.session_id:
            raise AssertionError(f"unexpected session_id: {session_id}")
        return {"state": "COMPLETED", "outputs": []}

    def list_activities(self, session_id: str) -> list[dict[str, Any]]:
        return []

    def send_message(self, session_id: str, prompt: str) -> None:
        return None

    def approve_plan(self, session_id: str) -> None:
        return None


def _descriptor(provider_id: str, priority: int) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        capabilities=(
            ProviderCapability.GITHUB_SOURCE,
            ProviderCapability.RESUME_SESSION,
        ),
        priority=priority,
    )


def run_probe() -> dict[str, object]:
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    task = CycleTask(
        task_id="phase10-failover-probe",
        title="Phase 10 failover probe",
        prompt="Exercise deterministic multi-provider routing.",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )
    request = RoutingRequest(
        required_capabilities=(ProviderCapability.GITHUB_SOURCE,),
        preferred_provider_ids=("primary", "fallback"),
    )

    primary = FakeProvider("primary-session")
    fallback = FakeProvider("fallback-session")
    registry = ProviderRegistry.from_pairs(
        [
            (_descriptor("primary", 10), primary),
            (_descriptor("fallback", 20), fallback),
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        preferred_store = CheckpointStore(root / "preferred.json")
        preferred = run_routed_cycle(
            registry,
            request,
            ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord("primary", ProviderAvailability.AVAILABLE),
                    ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                )
            ),
            now=now,
            task=task,
            source_name="probe-source",
            store=preferred_store,
        )
        if preferred.outcome is not RoutedExecutionOutcome.EXECUTED:
            raise AssertionError("preferred provider did not execute")
        if preferred.provider_id != "primary":
            raise AssertionError("preferred provider was not selected")
        if primary.create_calls != 1 or fallback.create_calls != 0:
            raise AssertionError("preferred selection created an unexpected session")
        if preferred_store.load().provider_id != "primary":
            raise AssertionError("preferred provider identity was not persisted")

        primary.create_calls = 0
        primary.get_calls = 0
        fallback.create_calls = 0
        fallback.get_calls = 0

        fallback_store = CheckpointStore(root / "fallback.json")
        fallback_result = run_routed_cycle(
            registry,
            request,
            ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord(
                        "primary",
                        ProviderAvailability.QUOTA_PAUSED,
                        resume_after=(now + timedelta(hours=1)).isoformat(),
                    ),
                    ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                )
            ),
            now=now,
            task=task,
            source_name="probe-source",
            store=fallback_store,
        )
        if fallback_result.provider_id != "fallback":
            raise AssertionError("quota-paused primary did not fall back")
        if primary.create_calls != 0 or fallback.create_calls != 1:
            raise AssertionError("fallback occurred after an unexpected primary session creation")
        if fallback_store.load().provider_id != "fallback":
            raise AssertionError("fallback provider identity was not persisted")

        primary.create_calls = 0
        primary.get_calls = 0
        fallback.create_calls = 0
        fallback.get_calls = 0

        sticky_store = CheckpointStore(root / "sticky.json")
        sticky_store.save(
            TaskCheckpoint(
                task_id=task.task_id,
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=0,
                provider_session_id="primary-session",
                provider_id="primary",
            )
        )
        sticky = run_routed_cycle(
            registry,
            request,
            ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord("primary", ProviderAvailability.AVAILABLE),
                    ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                )
            ),
            now=now,
            task=task,
            source_name="probe-source",
            store=sticky_store,
        )
        if sticky.provider_id != "primary":
            raise AssertionError("sticky resume changed providers")
        if primary.create_calls != 0 or primary.get_calls != 1:
            raise AssertionError("sticky resume did not monitor the existing primary session")
        if fallback.create_calls != 0:
            raise AssertionError("sticky resume created a fallback session")

        primary.create_calls = 0
        primary.get_calls = 0
        fallback.create_calls = 0
        fallback.get_calls = 0

        wait_store = CheckpointStore(root / "wait.json")
        wait_store.save(
            TaskCheckpoint(
                task_id=task.task_id,
                state=CheckpointState.RUNNING,
                attempt=0,
                replan_count=0,
                provider_session_id="primary-session",
                provider_id="primary",
            )
        )
        wait = run_routed_cycle(
            registry,
            request,
            ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord(
                        "primary",
                        ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                        resume_after=(now + timedelta(hours=1)).isoformat(),
                    ),
                    ProviderAvailabilityRecord("fallback", ProviderAvailability.AVAILABLE),
                )
            ),
            now=now,
            task=task,
            source_name="probe-source",
            store=wait_store,
        )
        if wait.outcome is not RoutedExecutionOutcome.WAIT:
            raise AssertionError("unavailable sticky provider did not return WAIT")
        if wait.provider_id != "primary":
            raise AssertionError("WAIT lost sticky provider identity")
        if primary.create_calls != 0 or fallback.create_calls != 0:
            raise AssertionError("provider migration occurred after session creation")

        primary.create_calls = 0
        primary.get_calls = 0
        fallback.create_calls = 0
        fallback.get_calls = 0

        none_store = CheckpointStore(root / "none.json")
        no_provider = run_routed_cycle(
            registry,
            request,
            ProviderAvailabilityState(
                records=(
                    ProviderAvailabilityRecord(
                        "primary",
                        ProviderAvailability.QUOTA_PAUSED,
                        resume_after=(now + timedelta(hours=1)).isoformat(),
                    ),
                    ProviderAvailabilityRecord(
                        "fallback",
                        ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                        resume_after=(now + timedelta(hours=2)).isoformat(),
                    ),
                )
            ),
            now=now,
            task=task,
            source_name="probe-source",
            store=none_store,
        )
        if no_provider.outcome is not RoutedExecutionOutcome.NO_PROVIDER:
            raise AssertionError("all-unavailable routing did not return NO_PROVIDER")
        if primary.create_calls != 0 or fallback.create_calls != 0:
            raise AssertionError("NO_PROVIDER path created a provider session")

    return {
        "ok": True,
        "preferred": "primary",
        "quota_fallback": "fallback",
        "sticky_resume": "primary",
        "post_session_failover": "blocked",
        "no_provider": "NO_PROVIDER",
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
