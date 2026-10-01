from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any

from .improvement_signal import (
    ImprovementSignal,
    ImprovementSignalKind,
)
from .improvement_signal_ledger import (
    ImprovementSignalLedger,
    ImprovementSignalLedgerError,
)


class ImprovementSignalResolutionError(ValueError):
    """Continuous Improvement signal resolution failed."""


class ImprovementResolutionState(StrEnum):
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    COOLDOWN = "COOLDOWN"
    CYCLE_LIMIT = "CYCLE_LIMIT"
    CONFLICTED = "CONFLICTED"


class ImprovementResolutionReason(StrEnum):
    VERIFIED_RELEASE_OBSERVATION = "VERIFIED_RELEASE_OBSERVATION"
    ACTIONABLE_GAP = "ACTIONABLE_GAP"
    LINEAGE_ADVANCED = "LINEAGE_ADVANCED"
    ONE_PER_RELEASE_BUDGET = "ONE_PER_RELEASE_BUDGET"
    GENERATION_LIMIT = "GENERATION_LIMIT"
    LINEAGE_BRANCH_CONFLICT = "LINEAGE_BRANCH_CONFLICT"


_PRIORITY_BY_KIND: dict[ImprovementSignalKind, int] = {
    ImprovementSignalKind.RUNTIME_GAP: 10,
    ImprovementSignalKind.RELIABILITY_GAP: 20,
    ImprovementSignalKind.QUALITY_GAP: 30,
    ImprovementSignalKind.PERFORMANCE_GAP: 40,
    ImprovementSignalKind.OPERABILITY_GAP: 50,
    ImprovementSignalKind.RELEASE_FOLLOWUP: 100,
}


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


def signal_priority(signal: ImprovementSignal) -> int:
    if not isinstance(signal, ImprovementSignal):
        raise ImprovementSignalResolutionError(
            "signal must be ImprovementSignal"
        )
    return _PRIORITY_BY_KIND[signal.kind]


@dataclass(frozen=True, slots=True)
class ImprovementResolutionPolicy:
    max_generation: int = 4
    max_current_per_release: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalResolutionError(
                "unsupported improvement resolution policy version"
            )
        if type(self.max_generation) is not int or not (
            0 <= self.max_generation <= 16
        ):
            raise ImprovementSignalResolutionError(
                "max_generation must be between 0 and 16"
            )
        if self.max_current_per_release != 1:
            raise ImprovementSignalResolutionError(
                "current safety policy allows exactly one current signal per release"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "max_generation": self.max_generation,
            "max_current_per_release": 1,
            "priority_source": "controller-improvement-kind-policy-v1",
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ImprovementResolutionEntry:
    signal_id: str
    state: ImprovementResolutionState
    reason: ImprovementResolutionReason
    priority_rank: int
    generation: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalResolutionError(
                "unsupported improvement resolution entry version"
            )
        if not isinstance(self.signal_id, str) or not self.signal_id:
            raise ImprovementSignalResolutionError(
                "signal_id must be non-empty"
            )
        if not isinstance(self.state, ImprovementResolutionState):
            raise ImprovementSignalResolutionError(
                "resolution state is invalid"
            )
        if not isinstance(self.reason, ImprovementResolutionReason):
            raise ImprovementSignalResolutionError(
                "resolution reason is invalid"
            )
        if self.priority_rank not in set(_PRIORITY_BY_KIND.values()):
            raise ImprovementSignalResolutionError(
                "priority rank is not controller-owned"
            )
        if type(self.generation) is not int or self.generation < 0:
            raise ImprovementSignalResolutionError(
                "generation must be non-negative"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "signal_id": self.signal_id,
            "state": self.state.value,
            "reason": self.reason.value,
            "priority_rank": self.priority_rank,
            "generation": self.generation,
            "priority_source": "controller-improvement-kind-policy-v1",
        }


@dataclass(frozen=True, slots=True)
class ImprovementSignalResolution:
    ledger_fingerprint: str
    policy_fingerprint: str
    entries: tuple[ImprovementResolutionEntry, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalResolutionError(
                "unsupported improvement resolution version"
            )
        for field, value in (
            ("ledger_fingerprint", self.ledger_fingerprint),
            ("policy_fingerprint", self.policy_fingerprint),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ImprovementSignalResolutionError(
                    f"{field} must be sha256"
                )
        ids: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, ImprovementResolutionEntry):
                raise ImprovementSignalResolutionError(
                    "resolution contains invalid entry"
                )
            if entry.signal_id in ids:
                raise ImprovementSignalResolutionError(
                    "resolution contains duplicate signal entry"
                )
            ids.add(entry.signal_id)
        object.__setattr__(
            self,
            "entries",
            tuple(
                sorted(
                    self.entries,
                    key=lambda entry: entry.signal_id,
                )
            ),
        )

    @property
    def current_signal_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.signal_id
            for entry in self.entries
            if entry.state is ImprovementResolutionState.CURRENT
        )

    def entry_for(
        self,
        signal_id: str,
    ) -> ImprovementResolutionEntry:
        matches = [
            entry
            for entry in self.entries
            if entry.signal_id == signal_id
        ]
        if len(matches) != 1:
            raise ImprovementSignalResolutionError(
                "signal resolution is missing or duplicated"
            )
        return matches[0]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ledger_fingerprint": self.ledger_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "entries": [
                entry.canonical_dict()
                for entry in self.entries
            ],
            "current_signal_ids": list(
                self.current_signal_ids
            ),
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def _release_key(
    signal: ImprovementSignal,
) -> tuple[str, str, str, str]:
    return (
        signal.repository,
        signal.source_sha,
        signal.release_candidate_id,
        signal.release_environment,
    )


