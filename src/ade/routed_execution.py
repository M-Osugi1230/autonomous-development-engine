from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .checkpoint import CheckpointState, TaskCheckpoint
from .checkpoint_runtime import CheckpointedCycleExecution, run_checkpointed_cycle
from .checkpoint_store import CheckpointStore
from .cycle import CycleTask
from .provider_availability import ProviderAvailabilityState, evaluate_provider_availability_state
from .provider_registry import ProviderRegistry
from .provider_router import RoutingDecision, RoutingOutcome, route_provider
from .provider_routing import RoutingRequest
from .repair import RepairPolicy


class RoutedExecutionOutcome(StrEnum):
    EXECUTED = "EXECUTED"
    WAIT = "WAIT"
    REPLAN = "REPLAN"
    NO_PROVIDER = "NO_PROVIDER"


@dataclass(frozen=True, slots=True)
class RoutedCycleExecution:
    outcome: RoutedExecutionOutcome
    provider_id: str | None
    execution: CheckpointedCycleExecution | None
    routing: RoutingDecision | None
    reason: str

    def __post_init__(self) -> None:
        try:
            outcome = RoutedExecutionOutcome(self.outcome)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid routed execution outcome: {self.outcome!r}") from exc
        object.__setattr__(self, "outcome", outcome)
        if self.provider_id is not None and (
            not isinstance(self.provider_id, str) or not self.provider_id.strip()
        ):
            raise ValueError("provider_id must be a non-empty string or None")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if outcome is RoutedExecutionOutcome.EXECUTED:
            if self.provider_id is None or self.execution is None:
                raise ValueError("EXECUTED requires provider_id and execution")
        elif self.execution is not None:
            raise ValueError(f"{outcome.value} cannot contain an execution")


def run_routed_cycle(
    registry: ProviderRegistry,
    request: RoutingRequest,
    availability_state: ProviderAvailabilityState,
    *,
    now: datetime,
    task: CycleTask,
    source_name: str,
    store: CheckpointStore,
    policy: RepairPolicy | None = None,
    existing_checkpoint: TaskCheckpoint | None = None,
) -> RoutedCycleExecution:
    if not isinstance(registry, ProviderRegistry):
        raise ValueError("registry must be a ProviderRegistry")
    if not isinstance(request, RoutingRequest):
        raise ValueError("request must be a RoutingRequest")
    if not isinstance(availability_state, ProviderAvailabilityState):
        raise ValueError("availability_state must be a ProviderAvailabilityState")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    if not isinstance(task, CycleTask):
        raise ValueError("task must be a CycleTask")
    if not isinstance(store, CheckpointStore):
        raise ValueError("store must be a CheckpointStore")

    checkpoint = existing_checkpoint
    if checkpoint is None:
        try:
            loaded = store.load()
        except (FileNotFoundError, ValueError):
            loaded = None
        if loaded is not None and loaded.task_id == task.task_id:
            checkpoint = loaded

    if checkpoint is not None:
        if checkpoint.task_id != task.task_id:
            raise ValueError("existing checkpoint belongs to a different task")
        if checkpoint.provider_session_id:
            if checkpoint.provider_id is None:
                return RoutedCycleExecution(
                    outcome=RoutedExecutionOutcome.REPLAN,
                    provider_id=None,
                    execution=None,
                    routing=None,
                    reason="existing provider session has no provider_id and cannot be migrated safely",
                )
            registration = registry.get(checkpoint.provider_id)
            if registration is None:
                return RoutedCycleExecution(
                    outcome=RoutedExecutionOutcome.WAIT,
                    provider_id=checkpoint.provider_id,
                    execution=None,
                    routing=None,
                    reason="sticky provider is not registered",
                )
            snapshots = {
                item.provider_id: item
                for item in evaluate_provider_availability_state(
                    availability_state,
                    now=now,
                )
            }
            snapshot = snapshots.get(checkpoint.provider_id)
            if snapshot is None or snapshot.availability.value != "AVAILABLE":
                return RoutedCycleExecution(
                    outcome=RoutedExecutionOutcome.WAIT,
                    provider_id=checkpoint.provider_id,
                    execution=None,
                    routing=None,
                    reason="sticky provider is not currently available",
                )
            execution = run_checkpointed_cycle(
                registration.provider,
                task=task,
                source_name=source_name,
                store=store,
                policy=policy,
                existing_checkpoint=checkpoint,
                load_existing_checkpoint=False,
                provider_id=checkpoint.provider_id,
            )
            return RoutedCycleExecution(
                outcome=RoutedExecutionOutcome.EXECUTED,
                provider_id=checkpoint.provider_id,
                execution=execution,
                routing=None,
                reason="resumed sticky provider session",
            )

        if checkpoint.state in {
            CheckpointState.HUMAN_WAIT,
            CheckpointState.FAILED,
            CheckpointState.COMPLETED,
        }:
            return RoutedCycleExecution(
                outcome=RoutedExecutionOutcome.WAIT,
                provider_id=checkpoint.provider_id,
                execution=None,
                routing=None,
                reason=f"checkpoint state {checkpoint.state.value} is not routable",
            )

    snapshots = evaluate_provider_availability_state(availability_state, now=now)
    decision = route_provider(registry, request, snapshots)
    if decision.outcome is RoutingOutcome.NO_PROVIDER:
        return RoutedCycleExecution(
            outcome=RoutedExecutionOutcome.NO_PROVIDER,
            provider_id=None,
            execution=None,
            routing=decision,
            reason=decision.reason,
        )

    provider_id = decision.selected_provider_id
    assert provider_id is not None
    registration = registry.require(provider_id)
    execution = run_checkpointed_cycle(
        registration.provider,
        task=task,
        source_name=source_name,
        store=store,
        policy=policy,
        existing_checkpoint=checkpoint,
        load_existing_checkpoint=False,
        provider_id=provider_id,
    )
    return RoutedCycleExecution(
        outcome=RoutedExecutionOutcome.EXECUTED,
        provider_id=provider_id,
        execution=execution,
        routing=decision,
        reason=f"executed with routed provider: {provider_id}",
    )
