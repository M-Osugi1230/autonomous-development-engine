from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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


def _parse_resume_after(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resume_after must be a non-empty ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("resume_after must be timezone-aware")
    return parsed.astimezone(UTC)


def broker_resume_action(
    checkpoint: dict[str, Any],
    *,
    now: datetime,
    fallback_available: bool,
) -> tuple[str, str | None, str | None]:
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be a JSON object")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    state = checkpoint.get("state")
    if not isinstance(state, str):
        raise ValueError("checkpoint state must be a string")
    session_id = checkpoint.get("provider_session_id")
    if session_id is not None and (
        not isinstance(session_id, str) or not session_id.strip()
    ):
        raise ValueError("provider_session_id must be a non-empty string or null")
    provider_id = checkpoint_provider_id(checkpoint)

    if state in {"COMPLETED", "FAILED", "HUMAN_WAIT", "REPLAN"}:
        return "NOOP", session_id, provider_id

    if state == "RUNNING":
        if not session_id:
            raise ValueError("RUNNING checkpoint requires provider_session_id")
        return "MONITOR", session_id, provider_id

    if state == "PAUSED_QUOTA":
        due = _parse_resume_after(checkpoint.get("resume_after"))
        if session_id:
            if due is None or now.astimezone(UTC) < due:
                return "WAIT", session_id, provider_id
            return "MONITOR", session_id, provider_id

        # No provider session exists yet, so safe rerouting remains possible.
        if fallback_available:
            return "START_NEW", None, None
        if due is None or now.astimezone(UTC) < due:
            return "WAIT", None, None
        return "START_NEW", None, None

    raise ValueError(f"unsupported checkpoint state: {state}")
