from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from .checkpoint import SECRET_PATTERNS


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCOPE = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
_MEMORY_ID = re.compile(r"^mem-[0-9a-f]{24}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_MEMORY_SUMMARY = 512
MAX_MEMORY_EVIDENCE = 16
MAX_MEMORY_RECORDS = 500
_ALLOWED_EVIDENCE_PREFIX = ".autodev/"


class DevelopmentMemoryError(ValueError):
    """Trusted Development Memory validation failed."""


class DevelopmentMemoryKind(StrEnum):
    SUCCESS_PATTERN = "SUCCESS_PATTERN"
    FAILURE_LESSON = "FAILURE_LESSON"
    CONSTRAINT = "CONSTRAINT"
    DECISION = "DECISION"
    REPOSITORY_FACT = "REPOSITORY_FACT"
    RUNTIME_FACT = "RUNTIME_FACT"


class DevelopmentMemoryAuthority(StrEnum):
    ADVISORY = "ADVISORY"


def _safe_text(value: object, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentMemoryError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise DevelopmentMemoryError(
            f"{field_name} exceeds trusted length budget {max_length}"
        )
    if _CONTROL.search(normalized):
        raise DevelopmentMemoryError(f"{field_name} contains control characters")
    if "Traceback (most recent call last)" in normalized:
        raise DevelopmentMemoryError(f"{field_name} must not contain raw tracebacks")
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise DevelopmentMemoryError(
                f"{field_name} contains a forbidden secret pattern"
            )
    return normalized


def _repository(value: object) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise DevelopmentMemoryError("repository must be owner/name")
    return value


def _scope(value: object) -> str:
    if not isinstance(value, str) or _SCOPE.fullmatch(value) is None:
        raise DevelopmentMemoryError(
            "scope must use only letters, digits, '.', '_', ':', '/', or '-'"
        )
    return value


def _timestamp(value: object) -> str:
    normalized = _safe_text(value, field_name="observed_at", max_length=80)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DevelopmentMemoryError("observed_at must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DevelopmentMemoryError("observed_at must be timezone-aware")
    return normalized


def _evidence_ref(value: object) -> str:
    normalized = _safe_text(value, field_name="evidence ref", max_length=512)
    if not normalized.startswith(_ALLOWED_EVIDENCE_PREFIX):
        raise DevelopmentMemoryError(
            "evidence ref must point to a trusted .autodev/ artifact"
        )
    if normalized.startswith("/") or "\\" in normalized:
        raise DevelopmentMemoryError("evidence ref must be a normalized relative path")
    parsed = PurePosixPath(normalized)
    if "." in parsed.parts or ".." in parsed.parts or str(parsed) != normalized:
        raise DevelopmentMemoryError("evidence ref must be a normalized relative path")
    return normalized


def _fingerprint(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentMemoryError(
            "evidence fingerprint must be a lowercase SHA-256 hex digest"
        )
    return value


@dataclass(frozen=True, slots=True, order=True)
class DevelopmentMemoryEvidence:
    ref: str
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _evidence_ref(self.ref))
        object.__setattr__(self, "fingerprint", _fingerprint(self.fingerprint))

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, payload: object) -> "DevelopmentMemoryEvidence":
        if not isinstance(payload, dict):
            raise DevelopmentMemoryError("memory evidence must be a JSON object")
        if set(payload) != {"ref", "fingerprint"}:
            raise DevelopmentMemoryError(
                "memory evidence must contain only ref and fingerprint"
            )
        return cls(ref=payload["ref"], fingerprint=payload["fingerprint"])


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryRecord:
    memory_id: str
    kind: DevelopmentMemoryKind
    repository: str
    scope: str
    summary: str
    evidence: tuple[DevelopmentMemoryEvidence, ...]
    observed_at: str
    authority: DevelopmentMemoryAuthority = DevelopmentMemoryAuthority.ADVISORY
    can_grant_execution_authority: bool = False
    can_expand_write_scope: bool = False
    can_bypass_human_wait: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory record schema_version")
        try:
            kind = DevelopmentMemoryKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise DevelopmentMemoryError(f"invalid memory kind: {self.kind}") from exc
        object.__setattr__(self, "kind", kind)

        try:
            authority = DevelopmentMemoryAuthority(self.authority)
        except (TypeError, ValueError) as exc:
            raise DevelopmentMemoryError("memory authority must be ADVISORY") from exc
        if authority is not DevelopmentMemoryAuthority.ADVISORY:
            raise DevelopmentMemoryError("memory authority must be ADVISORY")
        object.__setattr__(self, "authority", authority)

        if self.can_grant_execution_authority is not False:
            raise DevelopmentMemoryError(
                "memory must never grant execution authority"
            )
        if self.can_expand_write_scope is not False:
            raise DevelopmentMemoryError("memory must never expand write scope")
        if self.can_bypass_human_wait is not False:
            raise DevelopmentMemoryError("memory must never bypass HUMAN_WAIT")

        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(
            self,
            "summary",
            _safe_text(
                self.summary,
                field_name="summary",
                max_length=MAX_MEMORY_SUMMARY,
            ),
        )
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at))

        if not isinstance(self.evidence, tuple):
            raise DevelopmentMemoryError("evidence must be a tuple")
        if not self.evidence:
            raise DevelopmentMemoryError("memory requires at least one evidence ref")
        if len(self.evidence) > MAX_MEMORY_EVIDENCE:
            raise DevelopmentMemoryError(
                f"memory exceeds evidence budget {MAX_MEMORY_EVIDENCE}"
            )
        normalized_evidence: list[DevelopmentMemoryEvidence] = []
        for item in self.evidence:
            if not isinstance(item, DevelopmentMemoryEvidence):
                raise DevelopmentMemoryError(
                    "evidence entries must be DevelopmentMemoryEvidence"
                )
            normalized_evidence.append(item)
        ordered = tuple(sorted(normalized_evidence))
        if len({item.ref for item in ordered}) != len(ordered):
            raise DevelopmentMemoryError("duplicate evidence ref")
        object.__setattr__(self, "evidence", ordered)

        if not isinstance(self.memory_id, str) or _MEMORY_ID.fullmatch(self.memory_id) is None:
            raise DevelopmentMemoryError("memory_id must be mem- plus 24 lowercase hex chars")
        expected = "mem-" + self.fingerprint()[:24]
        if self.memory_id != expected:
            raise DevelopmentMemoryError(
                "memory_id does not match trusted content fingerprint"
            )

    def content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "repository": self.repository,
            "scope": self.scope,
            "summary": self.summary,
            "evidence": [item.to_dict() for item in self.evidence],
            "observed_at": self.observed_at,
            "authority": self.authority.value,
            "can_grant_execution_authority": False,
            "can_expand_write_scope": False,
            "can_bypass_human_wait": False,
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, **self.content_dict()}

    @classmethod
    def from_dict(cls, payload: object) -> "DevelopmentMemoryRecord":
        if not isinstance(payload, dict):
            raise DevelopmentMemoryError("memory record must be a JSON object")
        required = {
            "schema_version",
            "memory_id",
            "kind",
            "repository",
            "scope",
            "summary",
            "evidence",
            "observed_at",
            "authority",
            "can_grant_execution_authority",
            "can_expand_write_scope",
            "can_bypass_human_wait",
        }
        if set(payload) != required:
            raise DevelopmentMemoryError(
                "memory record keys do not match trusted schema"
            )
        raw_evidence = payload["evidence"]
        if not isinstance(raw_evidence, list):
            raise DevelopmentMemoryError("evidence must be a JSON array")
        return cls(
            schema_version=payload["schema_version"],
            memory_id=payload["memory_id"],
            kind=payload["kind"],
            repository=payload["repository"],
            scope=payload["scope"],
            summary=payload["summary"],
            evidence=tuple(
                DevelopmentMemoryEvidence.from_dict(item)
                for item in raw_evidence
            ),
            observed_at=payload["observed_at"],
            authority=payload["authority"],
            can_grant_execution_authority=payload[
                "can_grant_execution_authority"
            ],
            can_expand_write_scope=payload["can_expand_write_scope"],
            can_bypass_human_wait=payload["can_bypass_human_wait"],
        )


