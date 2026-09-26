from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .provider_routing import ProviderDescriptor, RoutingRequest
from .providers.base import CodingAgentProvider


_REQUIRED_PROVIDER_METHODS = (
    "list_sources",
    "create_session",
    "get_session",
    "list_activities",
    "send_message",
    "approve_plan",
)


def _validate_provider_instance(provider: object) -> None:
    if provider is None:
        raise ValueError("provider instance must not be None")
    missing = [
        name
        for name in _REQUIRED_PROVIDER_METHODS
        if not callable(getattr(provider, name, None))
    ]
    if missing:
        raise ValueError(
            "provider instance does not satisfy CodingAgentProvider: "
            f"missing callable methods {missing}"
        )


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    descriptor: ProviderDescriptor
    provider: CodingAgentProvider = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ProviderDescriptor):
            raise ValueError("descriptor must be a ProviderDescriptor")
        _validate_provider_instance(self.provider)

    @property
    def provider_id(self) -> str:
        return self.descriptor.provider_id


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    registrations: tuple[ProviderRegistration, ...] = ()

    def __post_init__(self) -> None:
        raw = self.registrations
        if not isinstance(raw, tuple):
            try:
                raw = tuple(raw)
            except TypeError as exc:
                raise ValueError(
                    "registrations must be an iterable of ProviderRegistration values"
                ) from exc

        normalized: list[ProviderRegistration] = []
        seen: set[str] = set()
        for registration in raw:
            if not isinstance(registration, ProviderRegistration):
                raise ValueError(
                    "registrations must contain only ProviderRegistration values"
                )
            provider_id = registration.provider_id
            if provider_id in seen:
                raise ValueError(f"duplicate provider_id: {provider_id}")
            seen.add(provider_id)
            normalized.append(registration)

        object.__setattr__(self, "registrations", tuple(normalized))

    @classmethod
    def from_pairs(
        cls,
        pairs: Iterable[tuple[ProviderDescriptor, CodingAgentProvider]],
    ) -> "ProviderRegistry":
        if isinstance(pairs, (str, bytes)):
            raise ValueError("pairs must be an iterable of descriptor/provider pairs")
        try:
            iterator = iter(pairs)
        except TypeError as exc:
            raise ValueError(
                "pairs must be an iterable of descriptor/provider pairs"
            ) from exc

        registrations: list[ProviderRegistration] = []
        for item in iterator:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError(
                    "each registry pair must contain descriptor and provider"
                )
            descriptor, provider = item
            registrations.append(
                ProviderRegistration(
                    descriptor=descriptor,
                    provider=provider,
                )
            )
        return cls(tuple(registrations))

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            registration.descriptor
            for registration in sorted(
                self.registrations,
                key=lambda item: (
                    item.descriptor.priority,
                    item.provider_id,
                ),
            )
        )

    def descriptor_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(descriptor.to_dict() for descriptor in self.descriptors())

    def get(self, provider_id: str) -> ProviderRegistration | None:
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        for registration in self.registrations:
            if registration.provider_id == provider_id:
                return registration
        return None

    def require(self, provider_id: str) -> ProviderRegistration:
        registration = self.get(provider_id)
        if registration is None:
            raise KeyError(f"provider_id not found: {provider_id}")
        return registration

    def candidates(
        self,
        request: RoutingRequest,
    ) -> tuple[ProviderRegistration, ...]:
        if not isinstance(request, RoutingRequest):
            raise ValueError("request must be a RoutingRequest")

        required = set(request.required_capabilities)
        allowed = (
            set(request.allowed_provider_ids)
            if request.allowed_provider_ids is not None
            else None
        )

        eligible: list[ProviderRegistration] = []
        for registration in self.registrations:
            descriptor = registration.descriptor
            if not descriptor.enabled:
                continue
            if allowed is not None and descriptor.provider_id not in allowed:
                continue
            if not required.issubset(set(descriptor.capabilities)):
                continue
            eligible.append(registration)

        preferred_rank = {
            provider_id: index
            for index, provider_id in enumerate(request.preferred_provider_ids)
        }
        fallback_rank = len(preferred_rank)

        eligible.sort(
            key=lambda item: (
                preferred_rank.get(item.provider_id, fallback_rank),
                item.descriptor.priority,
                item.provider_id,
            )
        )
        return tuple(eligible)