def resolve_improvement_signals(
    ledger: ImprovementSignalLedger,
    *,
    policy: ImprovementResolutionPolicy | None = None,
) -> ImprovementSignalResolution:
    if not isinstance(ledger, ImprovementSignalLedger):
        raise ImprovementSignalResolutionError(
            "ledger must be ImprovementSignalLedger"
        )
    policy = policy or ImprovementResolutionPolicy()
    if not isinstance(policy, ImprovementResolutionPolicy):
        raise ImprovementSignalResolutionError(
            "policy must be ImprovementResolutionPolicy"
        )

    signals = {
        signal.signal_id: signal
        for signal in ledger.signals
    }
    children_by_parent: dict[str, list[ImprovementSignal]] = {}
    for signal in ledger.signals:
        if signal.parent_signal_id is not None:
            children_by_parent.setdefault(
                signal.parent_signal_id,
                [],
            ).append(signal)

    state_by_id: dict[
        str,
        tuple[
            ImprovementResolutionState,
            ImprovementResolutionReason,
        ],
    ] = {}

    for signal in ledger.signals:
        if signal.generation > policy.max_generation:
            state_by_id[signal.signal_id] = (
                ImprovementResolutionState.CYCLE_LIMIT,
                ImprovementResolutionReason.GENERATION_LIMIT,
            )

    for parent_id, children in children_by_parent.items():
        active_children = [
            child
            for child in children
            if child.signal_id not in state_by_id
        ]
        if len(active_children) > 1:
            for child in active_children:
                state_by_id[child.signal_id] = (
                    ImprovementResolutionState.CONFLICTED,
                    ImprovementResolutionReason.LINEAGE_BRANCH_CONFLICT,
                )
            continue
        if len(active_children) == 1:
            parent = signals[parent_id]
            if parent.signal_id not in state_by_id:
                state_by_id[parent.signal_id] = (
                    ImprovementResolutionState.SUPERSEDED,
                    ImprovementResolutionReason.LINEAGE_ADVANCED,
                )

    for signal in ledger.signals:
        if signal.signal_id in state_by_id:
            continue
        if signal.kind is ImprovementSignalKind.RELEASE_FOLLOWUP:
            state_by_id[signal.signal_id] = (
                ImprovementResolutionState.OBSERVATION_ONLY,
                ImprovementResolutionReason.VERIFIED_RELEASE_OBSERVATION,
            )

    actionable_by_release: dict[
        tuple[str, str, str, str],
        list[ImprovementSignal],
    ] = {}
    for signal in ledger.signals:
        if signal.signal_id in state_by_id:
            continue
        actionable_by_release.setdefault(
            _release_key(signal),
            [],
        ).append(signal)

    for group in actionable_by_release.values():
        ranked = sorted(
            group,
            key=lambda signal: (
                signal_priority(signal),
                signal.generation,
                signal.signal_id,
            ),
        )
        for index, signal in enumerate(ranked):
            if index < policy.max_current_per_release:
                state_by_id[signal.signal_id] = (
                    ImprovementResolutionState.CURRENT,
                    ImprovementResolutionReason.ACTIONABLE_GAP,
                )
            else:
                state_by_id[signal.signal_id] = (
                    ImprovementResolutionState.COOLDOWN,
                    ImprovementResolutionReason.ONE_PER_RELEASE_BUDGET,
                )

    entries = tuple(
        ImprovementResolutionEntry(
            signal_id=signal.signal_id,
            state=state_by_id[signal.signal_id][0],
            reason=state_by_id[signal.signal_id][1],
            priority_rank=signal_priority(signal),
            generation=signal.generation,
        )
        for signal in ledger.signals
    )
    return ImprovementSignalResolution(
        ledger_fingerprint=ledger.fingerprint(),
        policy_fingerprint=policy.fingerprint(),
        entries=entries,
    )
