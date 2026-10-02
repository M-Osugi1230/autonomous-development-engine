from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .autonomous_backlog import (
    BacklogCandidate,
    BacklogCandidateKind,
    build_candidate_id,
)
from .development_memory import (
    DevelopmentMemoryRecord,
    MemoryKind,
)
from .improvement_signal import (
    ImprovementSignal,
    ImprovementSignalKind,
)
from .improvement_signal_ledger import (
    ImprovementSignalLedger,
)
from .improvement_signal_resolution import (
    ImprovementResolutionState,
    ImprovementSignalResolution,
)


class ImprovementBridgeError(ValueError):
    """Continuous Improvement Memory/Backlog bridge failed."""


_KIND_TO_BACKLOG: dict[
    ImprovementSignalKind,
    BacklogCandidateKind,
] = {
    ImprovementSignalKind.RUNTIME_GAP: (
        BacklogCandidateKind.RUNTIME_GAP
    ),
    ImprovementSignalKind.RELIABILITY_GAP: (
        BacklogCandidateKind.VERIFIED_REMEDIATION
    ),
    ImprovementSignalKind.QUALITY_GAP: (
        BacklogCandidateKind.VERIFIED_REMEDIATION
    ),
    ImprovementSignalKind.PERFORMANCE_GAP: (
        BacklogCandidateKind.VERIFIED_REMEDIATION
    ),
    ImprovementSignalKind.OPERABILITY_GAP: (
        BacklogCandidateKind.REPOSITORY_HYGIENE
    ),
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


def _memory_id(
    *,
    signal: ImprovementSignal,
    resolution: ImprovementSignalResolution,
) -> str:
    digest = _fingerprint(
        {
            "signal_id": signal.signal_id,
            "signal_fingerprint": signal.fingerprint(),
            "resolution_fingerprint": resolution.fingerprint(),
            "bridge": "continuous-improvement-v1",
        }
    )
    return "mem-" + digest[:24]


def _evidence(
    *,
    signal: ImprovementSignal,
    resolution: ImprovementSignalResolution,
    signal_path: str,
    resolution_path: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    paths = (
        signal_path,
        resolution_path,
        *tuple(ref.path for ref in signal.evidence_refs),
    )
    fingerprints = (
        signal.fingerprint(),
        resolution.fingerprint(),
        *tuple(
            ref.fingerprint for ref in signal.evidence_refs
        ),
    )
    # DevelopmentMemoryRecord/BacklogCandidate both normalize and bound these
    # values. Keep bridge output at or below their shared budget.
    if len(set(paths)) > 8 or len(set(fingerprints)) > 8:
        raise ImprovementBridgeError(
            "improvement bridge evidence exceeds trusted budget"
        )
    return tuple(paths), tuple(fingerprints)


@dataclass(frozen=True, slots=True)
class ImprovementBridgeBundle:
    signal_id: str
    signal_fingerprint: str
    resolution_fingerprint: str
    memory_record: DevelopmentMemoryRecord
    backlog_candidate: BacklogCandidate
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementBridgeError(
                "unsupported improvement bridge schema version"
            )
        if (
            not isinstance(self.signal_id, str)
            or not self.signal_id
        ):
            raise ImprovementBridgeError(
                "signal_id must be non-empty"
            )
        for field, value in (
            ("signal_fingerprint", self.signal_fingerprint),
            (
                "resolution_fingerprint",
                self.resolution_fingerprint,
            ),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    char not in "0123456789abcdef"
                    for char in value
                )
            ):
                raise ImprovementBridgeError(
                    f"{field} must be sha256"
                )
        if not isinstance(
            self.memory_record,
            DevelopmentMemoryRecord,
        ):
            raise ImprovementBridgeError(
                "memory_record must be DevelopmentMemoryRecord"
            )
        if not isinstance(
            self.backlog_candidate,
            BacklogCandidate,
        ):
            raise ImprovementBridgeError(
                "backlog_candidate must be BacklogCandidate"
            )
        if (
            self.memory_record.repository
            != self.backlog_candidate.repository
            or self.memory_record.source_sha
            != self.backlog_candidate.source_sha
        ):
            raise ImprovementBridgeError(
                "bridge memory/backlog identity drift"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "signal_id": self.signal_id,
            "signal_fingerprint": self.signal_fingerprint,
            "resolution_fingerprint": (
                self.resolution_fingerprint
            ),
            "memory_record": (
                self.memory_record.canonical_dict()
            ),
            "backlog_candidate": (
                self.backlog_candidate.canonical_dict()
            ),
            "memory_authority": "advisory-data-only",
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
            "selection_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def build_improvement_memory_backlog_bridge(
    *,
    ledger: ImprovementSignalLedger,
    resolution: ImprovementSignalResolution,
    signal_id: str,
    signal_path: str,
    resolution_path: str,
) -> ImprovementBridgeBundle:
    if not isinstance(ledger, ImprovementSignalLedger):
        raise ImprovementBridgeError(
            "ledger must be ImprovementSignalLedger"
        )
    if not isinstance(
        resolution,
        ImprovementSignalResolution,
    ):
        raise ImprovementBridgeError(
            "resolution must be ImprovementSignalResolution"
        )
    if resolution.ledger_fingerprint != ledger.fingerprint():
        raise ImprovementBridgeError(
            "resolution does not bind supplied signal ledger"
        )

    signal = ledger.signal_for(signal_id)
    entry = resolution.entry_for(signal_id)
    if entry.state is not ImprovementResolutionState.CURRENT:
        raise ImprovementBridgeError(
            "only CURRENT improvement signal can enter Memory/Backlog bridge"
        )
    if signal.kind is ImprovementSignalKind.RELEASE_FOLLOWUP:
        raise ImprovementBridgeError(
            "observation-only release follow-up cannot enter Memory/Backlog bridge"
        )
    backlog_kind = _KIND_TO_BACKLOG.get(signal.kind)
    if backlog_kind is None:
        raise ImprovementBridgeError(
            "improvement signal kind has no trusted backlog mapping"
        )

    paths, fingerprints = _evidence(
        signal=signal,
        resolution=resolution,
        signal_path=signal_path,
        resolution_path=resolution_path,
    )
    kind_tag = signal.kind.value.casefold().replace("_", "-")
    memory = DevelopmentMemoryRecord(
        memory_id=_memory_id(
            signal=signal,
            resolution=resolution,
        ),
        kind=MemoryKind.REMEDIATION,
        repository=signal.repository,
        source_sha=signal.source_sha,
        statement=(
            "Trusted Continuous Improvement signal "
            + signal.signal_id
            + " is CURRENT after verified release evidence; "
            "retain it as advisory remediation context."
        ),
        evidence_paths=paths,
        evidence_fingerprints=fingerprints,
        tags=(
            "continuous-improvement",
            "current",
            kind_tag,
            "release",
            "verified",
        ),
    )

    backlog_statement = (
        "Resolve trusted Continuous Improvement signal "
        + signal.signal_id
        + ": "
        + signal.statement
    )
    candidate_id = build_candidate_id(
        kind=backlog_kind,
        repository=signal.repository,
        source_sha=signal.source_sha,
        statement=backlog_statement,
        evidence_fingerprints=(
            *fingerprints,
            memory.fingerprint(),
        ),
    )
    backlog = BacklogCandidate(
        candidate_id=candidate_id,
        kind=backlog_kind,
        repository=signal.repository,
        source_sha=signal.source_sha,
        statement=backlog_statement,
        evidence_paths=paths,
        evidence_fingerprints=(
            *fingerprints,
            memory.fingerprint(),
        ),
        tags=(
            "continuous-improvement",
            "current",
            kind_tag,
            "memory",
            "verified",
        ),
        source_phase="v1.9-continuous-improvement",
        human_only=False,
    )

    return ImprovementBridgeBundle(
        signal_id=signal.signal_id,
        signal_fingerprint=signal.fingerprint(),
        resolution_fingerprint=resolution.fingerprint(),
        memory_record=memory,
        backlog_candidate=backlog,
    )
