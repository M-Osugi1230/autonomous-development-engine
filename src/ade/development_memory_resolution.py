from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\\x00-\\x1f\\x7f]")


class MemoryResolutionStatus(str, Enum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"


class MemorySupersessionReason(str, Enum):
    CORRECTED = "CORRECTED"
    REPLACED_BY_NEWER_EVIDENCE = "REPLACED_BY_NEWER_EVIDENCE"
    RETIRED = "RETIRED"


def _validated_supersession_evidence_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise DevelopmentMemoryError("supersession evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise DevelopmentMemoryError("supersession evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise DevelopmentMemoryError("supersession evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise DevelopmentMemoryError(
            "supersession evidence path must remain inside .autodev/"
        )
    return value


def _validated_supersession_fingerprint(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentMemoryError(
            "supersession evidence fingerprint must be sha256"
        )
    return value


@dataclass(frozen=True, slots=True)
class MemorySupersession:
    superseded_memory_id: str
    successor_memory_id: str
    reason: MemorySupersessionReason
    evidence_path: str
    evidence_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.superseded_memory_id, str)
            or not self.superseded_memory_id
            or not isinstance(self.successor_memory_id, str)
            or not self.successor_memory_id
        ):
            raise DevelopmentMemoryError("supersession memory ids must be non-empty")
        if self.superseded_memory_id == self.successor_memory_id:
            raise DevelopmentMemoryError("memory cannot supersede itself")
        if not isinstance(self.reason, MemorySupersessionReason):
            raise DevelopmentMemoryError("supersession reason is invalid")
        object.__setattr__(
            self,
            "evidence_path",
            _validated_supersession_evidence_path(self.evidence_path),
        )
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _validated_supersession_fingerprint(self.evidence_fingerprint),
        )

    def canonical_dict(self) -> dict[str, str]:
        return {
            "superseded_memory_id": self.superseded_memory_id,
            "successor_memory_id": self.successor_memory_id,
            "reason": self.reason.value,
            "evidence_path": self.evidence_path,
            "evidence_fingerprint": self.evidence_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ResolvedMemoryRecord:
    record: DevelopmentMemoryRecord
    status: MemoryResolutionStatus
    reason: str

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.canonical_dict(),
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryResolution:
    records: tuple[ResolvedMemoryRecord, ...]
    supersessions: tuple[MemorySupersession, ...]
    current_source_shas: tuple[tuple[str, str], ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory resolution schema version")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "current_source_shas": [
                {"repository": repository, "source_sha": source_sha}
                for repository, source_sha in self.current_source_shas
            ],
            "supersessions": [
                item.canonical_dict() for item in self.supersessions
            ],
            "records": [item.canonical_dict() for item in self.records],
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def eligible_ledger(self) -> DevelopmentMemoryLedger:
        return DevelopmentMemoryLedger(
            records=tuple(
                item.record
                for item in self.records
                if item.status
                in {
                    MemoryResolutionStatus.CURRENT,
                    MemoryResolutionStatus.HISTORICAL,
                }
            )
        )

    @property
    def conflicted(self) -> tuple[ResolvedMemoryRecord, ...]:
        return tuple(
            item
            for item in self.records
            if item.status is MemoryResolutionStatus.CONFLICTED
        )


def _validate_current_sources(
    ledger: DevelopmentMemoryLedger,
    current_source_shas: dict[str, str],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(current_source_shas, dict):
        raise DevelopmentMemoryError("current_source_shas must be a dict")

    repositories = {record.repository for record in ledger.records}
    normalized: list[tuple[str, str]] = []
    for repository in sorted(repositories):
        sha = current_source_shas.get(repository)
        if not isinstance(sha, str) or _SHA40.fullmatch(sha) is None:
            raise DevelopmentMemoryError(
                f"missing or invalid current source SHA for {repository}"
            )
        normalized.append((repository, sha))

    unexpected = set(current_source_shas) - repositories
    if unexpected:
        raise DevelopmentMemoryError(
            "current_source_shas contains repositories absent from the ledger"
        )
    return tuple(normalized)


def _validate_supersessions(
    ledger: DevelopmentMemoryLedger,
    supersessions: Iterable[MemorySupersession],
) -> tuple[MemorySupersession, ...]:
    by_id = {record.memory_id: record for record in ledger.records}
    normalized = tuple(
        sorted(
            tuple(supersessions),
            key=lambda item: (
                item.superseded_memory_id,
                item.successor_memory_id,
                item.reason.value,
            ),
        )
    )
    seen_old: set[str] = set()
    edges: dict[str, str] = {}
    for item in normalized:
        if not isinstance(item, MemorySupersession):
            raise DevelopmentMemoryError(
                "supersessions must contain MemorySupersession values"
            )
        old = by_id.get(item.superseded_memory_id)
        new = by_id.get(item.successor_memory_id)
        if old is None or new is None:
            raise DevelopmentMemoryError(
                "supersession refers to memory outside the ledger"
            )
        if old.repository != new.repository:
            raise DevelopmentMemoryError(
                "supersession cannot cross repository boundaries"
            )
        if _subject_key(old) != _subject_key(new):
            raise DevelopmentMemoryError(
                "supersession cannot cross memory subjects"
            )
        if item.superseded_memory_id in seen_old:
            raise DevelopmentMemoryError(
                "one memory cannot have multiple supersession successors"
            )
        seen_old.add(item.superseded_memory_id)
        edges[item.superseded_memory_id] = item.successor_memory_id

    for start in edges:
        visited: set[str] = set()
        cursor = start
        while cursor in edges:
            if cursor in visited:
                raise DevelopmentMemoryError("supersession graph contains a cycle")
            visited.add(cursor)
            cursor = edges[cursor]

    return normalized


def _subject_key(
    record: DevelopmentMemoryRecord,
) -> tuple[str, str, tuple[str, ...], str | None, str | None]:
    return (
        record.repository,
        record.kind.value,
        record.tags,
        record.task_id,
        record.campaign_id,
    )


def resolve_development_memory(
    ledger: DevelopmentMemoryLedger,
    *,
    current_source_shas: dict[str, str],
    supersessions: Iterable[MemorySupersession] = (),
) -> DevelopmentMemoryResolution:
    if not isinstance(ledger, DevelopmentMemoryLedger):
        raise DevelopmentMemoryError("ledger must be DevelopmentMemoryLedger")

    current_sources = _validate_current_sources(ledger, current_source_shas)
    current_by_repo = dict(current_sources)
    normalized_supersessions = _validate_supersessions(ledger, supersessions)
    superseded_ids = {
        item.superseded_memory_id for item in normalized_supersessions
    }

    preliminary: dict[str, ResolvedMemoryRecord] = {}
    for record in ledger.records:
        if record.memory_id in superseded_ids:
            preliminary[record.memory_id] = ResolvedMemoryRecord(
                record=record,
                status=MemoryResolutionStatus.SUPERSEDED,
                reason="explicit trusted supersession",
            )
            continue

        if record.kind is MemoryKind.VERIFIED_OUTCOME:
            if record.source_sha != current_by_repo[record.repository]:
                preliminary[record.memory_id] = ResolvedMemoryRecord(
                    record=record,
                    status=MemoryResolutionStatus.STALE,
                    reason="verified outcome source SHA is not current",
                )
            else:
                preliminary[record.memory_id] = ResolvedMemoryRecord(
                    record=record,
                    status=MemoryResolutionStatus.CURRENT,
                    reason="verified outcome is bound to current source SHA",
                )
            continue

        preliminary[record.memory_id] = ResolvedMemoryRecord(
            record=record,
            status=MemoryResolutionStatus.HISTORICAL,
            reason="historical decision/failure/remediation lesson",
        )

    current_groups: dict[
        tuple[str, str, tuple[str, ...], str | None, str | None],
        list[ResolvedMemoryRecord],
    ] = {}
    for item in preliminary.values():
        if item.status is not MemoryResolutionStatus.CURRENT:
            continue
        current_groups.setdefault(_subject_key(item.record), []).append(item)

    conflicted_ids: set[str] = set()
    for group in current_groups.values():
        statements = {item.record.statement for item in group}
        if len(statements) <= 1:
            continue
        for item in group:
            conflicted_ids.add(item.record.memory_id)

    resolved = []
    for record in ledger.records:
        item = preliminary[record.memory_id]
        if record.memory_id in conflicted_ids:
            item = ResolvedMemoryRecord(
                record=record,
                status=MemoryResolutionStatus.CONFLICTED,
                reason=(
                    "multiple current verified memories share the same subject "
                    "but disagree on statement"
                ),
            )
        resolved.append(item)

    return DevelopmentMemoryResolution(
        records=tuple(resolved),
        supersessions=normalized_supersessions,
        current_source_shas=current_sources,
    )
