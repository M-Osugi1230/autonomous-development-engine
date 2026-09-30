from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_MARKERS = (
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "github_pat_",
    "ghp_",
    "gho_",
    "ghs_",
    "akia",
    "bearer ",
)


class DevelopmentMemoryError(ValueError):
    """Trusted development-memory validation failed."""


class MemoryKind(str, Enum):
    DECISION = "DECISION"
    FAILURE = "FAILURE"
    REMEDIATION = "REMEDIATION"
    VERIFIED_OUTCOME = "VERIFIED_OUTCOME"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validated_repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise DevelopmentMemoryError("repository must be owner/name")
    return value


def _validated_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise DevelopmentMemoryError("source_sha must be a lowercase 40-char SHA")
    return value


def _validated_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise DevelopmentMemoryError(f"{field} is invalid")
    return value


def _validated_optional_id(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _validated_id(value, field=field)


def _validated_statement(value: str) -> str:
    if not isinstance(value, str):
        raise DevelopmentMemoryError("statement must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > 500 or _CONTROL.search(normalized):
        raise DevelopmentMemoryError("statement must be one bounded printable line")
    folded = normalized.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        raise DevelopmentMemoryError("statement contains a secret-like marker")
    if "http://" in folded or "https://" in folded:
        raise DevelopmentMemoryError("statement must not contain URLs")
    return normalized


def _validated_evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise DevelopmentMemoryError("evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise DevelopmentMemoryError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise DevelopmentMemoryError("evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise DevelopmentMemoryError("evidence path must remain inside .autodev/")
    return value


def _validated_fingerprint(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentMemoryError("evidence fingerprint must be sha256")
    return value


def _validated_tag(value: str) -> str:
    if not isinstance(value, str) or _TAG.fullmatch(value) is None:
        raise DevelopmentMemoryError("memory tag is invalid")
    return value


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryRecord:
    memory_id: str
    kind: MemoryKind
    repository: str
    source_sha: str
    statement: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    tags: tuple[str, ...] = ()
    campaign_id: str | None = None
    task_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory schema version")
        object.__setattr__(self, "memory_id", _validated_id(self.memory_id, field="memory_id"))
        if not isinstance(self.kind, MemoryKind):
            raise DevelopmentMemoryError("kind must be MemoryKind")
        object.__setattr__(self, "repository", _validated_repository(self.repository))
        object.__setattr__(self, "source_sha", _validated_sha(self.source_sha))
        object.__setattr__(self, "statement", _validated_statement(self.statement))
        object.__setattr__(
            self,
            "campaign_id",
            _validated_optional_id(self.campaign_id, field="campaign_id"),
        )
        object.__setattr__(
            self,
            "task_id",
            _validated_optional_id(self.task_id, field="task_id"),
        )

        evidence_paths = tuple(
            sorted({_validated_evidence_path(path) for path in self.evidence_paths})
        )
        evidence_fingerprints = tuple(
            sorted({_validated_fingerprint(value) for value in self.evidence_fingerprints})
        )
        tags = tuple(sorted({_validated_tag(tag) for tag in self.tags}))

        if not evidence_paths:
            raise DevelopmentMemoryError("at least one trusted evidence path is required")
        if not evidence_fingerprints:
            raise DevelopmentMemoryError("at least one evidence fingerprint is required")
        if len(evidence_paths) > 8:
            raise DevelopmentMemoryError("too many evidence paths")
        if len(evidence_fingerprints) > 8:
            raise DevelopmentMemoryError("too many evidence fingerprints")
        if len(tags) > 12:
            raise DevelopmentMemoryError("too many memory tags")

        object.__setattr__(self, "evidence_paths", evidence_paths)
        object.__setattr__(self, "evidence_fingerprints", evidence_fingerprints)
        object.__setattr__(self, "tags", tags)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "statement": self.statement,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "tags": list(self.tags),
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryLedger:
    records: tuple[DevelopmentMemoryRecord, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported ledger schema version")

        seen: set[str] = set()
        normalized: list[DevelopmentMemoryRecord] = []
        for record in self.records:
            if not isinstance(record, DevelopmentMemoryRecord):
                raise DevelopmentMemoryError("ledger contains an invalid record")
            if record.memory_id in seen:
                raise DevelopmentMemoryError(
                    f"duplicate development memory id: {record.memory_id}"
                )
            seen.add(record.memory_id)
            normalized.append(record)

        object.__setattr__(
            self,
            "records",
            tuple(
                sorted(
                    normalized,
                    key=lambda item: (
                        item.repository,
                        item.kind.value,
                        item.memory_id,
                    ),
                )
            ),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "record_count": len(self.records),
            "records": [record.canonical_dict() for record in self.records],
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    def append(self, record: DevelopmentMemoryRecord) -> DevelopmentMemoryLedger:
        if not isinstance(record, DevelopmentMemoryRecord):
            raise DevelopmentMemoryError("record must be DevelopmentMemoryRecord")
        return DevelopmentMemoryLedger(records=(*self.records, record))


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryPlannerContext:
    payload: dict[str, Any]
    serialized: str
    fingerprint: str


def build_planner_memory_context(
    ledger: DevelopmentMemoryLedger,
    *,
    repository: str,
    kinds: Iterable[MemoryKind] | None = None,
    max_records: int = 20,
    max_chars: int = 6000,
) -> DevelopmentMemoryPlannerContext:
    if not isinstance(ledger, DevelopmentMemoryLedger):
        raise DevelopmentMemoryError("ledger must be DevelopmentMemoryLedger")
    repository = _validated_repository(repository)
    if type(max_records) is not int or not 1 <= max_records <= 100:
        raise DevelopmentMemoryError("max_records must be between 1 and 100")
    if type(max_chars) is not int or not 512 <= max_chars <= 20000:
        raise DevelopmentMemoryError("max_chars must be between 512 and 20000")

    allowed_kinds: frozenset[MemoryKind] | None = None
    if kinds is not None:
        values = tuple(kinds)
        if not values or any(not isinstance(kind, MemoryKind) for kind in values):
            raise DevelopmentMemoryError("kinds must contain MemoryKind values")
        allowed_kinds = frozenset(values)

    candidates = [
        record
        for record in ledger.records
        if record.repository == repository
        and (allowed_kinds is None or record.kind in allowed_kinds)
    ]

    selected: list[dict[str, Any]] = []
    for record in candidates[:max_records]:
        item = record.canonical_dict()
        candidate_payload = {
            "schema_version": 1,
            "repository": repository,
            "authority": "advisory-data-only",
            "execution_authority": False,
            "memory_may_expand_scope": False,
            "memory_may_override_acceptance": False,
            "records": [*selected, item],
        }
        serialized = _canonical_json(candidate_payload)
        if len(serialized) > max_chars:
            break
        selected.append(item)

    payload = {
        "schema_version": 1,
        "repository": repository,
        "authority": "advisory-data-only",
        "execution_authority": False,
        "memory_may_expand_scope": False,
        "memory_may_override_acceptance": False,
        "records": selected,
    }
    serialized = _canonical_json(payload)
    if len(serialized) > max_chars:
        raise DevelopmentMemoryError("memory context header exceeds character budget")
    return DevelopmentMemoryPlannerContext(
        payload=payload,
        serialized=serialized,
        fingerprint=_fingerprint(payload),
    )
