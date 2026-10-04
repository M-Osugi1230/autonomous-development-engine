from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider_registry import ProviderRegistry
from .provider_router import (
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
    RoutingDecision,
    route_provider,
)
from .provider_routing import (
    ProviderCapability,
    ProviderCostClass,
    ProviderDescriptor,
    RoutingRequest,
)


JULES_PROVIDER_ID = "jules"
COPILOT_PROVIDER_ID = "github-copilot"


@dataclass(frozen=True, slots=True)
class BrokerAvailability:
    jules_available: bool
    copilot_available: bool
    jules_reason: str | None = None
    copilot_reason: str | None = None


def provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    capabilities = (
        ProviderCapability.AUTO_CREATE_PR,
        ProviderCapability.GITHUB_SOURCE,
        ProviderCapability.HOSTED_EXECUTION,
        ProviderCapability.RESUME_SESSION,
    )
    return (
        ProviderDescriptor(
            provider_id=JULES_PROVIDER_ID,
            display_name="Jules",
            capabilities=capabilities,
            priority=10,
            cost_class=ProviderCostClass.FREE,
        ),
        ProviderDescriptor(
            provider_id=COPILOT_PROVIDER_ID,
            display_name="GitHub Copilot coding agent",
            capabilities=capabilities,
            priority=20,
            cost_class=ProviderCostClass.USAGE_BASED,
        ),
    )


def implementation_routing_request() -> RoutingRequest:
    return RoutingRequest(
        required_capabilities=(
            ProviderCapability.AUTO_CREATE_PR,
            ProviderCapability.GITHUB_SOURCE,
            ProviderCapability.HOSTED_EXECUTION,
            ProviderCapability.RESUME_SESSION,
        ),
        preferred_provider_ids=(JULES_PROVIDER_ID, COPILOT_PROVIDER_ID),
    )


def availability_snapshots(
    availability: BrokerAvailability,
) -> tuple[ProviderAvailabilitySnapshot, ...]:
    return (
        ProviderAvailabilitySnapshot(
            provider_id=JULES_PROVIDER_ID,
            availability=(
                ProviderAvailability.AVAILABLE
                if availability.jules_available
                else ProviderAvailability.QUOTA_PAUSED
            ),
            reason=availability.jules_reason,
        ),
        ProviderAvailabilitySnapshot(
            provider_id=COPILOT_PROVIDER_ID,
            availability=(
                ProviderAvailability.AVAILABLE
                if availability.copilot_available
                else ProviderAvailability.DISABLED
            ),
            reason=availability.copilot_reason,
        ),
    )


def route_implementation_provider(
    registry: ProviderRegistry,
    *,
    availability: BrokerAvailability,
) -> RoutingDecision:
    return route_provider(
        registry,
        implementation_routing_request(),
        availability_snapshots(availability),
    )


def checkpoint_provider_id(checkpoint: dict[str, Any]) -> str | None:
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be a JSON object")
    provider_id = checkpoint.get("provider_id")
    session_id = checkpoint.get("provider_session_id")
    if provider_id is not None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string or null")
        return provider_id.strip()
    if isinstance(session_id, str) and session_id.strip():
        # Backward compatibility: every provider session created before the
        # production broker was Jules.
        return JULES_PROVIDER_ID
    return None


def copilot_fallback_enabled(
    *,
    token: str | None,
    explicit_enable: str | None,
) -> bool:
    if not isinstance(token, str) or not token.strip():
        return False
    if not isinstance(explicit_enable, str):
        return False
    return explicit_enable.strip().casefold() in {"1", "true", "yes", "on"}
