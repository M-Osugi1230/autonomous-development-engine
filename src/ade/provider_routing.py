from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class ProviderCapability(StrEnum):
    GITHUB_SOURCE = "GITHUB_SOURCE"
    AUTO_CREATE_PR = "AUTO_CREATE_PR"
    PLAN_APPROVAL = "PLAN_APPROVAL"
    INTERACTIVE_MESSAGE = "INTERACTIVE_MESSAGE"
    RESUME_SESSION = "RESUME_SESSION"
    HOSTED_EXECUTION = "HOSTED_EXECUTION"
    LOCAL_EXECUTION = "LOCAL_EXECUTION"


class ProviderCostClass(StrEnum):
    FREE = "FREE"
    FLAT_RATE = "FLAT_RATE"
    USAGE_BASED = "USAGE_BASED"
    LOCAL = "LOCAL"


def _provider_id(value: object, *, field: str = "provider_id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if not _PROVIDER_ID.fullmatch(normalized):
        raise ValueError(
            f"{field} must match {_PROVIDER_ID.pattern}"
        )
    return normalized


def _normalize_capabilities(
    values: Iterable[ProviderCapability | str],
) -> tuple[ProviderCapability, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("capabilities must be an iterable of capability values")

    normalized: list[ProviderCapability] = []
    seen: set[ProviderCapability] = set()
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError("capabilities must be iterable") from exc

    for raw in iterator:
        try:
            capability = ProviderCapability(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid provider capability: {raw!r}") from exc
        if capability in seen:
            raise ValueError(f"duplicate provider capability: {capability.value}")
        seen.add(capability)
        normalized.append(capability)

    normalized.sort(key=lambda item: item.value)
    return tuple(normalized)


def _normalize_provider_ids(
    values: Iterable[str] | None,
    *,
    field: str,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must be an iterable of provider IDs or None")

    normalized: list[str] = []
    seen: set[str] = set()
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError(f"{field} must be iterable or None") from exc

    for raw in iterator:
        provider_id = _provider_id(raw, field=field)
        if provider_id in seen:
            raise ValueError(f"{field} contains duplicate provider ID: {provider_id}")
        seen.add(provider_id)
        normalized.append(provider_id)

    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    capabilities: tuple[ProviderCapability, ...]
    priority: int = 100
    enabled: bool = True
    cost_class: ProviderCostClass | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))

        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string")
        object.__setattr__(self, "display_name", self.display_name.strip())

        object.__setattr__(
            self,
            "capabilities",
            _normalize_capabilities(self.capabilities),
        )

        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("priority must be a non-negative integer")

        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")

        if self.cost_class is not None:
            try:
                cost_class = ProviderCostClass(self.cost_class)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid cost_class: {self.cost_class!r}") from exc
            object.__setattr__(self, "cost_class", cost_class)

    def supports(self, capability: ProviderCapability | str) -> bool:
        try:
            normalized = ProviderCapability(capability)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid provider capability: {capability!r}") from exc
        return normalized in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "capabilities": [item.value for item in self.capabilities],
            "priority": self.priority,
            "enabled": self.enabled,
            "cost_class": (
                self.cost_class.value if self.cost_class is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderDescriptor":
        if not isinstance(payload, dict):
            raise ValueError("provider descriptor payload must be a JSON object")
        required = {"provider_id", "display_name", "capabilities"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(
                f"provider descriptor missing required keys: {sorted(missing)}"
            )
        capabilities = payload["capabilities"]
        if not isinstance(capabilities, (list, tuple)):
            raise ValueError("capabilities must be a list")
        return cls(
            provider_id=payload["provider_id"],
            display_name=payload["display_name"],
            capabilities=tuple(capabilities),
            priority=payload.get("priority", 100),
            enabled=payload.get("enabled", True),
            cost_class=payload.get("cost_class"),
        )


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    required_capabilities: tuple[ProviderCapability, ...] = ()
    allowed_provider_ids: tuple[str, ...] | None = None
    preferred_provider_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_capabilities",
            _normalize_capabilities(self.required_capabilities),
        )

        allowed = _normalize_provider_ids(
            self.allowed_provider_ids,
            field="allowed_provider_ids",
        )
        object.__setattr__(self, "allowed_provider_ids", allowed)

        preferred = _normalize_provider_ids(
            self.preferred_provider_ids,
            field="preferred_provider_ids",
        )
        assert preferred is not None
        object.__setattr__(self, "preferred_provider_ids", preferred)

        if allowed is not None:
            disallowed = [
                provider_id
                for provider_id in preferred
                if provider_id not in allowed
            ]
            if disallowed:
                raise ValueError(
                    "preferred_provider_ids must be contained in "
                    f"allowed_provider_ids: {disallowed}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_capabilities": [
                item.value for item in self.required_capabilities
            ],
            "allowed_provider_ids": (
                list(self.allowed_provider_ids)
                if self.allowed_provider_ids is not None
                else None
            ),
            "preferred_provider_ids": list(self.preferred_provider_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutingRequest":
        if not isinstance(payload, dict):
            raise ValueError("routing request payload must be a JSON object")

        required_capabilities = payload.get("required_capabilities", [])
        allowed_provider_ids = payload.get("allowed_provider_ids")
        preferred_provider_ids = payload.get("preferred_provider_ids", [])

        if not isinstance(required_capabilities, (list, tuple)):
            raise ValueError("required_capabilities must be a list")
        if allowed_provider_ids is not None and not isinstance(
            allowed_provider_ids, (list, tuple)
        ):
            raise ValueError("allowed_provider_ids must be a list or null")
        if not isinstance(preferred_provider_ids, (list, tuple)):
            raise ValueError("preferred_provider_ids must be a list")

        return cls(
            required_capabilities=tuple(deepcopy(required_capabilities)),
            allowed_provider_ids=(
                tuple(deepcopy(allowed_provider_ids))
                if allowed_provider_ids is not None
                else None
            ),
            preferred_provider_ids=tuple(deepcopy(preferred_provider_ids)),
        )
