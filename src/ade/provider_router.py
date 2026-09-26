from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .provider_registry import ProviderRegistry
from .provider_routing import RoutingRequest


class ProviderAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    QUOTA_PAUSED = "QUOTA_PAUSED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNAUTHORIZED = "UNAUTHORIZED"
    DISABLED = "DISABLED"


class RoutingOutcome(StrEnum):
    SELECTED = "SELECTED"
    NO_PROVIDER = "NO_PROVIDER"


@dataclass(frozen=True, slots=True)
class ProviderAvailabilitySnapshot:
    provider_id: str
    availability: ProviderAvailability
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("provider_id must be a non-empty string")
        if self.provider_id != self.provider_id.strip():
            raise ValueError(
                "provider_id must not contain leading or trailing whitespace"
            )
        try:
            normalized = ProviderAvailability(self.availability)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"invalid provider availability: {self.availability!r}"
            ) from exc
        object.__setattr__(self, "availability", normalized)

        if self.reason is not None:
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("reason must be a non-empty string or None")
            object.__setattr__(self, "reason", self.reason.strip())


@dataclass(frozen=True, slots=True)
class RoutingSkip:
    provider_id: str
    availability: ProviderAvailability
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("provider_id must be a non-empty string")
        try:
            normalized = ProviderAvailability(self.availability)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"invalid provider availability: {self.availability!r}"
            ) from exc
        object.__setattr__(self, "availability", normalized)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    outcome: RoutingOutcome
    selected_provider_id: str | None
    candidate_provider_ids: tuple[str, ...]
    skipped: tuple[RoutingSkip, ...]
    reason: str

    def __post_init__(self) -> None:
        try:
            outcome = RoutingOutcome(self.outcome)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid routing outcome: {self.outcome!r}") from exc
        object.__setattr__(self, "outcome", outcome)

        if self.selected_provider_id is not None:
            if (
                not isinstance(self.selected_provider_id, str)
                or not self.selected_provider_id
            ):
                raise ValueError(
                    "selected_provider_id must be a non-empty string or None"
                )

        if not isinstance(self.candidate_provider_ids, tuple):
            object.__setattr__(
                self,
                "candidate_provider_ids",
                tuple(self.candidate_provider_ids),
            )
        if len(set(self.candidate_provider_ids)) != len(
            self.candidate_provider_ids
        ):
            raise ValueError("candidate_provider_ids must be unique")
        for provider_id in self.candidate_provider_ids:
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError(
                    "candidate_provider_ids must contain non-empty strings"
                )

        if not isinstance(self.skipped, tuple):
            object.__setattr__(self, "skipped", tuple(self.skipped))
        for skip in self.skipped:
            if not isinstance(skip, RoutingSkip):
                raise ValueError("skipped must contain RoutingSkip values")

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")

        if outcome is RoutingOutcome.SELECTED:
            if self.selected_provider_id is None:
                raise ValueError(
                    "SELECTED routing decision requires selected_provider_id"
                )
            if self.selected_provider_id not in self.candidate_provider_ids:
                raise ValueError(
                    "selected_provider_id must be in candidate_provider_ids"
                )
        elif self.selected_provider_id is not None:
            raise ValueError(
                "NO_PROVIDER routing decision cannot select a provider"
            )


def route_provider(
    registry: ProviderRegistry,
    request: RoutingRequest,
    availability: Iterable[ProviderAvailabilitySnapshot],
) -> RoutingDecision:
    if not isinstance(registry, ProviderRegistry):
        raise ValueError("registry must be a ProviderRegistry")
    if not isinstance(request, RoutingRequest):
        raise ValueError("request must be a RoutingRequest")
    if isinstance(availability, (str, bytes)):
        raise ValueError(
            "availability must be an iterable of ProviderAvailabilitySnapshot"
        )

    snapshots: dict[str, ProviderAvailabilitySnapshot] = {}
    try:
        iterator = iter(availability)
    except TypeError as exc:
        raise ValueError(
            "availability must be an iterable of ProviderAvailabilitySnapshot"
        ) from exc

    for snapshot in iterator:
        if not isinstance(snapshot, ProviderAvailabilitySnapshot):
            raise ValueError(
                "availability must contain ProviderAvailabilitySnapshot values"
            )
        if snapshot.provider_id in snapshots:
            raise ValueError(
                f"duplicate availability snapshot: {snapshot.provider_id}"
            )
        snapshots[snapshot.provider_id] = snapshot

    candidates = registry.candidates(request)
    candidate_ids = tuple(item.provider_id for item in candidates)
    skipped: list[RoutingSkip] = []

    for registration in candidates:
        provider_id = registration.provider_id
        snapshot = snapshots.get(provider_id)
        if snapshot is None:
            skipped.append(
                RoutingSkip(
                    provider_id=provider_id,
                    availability=ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                    reason="availability snapshot is missing",
                )
            )
            continue

        if snapshot.availability is ProviderAvailability.AVAILABLE:
            return RoutingDecision(
                outcome=RoutingOutcome.SELECTED,
                selected_provider_id=provider_id,
                candidate_provider_ids=candidate_ids,
                skipped=tuple(skipped),
                reason=f"selected first available provider: {provider_id}",
            )

        reason = snapshot.reason or (
            f"provider is {snapshot.availability.value.lower()}"
        )
        skipped.append(
            RoutingSkip(
                provider_id=provider_id,
                availability=snapshot.availability,
                reason=reason,
            )
        )

    if not candidate_ids:
        reason = "no providers satisfy the routing request"
    else:
        reason = "no eligible provider is currently available"

    return RoutingDecision(
        outcome=RoutingOutcome.NO_PROVIDER,
        selected_provider_id=None,
        candidate_provider_ids=candidate_ids,
        skipped=tuple(skipped),
        reason=reason,
    )
