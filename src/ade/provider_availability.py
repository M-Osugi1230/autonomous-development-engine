from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .checkpoint import MAX_ERROR_LENGTH, SECRET_PATTERNS
from .provider_router import (
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
)


def _parse_timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid ISO-8601 {field}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProviderAvailabilityRecord:
    provider_id: str
    availability: ProviderAvailability
    resume_after: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("provider_id must be a non-empty string")
        if self.provider_id != self.provider_id.strip():
            raise ValueError(
                "provider_id must not contain leading or trailing whitespace"
            )

        try:
            availability = ProviderAvailability(self.availability)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"invalid provider availability: {self.availability!r}"
            ) from exc
        object.__setattr__(self, "availability", availability)

        if self.last_error is not None:
            if not isinstance(self.last_error, str) or not self.last_error.strip():
                raise ValueError("last_error must be a non-empty string or None")
            error = self.last_error.strip()
            for pattern in SECRET_PATTERNS:
                if pattern.search(error):
                    raise ValueError("last_error contains forbidden secret patterns")
            object.__setattr__(
                self,
                "last_error",
                error[:MAX_ERROR_LENGTH],
            )

        if availability in {
            ProviderAvailability.QUOTA_PAUSED,
            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
        }:
            if self.resume_after is None:
                raise ValueError(
                    f"{availability.value} requires resume_after"
                )
            _parse_timestamp(self.resume_after, field="resume_after")
        elif self.resume_after is not None:
            raise ValueError(
                f"{availability.value} cannot have resume_after"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "availability": self.availability.value,
            "resume_after": self.resume_after,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ProviderAvailabilityRecord":
        if not isinstance(payload, dict):
            raise ValueError(
                "provider availability record must be a JSON object"
            )
        if "provider_id" not in payload or "availability" not in payload:
            raise ValueError(
                "provider availability record requires provider_id and availability"
            )
        return cls(
            provider_id=payload["provider_id"],
            availability=payload["availability"],
            resume_after=payload.get("resume_after"),
            last_error=payload.get("last_error"),
        )


@dataclass(frozen=True, slots=True)
class ProviderAvailabilityState:
    records: tuple[ProviderAvailabilityRecord, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                f"unsupported provider availability schema_version: {self.schema_version}"
            )

        raw = self.records
        if not isinstance(raw, tuple):
            try:
                raw = tuple(raw)
            except TypeError as exc:
                raise ValueError(
                    "records must be an iterable of ProviderAvailabilityRecord"
                ) from exc

        seen: set[str] = set()
        normalized: list[ProviderAvailabilityRecord] = []
        for record in raw:
            if not isinstance(record, ProviderAvailabilityRecord):
                raise ValueError(
                    "records must contain ProviderAvailabilityRecord values"
                )
            if record.provider_id in seen:
                raise ValueError(
                    f"duplicate provider availability record: {record.provider_id}"
                )
            seen.add(record.provider_id)
            normalized.append(record)

        normalized.sort(key=lambda item: item.provider_id)
        object.__setattr__(self, "records", tuple(normalized))

    def get(self, provider_id: str) -> ProviderAvailabilityRecord | None:
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        for record in self.records:
            if record.provider_id == provider_id:
                return record
        return None

    def upsert(
        self,
        record: ProviderAvailabilityRecord,
    ) -> "ProviderAvailabilityState":
        if not isinstance(record, ProviderAvailabilityRecord):
            raise ValueError("record must be a ProviderAvailabilityRecord")
        updated = [
            current
            for current in self.records
            if current.provider_id != record.provider_id
        ]
        updated.append(record)
        return ProviderAvailabilityState(
            records=tuple(updated),
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ProviderAvailabilityState":
        if not isinstance(payload, dict):
            raise ValueError(
                "provider availability state must be a JSON object"
            )
        if payload.get("schema_version") != 1:
            raise ValueError(
                "provider availability state schema_version must be 1"
            )
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError(
                "provider availability state records must be a list"
            )
        return cls(
            records=tuple(
                ProviderAvailabilityRecord.from_dict(item)
                for item in records
            ),
            schema_version=1,
        )


def evaluate_availability(
    record: ProviderAvailabilityRecord,
    *,
    now: datetime,
) -> ProviderAvailabilitySnapshot:
    if not isinstance(record, ProviderAvailabilityRecord):
        raise ValueError("record must be a ProviderAvailabilityRecord")
    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    if record.availability in {
        ProviderAvailability.QUOTA_PAUSED,
        ProviderAvailability.TEMPORARILY_UNAVAILABLE,
    }:
        assert record.resume_after is not None
        due = _parse_timestamp(record.resume_after, field="resume_after")
        if now.astimezone(UTC) >= due:
            return ProviderAvailabilitySnapshot(
                provider_id=record.provider_id,
                availability=ProviderAvailability.AVAILABLE,
                reason="cooldown expired",
            )

    return ProviderAvailabilitySnapshot(
        provider_id=record.provider_id,
        availability=record.availability,
        reason=record.last_error,
    )


def evaluate_state(
    state: ProviderAvailabilityState,
    *,
    now: datetime,
) -> tuple[ProviderAvailabilitySnapshot, ...]:
    if not isinstance(state, ProviderAvailabilityState):
        raise ValueError("state must be a ProviderAvailabilityState")
    return tuple(
        evaluate_availability(record, now=now)
        for record in state.records
    )
