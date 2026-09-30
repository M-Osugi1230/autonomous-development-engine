from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping

from .autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
)
from .autonomous_backlog_feedback import BacklogRetirementRecord


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


class BacklogResolutionState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"
    RETIRED = "RETIRED"


class BacklogResolutionReason(StrEnum):
    CURRENT_SOURCE = "CURRENT_SOURCE"
    SOURCE_SHA_ADVANCED = "SOURCE_SHA_ADVANCED"
    EXPLICIT_SUPERSESSION = "EXPLICIT_SUPERSESSION"
    SEMANTIC_DUPLICATE = "SEMANTIC_DUPLICATE"
    SUBJECT_CONFLICT = "SUBJECT_CONFLICT"
    VERIFIED_COMPLETION = "VERIFIED_COMPLETION"


_PRIORITY_BY_KIND: dict[BacklogCandidateKind, int] = {
    BacklogCandidateKind.RUNTIME_GAP: 10,
    BacklogCandidateKind.ACCEPTANCE_GAP: 20,
    BacklogCandidateKind.VERIFIED_REMEDIATION: 30,
    BacklogCandidateKind.REPOSITORY_HYGIENE: 40,
    BacklogCandidateKind.MEMORY_FOLLOWUP: 50,
}


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _candidate_id(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise AutonomousBacklogError("supersession candidate id is invalid")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AutonomousBacklogError("current source SHA is invalid")
    return value


def _evidence_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(".autodev/")
        or value.startswith("/")
        or "\\" in value
        or ".." in value.split("/")
    ):
        raise AutonomousBacklogError("supersession evidence path is unsafe")
    return value


def _evidence_fingerprint(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AutonomousBacklogError("supersession evidence fingerprint must be sha256")
    return value


@dataclass(frozen=True, slots=True)
class BacklogSupersession:
    prior_candidate_id: str
    successor_candidate_id: str
    evidence_path: str
    evidence_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported supersession schema version")
        object.__setattr__(
            self,
            "prior_candidate_id",
            _candidate_id(self.prior_candidate_id),
        )
        object.__setattr__(
            self,
            "successor_candidate_id",
            _candidate_id(self.successor_candidate_id),
        )
        if self.prior_candidate_id == self.successor_candidate_id:
            raise AutonomousBacklogError("candidate cannot supersede itself")
        object.__setattr__(self, "evidence_path", _evidence_path(self.evidence_path))
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _evidence_fingerprint(self.evidence_fingerprint),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "prior_candidate_id": self.prior_candidate_id,
            "successor_candidate_id": self.successor_candidate_id,
            "evidence_path": self.evidence_path,
            "evidence_fingerprint": self.evidence_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class BacklogResolutionEntry:
    candidate_id: str
    state: BacklogResolutionState
    reason: BacklogResolutionReason
    priority_rank: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported resolution entry schema version")
        object.__setattr__(self, "candidate_id", _candidate_id(self.candidate_id))
        if not isinstance(self.state, BacklogResolutionState):
            raise AutonomousBacklogError("resolution state is invalid")
        if not isinstance(self.reason, BacklogResolutionReason):
            raise AutonomousBacklogError("resolution reason is invalid")
        if type(self.priority_rank) is not int or self.priority_rank not in set(
            _PRIORITY_BY_KIND.values()
        ):
            raise AutonomousBacklogError("priority rank is not controller-owned")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "reason": self.reason.value,
            "priority_rank": self.priority_rank,
            "priority_source": "controller-kind-policy-v1",
        }


