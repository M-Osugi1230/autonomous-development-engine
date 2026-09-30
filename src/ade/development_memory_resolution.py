from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
)


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class MemoryDisposition(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    CONFLICT = "CONFLICT"


class SupersessionReason(StrEnum):
    SOURCE_ADVANCED = "SOURCE_ADVANCED"
    CORRECTION = "CORRECTION"
    REMEDIATION_REPLACED = "REMEDIATION_REPLACED"
    DECISION_REPLACED = "DECISION_REPLACED"


def _evidence_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise DevelopmentMemoryError("supersession evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise DevelopmentMemoryError("supersession evidence path is unsafe")
    parsed = PurePosixPath(value)
    if "." in parsed.parts or ".." in parsed.parts or str(parsed) != value:
        raise DevelopmentMemoryError(
            "supersession evidence path must be normalized"
        )
    if not value.startswith(".autodev/"):
        raise DevelopmentMemoryError(
            "supersession evidence path must remain inside .autodev/"
        )
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentMemoryError(
            "supersession evidence fingerprint must be sha256"
        )
    return value


def _sha40(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise DevelopmentMemoryError(
            f"{field} must be a lowercase 40-char SHA"
        )
    return value


@dataclass(frozen=True, slots=True)
class MemorySupersessionRule:
    rule_id: str
    old_memory_id: str
    new_memory_id: str
    reason: SupersessionReason
    evidence_path: str
    evidence_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError(
                "unsupported memory supersession schema version"
            )
        if (
            not isinstance(self.rule_id, str)
            or _RULE_ID.fullmatch(self.rule_id) is None
        ):
            raise DevelopmentMemoryError("supersession rule_id is invalid")
        for field_name in ("old_memory_id", "new_memory_id"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or _RULE_ID.fullmatch(value) is None
            ):
                raise DevelopmentMemoryError(
                    f"supersession {field_name} is invalid"
                )
        if self.old_memory_id == self.new_memory_id:
            raise DevelopmentMemoryError(
                "memory cannot supersede itself"
            )
        try:
            reason = SupersessionReason(self.reason)
        except (TypeError, ValueError) as exc:
            raise DevelopmentMemoryError(
                "supersession reason is invalid"
            ) from exc
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "evidence_path",
            _evidence_path(self.evidence_path),
        )
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _sha256(self.evidence_fingerprint),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "rule_id": self.rule_id,
            "old_memory_id": self.old_memory_id,
            "new_memory_id": self.new_memory_id,
            "reason": self.reason.value,
            "evidence_path": self.evidence_path,
            "evidence_fingerprint": self.evidence_fingerprint,
        }


def memory_subject(record: DevelopmentMemoryRecord) -> str:
    if not isinstance(record, DevelopmentMemoryRecord):
        raise DevelopmentMemoryError(
            "memory subject requires DevelopmentMemoryRecord"
        )
    tags = set(record.tags)
    if "runtime" in tags:
        if record.task_id is None:
            raise DevelopmentMemoryError(
                "runtime memory requires task_id for conflict resolution"
            )
        return f"runtime:{record.task_id}"
    if "campaign" in tags:
        if record.campaign_id is None:
            raise DevelopmentMemoryError(
                "campaign memory requires campaign_id for conflict resolution"
            )
        return f"campaign:{record.campaign_id}"
    if "recovery" in tags:
        if record.task_id is None:
            raise DevelopmentMemoryError(
                "recovery memory requires task_id for conflict resolution"
            )
        return f"recovery:{record.task_id}"
    if "decision" in tags:
        if record.task_id is None:
            raise DevelopmentMemoryError(
                "decision memory requires task_id for conflict resolution"
            )
        return f"decision:{record.task_id}"
    if record.task_id is not None:
        return f"{record.kind.value.casefold()}:{record.task_id}"
    if record.campaign_id is not None:
        return f"{record.kind.value.casefold()}:{record.campaign_id}"
    return f"{record.kind.value.casefold()}:{record.memory_id}"


@dataclass(frozen=True, slots=True)
class MemoryResolutionEntry:
    memory_id: str
    repository: str
    subject: str
    disposition: MemoryDisposition
    source_sha: str
    superseded_by: str | None = None
    reason: str | None = None

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "repository": self.repository,
            "subject": self.subject,
            "disposition": self.disposition.value,
            "source_sha": self.source_sha,
            "superseded_by": self.superseded_by,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryResolution:
    entries: tuple[MemoryResolutionEntry, ...]
    active_records: tuple[DevelopmentMemoryRecord, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError(
                "unsupported memory resolution schema version"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "entries": [entry.canonical_dict() for entry in self.entries],
            "active_memory_ids": [
                record.memory_id for record in self.active_records
            ],
        }


def _validate_supersessions(
    *,
    records: Mapping[str, DevelopmentMemoryRecord],
    rules: tuple[MemorySupersessionRule, ...],
) -> dict[str, MemorySupersessionRule]:
    by_old: dict[str, MemorySupersessionRule] = {}
    rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, MemorySupersessionRule):
            raise DevelopmentMemoryError(
                "supersession rules must be MemorySupersessionRule"
            )
        if rule.rule_id in rule_ids:
            raise DevelopmentMemoryError(
                f"duplicate supersession rule_id: {rule.rule_id}"
            )
        rule_ids.add(rule.rule_id)
        if rule.old_memory_id in by_old:
            raise DevelopmentMemoryError(
                f"memory has multiple supersession targets: {rule.old_memory_id}"
            )
        old = records.get(rule.old_memory_id)
        new = records.get(rule.new_memory_id)
        if old is None or new is None:
            raise DevelopmentMemoryError(
                "supersession references unknown memory"
            )
        if old.repository != new.repository:
            raise DevelopmentMemoryError(
                "supersession cannot cross repositories"
            )
        if memory_subject(old) != memory_subject(new):
            raise DevelopmentMemoryError(
                "supersession cannot cross memory subjects"
            )
        by_old[rule.old_memory_id] = rule

    for start in by_old:
        seen: set[str] = set()
        cursor = start
        while cursor in by_old:
            if cursor in seen:
                raise DevelopmentMemoryError(
                    "memory supersession graph contains a cycle"
                )
            seen.add(cursor)
            cursor = by_old[cursor].new_memory_id
    return by_old


def resolve_development_memory(
    ledger: DevelopmentMemoryLedger,
    *,
    current_source_shas: Mapping[str, str],
    supersessions: tuple[MemorySupersessionRule, ...] = (),
) -> DevelopmentMemoryResolution:
    if not isinstance(ledger, DevelopmentMemoryLedger):
        raise DevelopmentMemoryError(
            "ledger must be DevelopmentMemoryLedger"
        )
    if not isinstance(current_source_shas, Mapping):
        raise DevelopmentMemoryError(
            "current_source_shas must be a mapping"
        )

    repositories = {record.repository for record in ledger.records}
    normalized_current: dict[str, str] = {}
    for repository in repositories:
        if repository not in current_source_shas:
            raise DevelopmentMemoryError(
                f"current source SHA missing for repository: {repository}"
            )
        normalized_current[repository] = _sha40(
            current_source_shas[repository],
            field=f"current source SHA for {repository}",
        )

    records = {record.memory_id: record for record in ledger.records}
    by_old = _validate_supersessions(
        records=records,
        rules=supersessions,
    )
    preliminary: dict[str, MemoryResolutionEntry] = {}

    for record in ledger.records:
        subject = memory_subject(record)
        rule = by_old.get(record.memory_id)
        if rule is not None:
            preliminary[record.memory_id] = MemoryResolutionEntry(
                memory_id=record.memory_id,
                repository=record.repository,
                subject=subject,
                disposition=MemoryDisposition.SUPERSEDED,
                source_sha=record.source_sha,
                superseded_by=rule.new_memory_id,
                reason=rule.reason.value,
            )
            continue
        current_sha = normalized_current[record.repository]
        if record.source_sha != current_sha:
            preliminary[record.memory_id] = MemoryResolutionEntry(
                memory_id=record.memory_id,
                repository=record.repository,
                subject=subject,
                disposition=MemoryDisposition.STALE,
                source_sha=record.source_sha,
                reason="source-sha-not-current",
            )
            continue
        preliminary[record.memory_id] = MemoryResolutionEntry(
            memory_id=record.memory_id,
            repository=record.repository,
            subject=subject,
            disposition=MemoryDisposition.ACTIVE,
            source_sha=record.source_sha,
        )

    active_by_subject: dict[tuple[str, str], list[str]] = {}
    for memory_id, entry in preliminary.items():
        if entry.disposition is MemoryDisposition.ACTIVE:
            active_by_subject.setdefault(
                (entry.repository, entry.subject),
                [],
            ).append(memory_id)

    for memory_ids in active_by_subject.values():
        if len(memory_ids) <= 1:
            continue
        for memory_id in memory_ids:
            entry = preliminary[memory_id]
            preliminary[memory_id] = MemoryResolutionEntry(
                memory_id=entry.memory_id,
                repository=entry.repository,
                subject=entry.subject,
                disposition=MemoryDisposition.CONFLICT,
                source_sha=entry.source_sha,
                reason="multiple-current-memories-for-subject",
            )

    entries = tuple(
        preliminary[record.memory_id]
        for record in ledger.records
    )
    active_records = tuple(
        record
        for record in ledger.records
        if preliminary[record.memory_id].disposition
        is MemoryDisposition.ACTIVE
    )
    return DevelopmentMemoryResolution(
        entries=entries,
        active_records=active_records,
    )
