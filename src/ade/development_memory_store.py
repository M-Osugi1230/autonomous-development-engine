from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_from_dict(payload: object) -> DevelopmentMemoryRecord:
    if not isinstance(payload, dict):
        raise DevelopmentMemoryError("memory store record must be a JSON object")
    allowed = {
        "schema_version",
        "memory_id",
        "kind",
        "repository",
        "source_sha",
        "statement",
        "campaign_id",
        "task_id",
        "evidence_paths",
        "evidence_fingerprints",
        "tags",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise DevelopmentMemoryError(
            f"unknown memory store record fields: {sorted(unknown)}"
        )
    evidence_paths = payload.get("evidence_paths")
    evidence_fingerprints = payload.get("evidence_fingerprints")
    tags = payload.get("tags", [])
    if not isinstance(evidence_paths, list):
        raise DevelopmentMemoryError("memory store evidence_paths must be a list")
    if not isinstance(evidence_fingerprints, list):
        raise DevelopmentMemoryError(
            "memory store evidence_fingerprints must be a list"
        )
    if not isinstance(tags, list):
        raise DevelopmentMemoryError("memory store tags must be a list")
    try:
        kind = MemoryKind(payload.get("kind"))
    except (TypeError, ValueError) as exc:
        raise DevelopmentMemoryError("memory store kind is invalid") from exc
    return DevelopmentMemoryRecord(
        schema_version=payload.get("schema_version", 0),
        memory_id=payload.get("memory_id", ""),
        kind=kind,
        repository=payload.get("repository", ""),
        source_sha=payload.get("source_sha", ""),
        statement=payload.get("statement", ""),
        campaign_id=payload.get("campaign_id"),
        task_id=payload.get("task_id"),
        evidence_paths=tuple(evidence_paths),
        evidence_fingerprints=tuple(evidence_fingerprints),
        tags=tuple(tags),
    )


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryStore:
    ledger: DevelopmentMemoryLedger = DevelopmentMemoryLedger()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory store schema version")
        if not isinstance(self.ledger, DevelopmentMemoryLedger):
            raise DevelopmentMemoryError("memory store ledger is invalid")
        if len(self.ledger.records) > 500:
            raise DevelopmentMemoryError("memory store exceeds trusted record budget")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ledger": self.ledger.canonical_dict(),
            "ledger_fingerprint": self.ledger.fingerprint(),
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.canonical_dict()).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_dict(cls, payload: object) -> "DevelopmentMemoryStore":
        if not isinstance(payload, dict):
            raise DevelopmentMemoryError("memory store must be a JSON object")
        allowed = {"schema_version", "ledger", "ledger_fingerprint"}
        unknown = set(payload) - allowed
        if unknown:
            raise DevelopmentMemoryError(
                f"unknown memory store fields: {sorted(unknown)}"
            )
        if payload.get("schema_version") != 1:
            raise DevelopmentMemoryError("memory store schema_version must be 1")
        ledger_payload = payload.get("ledger")
        if not isinstance(ledger_payload, dict):
            raise DevelopmentMemoryError("memory store ledger must be an object")
        if set(ledger_payload) != {"schema_version", "record_count", "records"}:
            raise DevelopmentMemoryError("memory store ledger fields are invalid")
        if ledger_payload.get("schema_version") != 1:
            raise DevelopmentMemoryError("memory store ledger schema_version must be 1")
        raw_records = ledger_payload.get("records")
        if not isinstance(raw_records, list):
            raise DevelopmentMemoryError("memory store records must be a list")
        if ledger_payload.get("record_count") != len(raw_records):
            raise DevelopmentMemoryError("memory store record_count mismatch")
        ledger = DevelopmentMemoryLedger(
            records=tuple(_record_from_dict(item) for item in raw_records)
        )
        if payload.get("ledger_fingerprint") != ledger.fingerprint():
            raise DevelopmentMemoryError("memory store ledger fingerprint mismatch")
        return cls(ledger=ledger)


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryStoreUpdate:
    store: DevelopmentMemoryStore
    changed: bool
    added_memory_ids: tuple[str, ...]


def merge_memory_records(
    store: DevelopmentMemoryStore,
    records: Iterable[DevelopmentMemoryRecord],
) -> DevelopmentMemoryStoreUpdate:
    if not isinstance(store, DevelopmentMemoryStore):
        raise DevelopmentMemoryError("store must be DevelopmentMemoryStore")

    existing = {record.memory_id: record for record in store.ledger.records}
    added: list[str] = []
    for record in records:
        if not isinstance(record, DevelopmentMemoryRecord):
            raise DevelopmentMemoryError(
                "memory store update requires DevelopmentMemoryRecord values"
            )
        prior = existing.get(record.memory_id)
        if prior is None:
            existing[record.memory_id] = record
            added.append(record.memory_id)
            continue
        if prior.canonical_dict() != record.canonical_dict():
            raise DevelopmentMemoryError(
                f"memory id collision with different content: {record.memory_id}"
            )

    next_store = DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=tuple(existing.values()))
    )
    return DevelopmentMemoryStoreUpdate(
        store=next_store,
        changed=next_store.canonical_dict() != store.canonical_dict(),
        added_memory_ids=tuple(sorted(added)),
    )