@dataclass(frozen=True, slots=True)
class AutonomousBacklogResolution:
    backlog_fingerprint: str
    current_sources: tuple[tuple[str, str], ...]
    supersessions: tuple[BacklogSupersession, ...]
    entries: tuple[BacklogResolutionEntry, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported resolution schema version")
        if not isinstance(self.backlog_fingerprint, str) or _SHA256.fullmatch(
            self.backlog_fingerprint
        ) is None:
            raise AutonomousBacklogError("backlog fingerprint must be sha256")
        object.__setattr__(self, "current_sources", tuple(sorted(self.current_sources)))
        object.__setattr__(
            self,
            "supersessions",
            tuple(
                sorted(
                    self.supersessions,
                    key=lambda item: (
                        item.prior_candidate_id,
                        item.successor_candidate_id,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda item: item.candidate_id)),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "backlog_fingerprint": self.backlog_fingerprint,
            "current_sources": [
                {"repository": repository, "source_sha": source_sha}
                for repository, source_sha in self.current_sources
            ],
            "supersessions": [item.canonical_dict() for item in self.supersessions],
            "entries": [entry.canonical_dict() for entry in self.entries],
            "priority_policy": "controller-kind-policy-v1",
            "execution_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    def entry_for(self, candidate_id: str) -> BacklogResolutionEntry:
        candidate_id = _candidate_id(candidate_id)
        matches = [entry for entry in self.entries if entry.candidate_id == candidate_id]
        if len(matches) != 1:
            raise AutonomousBacklogError("candidate resolution is missing or duplicated")
        return matches[0]


def candidate_priority(candidate: BacklogCandidate) -> int:
    if not isinstance(candidate, BacklogCandidate):
        raise AutonomousBacklogError("candidate must be BacklogCandidate")
    return _PRIORITY_BY_KIND[candidate.kind]


def _validate_current_sources(
    backlog: AutonomousBacklog,
    current_sources: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(current_sources, Mapping):
        raise AutonomousBacklogError("current_sources must be a mapping")
    repositories = {candidate.repository for candidate in backlog.candidates}
    if set(current_sources) != repositories:
        raise AutonomousBacklogError(
            "current_sources must bind every and only backlog repository"
        )
    return tuple(
        sorted((repository, _sha(source_sha)) for repository, source_sha in current_sources.items())
    )


def _validated_supersessions(
    backlog: AutonomousBacklog,
    supersessions: tuple[BacklogSupersession, ...],
) -> tuple[BacklogSupersession, ...]:
    candidates = {candidate.candidate_id: candidate for candidate in backlog.candidates}
    successor_by_prior: dict[str, str] = {}
    incoming: dict[str, str] = {}
    for link in supersessions:
        if not isinstance(link, BacklogSupersession):
            raise AutonomousBacklogError("supersession must be BacklogSupersession")
        if link.prior_candidate_id not in candidates or link.successor_candidate_id not in candidates:
            raise AutonomousBacklogError("supersession references an unknown candidate")
        prior = candidates[link.prior_candidate_id]
        successor = candidates[link.successor_candidate_id]
        if prior.repository != successor.repository:
            raise AutonomousBacklogError("cross-repository supersession is forbidden")
        existing = successor_by_prior.get(link.prior_candidate_id)
        if existing is not None and existing != link.successor_candidate_id:
            raise AutonomousBacklogError("candidate cannot have multiple successors")
        previous = incoming.get(link.successor_candidate_id)
        if previous is not None and previous != link.prior_candidate_id:
            raise AutonomousBacklogError("candidate cannot supersede multiple prior candidates")
        successor_by_prior[link.prior_candidate_id] = link.successor_candidate_id
        incoming[link.successor_candidate_id] = link.prior_candidate_id

    for start in successor_by_prior:
        seen: set[str] = set()
        current = start
        while current in successor_by_prior:
            if current in seen:
                raise AutonomousBacklogError("supersession cycle detected")
            seen.add(current)
            current = successor_by_prior[current]
    return tuple(supersessions)


def _validated_retirements(
    backlog: AutonomousBacklog,
    retirements: tuple[BacklogRetirementRecord, ...],
) -> tuple[BacklogRetirementRecord, ...]:
    candidates = {candidate.candidate_id: candidate for candidate in backlog.candidates}
    by_candidate: dict[str, BacklogRetirementRecord] = {}
    for retirement in retirements:
        if not isinstance(retirement, BacklogRetirementRecord):
            raise AutonomousBacklogError(
                "retirement must be BacklogRetirementRecord"
            )
        candidate = candidates.get(retirement.candidate_id)
        if candidate is None:
            raise AutonomousBacklogError(
                "retirement references an unknown candidate"
            )
        if retirement.candidate_id in by_candidate:
            raise AutonomousBacklogError(
                "candidate cannot have multiple retirement records"
            )
        if retirement.candidate_fingerprint != candidate.fingerprint():
            raise AutonomousBacklogError(
                "retirement candidate fingerprint does not match backlog"
            )
        if retirement.repository != candidate.repository:
            raise AutonomousBacklogError(
                "retirement repository does not match candidate"
            )
        if retirement.original_source_sha != candidate.source_sha:
            raise AutonomousBacklogError(
                "retirement original source SHA does not match candidate"
            )
        by_candidate[retirement.candidate_id] = retirement
    return tuple(
        sorted(
            by_candidate.values(),
            key=lambda item: (item.candidate_id, item.retirement_id),
        )
    )


def _subject(candidate: BacklogCandidate) -> tuple[object, ...]:
    return (
        candidate.repository,
        candidate.source_sha,
        candidate.kind.value,
        candidate.tags,
        candidate.human_only,
    )


def resolve_autonomous_backlog(
    backlog: AutonomousBacklog,
    *,
    current_sources: Mapping[str, str],
    supersessions: tuple[BacklogSupersession, ...] = (),
    retirements: tuple[BacklogRetirementRecord, ...] = (),
) -> AutonomousBacklogResolution:
    if not isinstance(backlog, AutonomousBacklog):
        raise AutonomousBacklogError("backlog must be AutonomousBacklog")
    sources = _validate_current_sources(backlog, current_sources)
    source_map = dict(sources)
    links = _validated_supersessions(backlog, supersessions)
    retirement_records = _validated_retirements(backlog, retirements)
    explicit_prior_ids = {link.prior_candidate_id for link in links}
    retired_ids = {item.candidate_id for item in retirement_records}

    state_by_id: dict[str, tuple[BacklogResolutionState, BacklogResolutionReason]] = {}
    for candidate in backlog.candidates:
        if candidate.candidate_id in retired_ids:
            state_by_id[candidate.candidate_id] = (
                BacklogResolutionState.RETIRED,
                BacklogResolutionReason.VERIFIED_COMPLETION,
            )
        elif candidate.candidate_id in explicit_prior_ids:
            state_by_id[candidate.candidate_id] = (
                BacklogResolutionState.SUPERSEDED,
                BacklogResolutionReason.EXPLICIT_SUPERSESSION,
            )
        elif candidate.source_sha != source_map[candidate.repository]:
            state_by_id[candidate.candidate_id] = (
                BacklogResolutionState.STALE,
                BacklogResolutionReason.SOURCE_SHA_ADVANCED,
            )
        else:
            state_by_id[candidate.candidate_id] = (
                BacklogResolutionState.CURRENT,
                BacklogResolutionReason.CURRENT_SOURCE,
            )

    active_by_subject: dict[tuple[object, ...], list[BacklogCandidate]] = {}
    for candidate in backlog.candidates:
        if state_by_id[candidate.candidate_id][0] is BacklogResolutionState.CURRENT:
            active_by_subject.setdefault(_subject(candidate), []).append(candidate)

    for group in active_by_subject.values():
        if len(group) < 2:
            continue
        statements = {candidate.statement for candidate in group}
        if len(statements) > 1:
            for candidate in group:
                state_by_id[candidate.candidate_id] = (
                    BacklogResolutionState.CONFLICTED,
                    BacklogResolutionReason.SUBJECT_CONFLICT,
                )
            continue
        canonical = min(group, key=lambda candidate: candidate.candidate_id)
        for candidate in group:
            if candidate.candidate_id == canonical.candidate_id:
                continue
            state_by_id[candidate.candidate_id] = (
                BacklogResolutionState.SUPERSEDED,
                BacklogResolutionReason.SEMANTIC_DUPLICATE,
            )

    entries = tuple(
        BacklogResolutionEntry(
            candidate_id=candidate.candidate_id,
            state=state_by_id[candidate.candidate_id][0],
            reason=state_by_id[candidate.candidate_id][1],
            priority_rank=candidate_priority(candidate),
        )
        for candidate in backlog.candidates
    )
    return AutonomousBacklogResolution(
        backlog_fingerprint=backlog.fingerprint(),
        current_sources=sources,
        supersessions=links,
        entries=entries,
    )
