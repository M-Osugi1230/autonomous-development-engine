from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .pilot import PilotContract


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9_.@/-]{1,128}$")


def pilot_contract_fingerprint(contract: PilotContract) -> str:
    if not isinstance(contract, PilotContract):
        raise TypeError("contract must be a PilotContract")
    canonical = json.dumps(
        contract.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotActivation:
    pilot_id: str
    contract_fingerprint: str
    activated_by: str
    activated_at: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("pilot activation schema_version must be 1")
        if not isinstance(self.pilot_id, str) or not self.pilot_id.strip():
            raise ValueError("pilot_id must be a non-empty string")
        if (
            not isinstance(self.contract_fingerprint, str)
            or not _FINGERPRINT.fullmatch(self.contract_fingerprint)
        ):
            raise ValueError("contract_fingerprint must be a lowercase SHA-256 hex digest")
        if not isinstance(self.activated_by, str) or not _ACTOR.fullmatch(self.activated_by):
            raise ValueError(
                "activated_by must be a 1-128 character actor identifier"
            )
        if not isinstance(self.activated_at, str) or not self.activated_at.strip():
            raise ValueError("activated_at must be a timezone-aware ISO-8601 string")

        raw = self.activated_at.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "activated_at must be a timezone-aware ISO-8601 string"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("activated_at must include a timezone offset")
        normalized = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        object.__setattr__(self, "activated_at", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pilot_id": self.pilot_id,
            "contract_fingerprint": self.contract_fingerprint,
            "activated_by": self.activated_by,
            "activated_at": self.activated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotActivation":
        if not isinstance(payload, dict):
            raise ValueError("pilot activation must be a JSON object")
        required = {
            "schema_version",
            "pilot_id",
            "contract_fingerprint",
            "activated_by",
            "activated_at",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"pilot activation missing required keys: {sorted(missing)}")
        return cls(
            schema_version=payload["schema_version"],
            pilot_id=payload["pilot_id"],
            contract_fingerprint=payload["contract_fingerprint"],
            activated_by=payload["activated_by"],
            activated_at=payload["activated_at"],
        )


def build_pilot_activation(
    contract: PilotContract,
    *,
    activated_by: str,
    activated_at: str,
) -> PilotActivation:
    return PilotActivation(
        pilot_id=contract.pilot_id,
        contract_fingerprint=pilot_contract_fingerprint(contract),
        activated_by=activated_by,
        activated_at=activated_at,
    )


def pilot_target_writes_allowed(
    contract: PilotContract,
    activation: PilotActivation | None,
) -> bool:
    if not isinstance(contract, PilotContract):
        raise TypeError("contract must be a PilotContract")
    if not contract.safety.require_human_activation:
        return True
    if activation is None:
        return False
    if not isinstance(activation, PilotActivation):
        raise TypeError("activation must be a PilotActivation or None")
    return (
        activation.pilot_id == contract.pilot_id
        and activation.contract_fingerprint == pilot_contract_fingerprint(contract)
    )


def require_pilot_target_write_activation(
    contract: PilotContract,
    activation: PilotActivation | None,
) -> None:
    if pilot_target_writes_allowed(contract, activation):
        return
    if activation is None:
        raise PermissionError("production pilot target writes require human activation")
    raise PermissionError(
        "production pilot activation does not match the current pilot contract"
    )
