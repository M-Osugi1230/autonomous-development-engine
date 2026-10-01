from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .improvement_signal import (
    ImprovementSignal,
    ImprovementSignalError,
    MAX_IMPROVEMENT_GENERATION,
)


MAX_IMPROVEMENT_SIGNALS = 500


class ImprovementSignalLedgerError(ValueError):
    """Continuous Improvement signal-ledger validation failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _same_release_identity(
    parent: ImprovementSignal,
    child: ImprovementSignal,
) -> bool:
    return (
        parent.repository == child.repository
        and parent.source_sha == child.source_sha
        and parent.release_candidate_id
        == child.release_candidate_id
        and parent.release_environment
        == child.release_environment
    )


@dataclass(frozen=True, slots=True)
class ImprovementSignalLedger:
    signals: tuple[ImprovementSignal, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalLedgerError(
                "unsupported improvement signal ledger schema version"
            )
        if len(self.signals) > MAX_IMPROVEMENT_SIGNALS:
            raise ImprovementSignalLedgerError(
                "improvement signal ledger budget exceeded"
            )

        by_id: dict[str, ImprovementSignal] = {}
        for signal in self.signals:
            if not isinstance(signal, ImprovementSignal):
                raise ImprovementSignalLedgerError(
                    "ledger contains an invalid improvement signal"
                )
            existing = by_id.get(signal.signal_id)
            if existing is not None:
                if existing.canonical_dict() != signal.canonical_dict():
                    raise ImprovementSignalLedgerError(
                        "same signal_id cannot refer to different content"
                    )
                raise ImprovementSignalLedgerError(
                    f"duplicate improvement signal id: {signal.signal_id}"
                )
            by_id[signal.signal_id] = signal

        for signal in by_id.values():
            parent_id = signal.parent_signal_id
            if parent_id is None:
                continue
            parent = by_id.get(parent_id)
            if parent is None:
                raise ImprovementSignalLedgerError(
                    "successor improvement signal parent is absent from ledger"
                )
            if not _same_release_identity(parent, signal):
                raise ImprovementSignalLedgerError(
                    "cross-release improvement lineage is forbidden"
                )
            if signal.generation != parent.generation + 1:
                raise ImprovementSignalLedgerError(
                    "improvement lineage generation must advance by one"
                )
            if signal.generation > MAX_IMPROVEMENT_GENERATION:
                raise ImprovementSignalLedgerError(
                    "improvement lineage exceeds signal generation budget"
                )

        object.__setattr__(
            self,
            "signals",
            tuple(
                sorted(
                    by_id.values(),
                    key=lambda signal: (
                        signal.repository,
                        signal.release_candidate_id,
                        signal.release_environment,
                        signal.generation,
                        signal.kind.value,
                        signal.signal_id,
                    ),
                )
            ),
        )

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "signal_count": self.signal_count,
            "signals": [
                signal.canonical_dict()
                for signal in self.signals
            ],
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
            "release_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    def append(
        self,
        signal: ImprovementSignal,
    ) -> "ImprovementSignalLedger":
        if not isinstance(signal, ImprovementSignal):
            raise ImprovementSignalLedgerError(
                "signal must be ImprovementSignal"
            )
        for existing in self.signals:
            if existing.signal_id != signal.signal_id:
                continue
            if existing.canonical_dict() != signal.canonical_dict():
                raise ImprovementSignalLedgerError(
                    "same signal_id cannot refer to different content"
                )
            return self
        return ImprovementSignalLedger(
            signals=(*self.signals, signal)
        )

    def signal_for(self, signal_id: str) -> ImprovementSignal:
        matches = [
            signal
            for signal in self.signals
            if signal.signal_id == signal_id
        ]
        if len(matches) != 1:
            raise ImprovementSignalLedgerError(
                "improvement signal is missing or duplicated"
            )
        return matches[0]

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ImprovementSignalLedger":
        if not isinstance(payload, dict):
            raise ImprovementSignalLedgerError(
                "improvement signal ledger must be a JSON object"
            )
        allowed = {
            "schema_version",
            "signal_count",
            "signals",
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ImprovementSignalLedgerError(
                "unknown improvement signal ledger fields: "
                + str(sorted(unknown))
            )
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
        ):
            if payload.get(field, False) is not False:
                raise ImprovementSignalLedgerError(
                    "improvement signal ledger cannot grant "
                    + field.replace("_", " ")
                )
        raw_signals = payload.get("signals")
        if not isinstance(raw_signals, list):
            raise ImprovementSignalLedgerError(
                "signals must be a list"
            )
        try:
            ledger = cls(
                schema_version=payload.get("schema_version", 0),
                signals=tuple(
                    ImprovementSignal.from_dict(item)
                    for item in raw_signals
                ),
            )
        except ImprovementSignalError as exc:
            raise ImprovementSignalLedgerError(
                "improvement signal ledger contains invalid signal"
            ) from exc
        if payload.get("signal_count") != ledger.signal_count:
            raise ImprovementSignalLedgerError(
                "improvement signal_count drift"
            )
        return ledger
