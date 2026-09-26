from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .checkpoint import SECRET_PATTERNS
from .decisions import DecisionRecord, DecisionResponse, DecisionStatus

SCHEMA_VERSION = 1
DEFAULT_PATH = Path(".autodev/decisions.json")


def _assert_safe_payload(payload: Any) -> None:
    if isinstance(payload, str):
        if "Traceback (most recent call last)" in payload:
            raise ValueError("decision data must not contain tracebacks")
        for pattern in SECRET_PATTERNS:
            if pattern.search(payload):
                raise ValueError("decision data contains a forbidden secret pattern")
        return

    if isinstance(payload, dict):
        for key, value in payload.items():
            _assert_safe_payload(key)
            _assert_safe_payload(value)
        return

    if isinstance(payload, (list, tuple)):
        for item in payload:
            _assert_safe_payload(item)


class DecisionStore:
    """Durable, atomically persisted human-decision queue."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> tuple[DecisionRecord, ...]:
        if not self.path.exists():
            return ()

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"decision store contains invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("decision store must contain a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported decision store schema_version: {payload.get('schema_version')}"
            )

        records_payload = payload.get("decisions")
        if not isinstance(records_payload, list):
            raise ValueError("decision store decisions must be a list")

        records: list[DecisionRecord] = []
        seen_ids: set[str] = set()
        for item in records_payload:
            if not isinstance(item, dict):
                raise ValueError("decision store records must be JSON objects")
            record = DecisionRecord.from_dict(item)
            if record.decision_id in seen_ids:
                raise ValueError(f"duplicate decision_id in store: {record.decision_id}")
            _assert_safe_payload(record.to_dict())
            seen_ids.add(record.decision_id)
            records.append(record)

        return tuple(records)

    def save(self, records: tuple[DecisionRecord, ...] | list[DecisionRecord]) -> None:
        if not isinstance(records, (tuple, list)):
            raise TypeError("records must be a tuple or list of DecisionRecord values")

        normalized: list[DecisionRecord] = []
        seen_ids: set[str] = set()
        for record in records:
            if not isinstance(record, DecisionRecord):
                raise TypeError("records must contain only DecisionRecord values")
            if record.decision_id in seen_ids:
                raise ValueError(f"duplicate decision_id: {record.decision_id}")
            _assert_safe_payload(record.to_dict())
            seen_ids.add(record.decision_id)
            normalized.append(record)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "decisions": [record.to_dict() for record in normalized],
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def get(self, decision_id: str) -> DecisionRecord | None:
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise ValueError("decision_id must be a non-empty string")
        for record in self.load():
            if record.decision_id == decision_id:
                return record
        return None

    def enqueue(self, record: DecisionRecord) -> DecisionRecord:
        if not isinstance(record, DecisionRecord):
            raise TypeError("record must be a DecisionRecord")

        records = list(self.load())
        for existing in records:
            if existing.decision_id != record.decision_id:
                continue
            if existing == record:
                return existing
            raise ValueError(
                f"decision_id conflict for existing record: {record.decision_id}"
            )

        records.append(record)
        self.save(records)
        return record

    def list_open(self) -> tuple[DecisionRecord, ...]:
        return tuple(
            record
            for record in self.load()
            if record.status is DecisionStatus.OPEN
        )

    def resolve(
        self,
        decision_id: str,
        response: DecisionResponse,
    ) -> DecisionRecord:
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise ValueError("decision_id must be a non-empty string")
        if not isinstance(response, DecisionResponse):
            raise TypeError("response must be a DecisionResponse")
        if response.decision_id != decision_id:
            raise ValueError("response decision_id does not match decision_id")

        records = list(self.load())
        for index, record in enumerate(records):
            if record.decision_id != decision_id:
                continue
            if record.status is not DecisionStatus.OPEN:
                raise ValueError(
                    f"decision {decision_id} is already {record.status.value}"
                )

            resolved = DecisionRecord(
                request=record.request,
                status=DecisionStatus.RESOLVED,
                response=response,
            )
            records[index] = resolved
            self.save(records)
            return resolved

        raise KeyError(f"decision_id not found: {decision_id}")