def build_development_memory_record(
    *,
    kind: DevelopmentMemoryKind | str,
    repository: str,
    scope: str,
    summary: str,
    evidence: Iterable[DevelopmentMemoryEvidence],
    observed_at: str,
) -> DevelopmentMemoryRecord:
    evidence_tuple = tuple(evidence)
    draft = {
        "schema_version": 1,
        "kind": DevelopmentMemoryKind(kind).value,
        "repository": _repository(repository),
        "scope": _scope(scope),
        "summary": _safe_text(
            summary,
            field_name="summary",
            max_length=MAX_MEMORY_SUMMARY,
        ),
        "evidence": [
            item.to_dict()
            if isinstance(item, DevelopmentMemoryEvidence)
            else (_ for _ in ()).throw(
                DevelopmentMemoryError(
                    "evidence entries must be DevelopmentMemoryEvidence"
                )
            )
            for item in sorted(evidence_tuple)
        ],
        "observed_at": _timestamp(observed_at),
        "authority": DevelopmentMemoryAuthority.ADVISORY.value,
        "can_grant_execution_authority": False,
        "can_expand_write_scope": False,
        "can_bypass_human_wait": False,
    }
    raw = json.dumps(
        draft,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    memory_id = "mem-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=draft["kind"],
        repository=draft["repository"],
        scope=draft["scope"],
        summary=draft["summary"],
        evidence=evidence_tuple,
        observed_at=draft["observed_at"],
    )


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryLedger:
    records: tuple[DevelopmentMemoryRecord, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory ledger schema_version")
        if not isinstance(self.records, tuple):
            raise DevelopmentMemoryError("records must be a tuple")
        if len(self.records) > MAX_MEMORY_RECORDS:
            raise DevelopmentMemoryError(
                f"memory ledger exceeds record budget {MAX_MEMORY_RECORDS}"
            )
        for record in self.records:
            if not isinstance(record, DevelopmentMemoryRecord):
                raise DevelopmentMemoryError(
                    "ledger records must be DevelopmentMemoryRecord"
                )
        ids = [record.memory_id for record in self.records]
        if len(set(ids)) != len(ids):
            raise DevelopmentMemoryError("duplicate memory_id in ledger")
        fingerprints = [record.fingerprint() for record in self.records]
        if len(set(fingerprints)) != len(fingerprints):
            raise DevelopmentMemoryError("duplicate memory content in ledger")
        ordered = tuple(
            sorted(self.records, key=lambda record: (record.observed_at, record.memory_id))
        )
        object.__setattr__(self, "records", ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "DevelopmentMemoryLedger":
        if not isinstance(payload, dict):
            raise DevelopmentMemoryError("memory ledger must be a JSON object")
        if set(payload) != {"schema_version", "records"}:
            raise DevelopmentMemoryError(
                "memory ledger keys do not match trusted schema"
            )
        if payload["schema_version"] != 1:
            raise DevelopmentMemoryError("unsupported memory ledger schema_version")
        raw_records = payload["records"]
        if not isinstance(raw_records, list):
            raise DevelopmentMemoryError("records must be a JSON array")
        return cls(
            schema_version=1,
            records=tuple(
                DevelopmentMemoryRecord.from_dict(item)
                for item in raw_records
            ),
        )

    def add(self, record: DevelopmentMemoryRecord) -> "DevelopmentMemoryLedger":
        if not isinstance(record, DevelopmentMemoryRecord):
            raise DevelopmentMemoryError(
                "record must be a DevelopmentMemoryRecord"
            )
        for existing in self.records:
            if existing.memory_id == record.memory_id:
                if existing == record:
                    return self
                raise DevelopmentMemoryError(
                    "memory_id collision with different content"
                )
        return DevelopmentMemoryLedger(records=(*self.records, record))
