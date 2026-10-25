from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from .remote_execution import parse_pull_request_url, validate_repository_name


@dataclass(frozen=True, slots=True)
class ReviewWaitRecord:
    task_id: str
    target_repository: str
    pull_request_url: str
    reason: str
    created_at: str
    updated_at: str
    depends_on: tuple[str, ...] = ()
    status: str = "WAITING_REVIEW"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("review wait record schema_version must be 1")
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("review wait task_id must be non-empty")
        validate_repository_name(self.target_repository)
        repository, _ = parse_pull_request_url(self.pull_request_url)
        if repository != self.target_repository:
            raise ValueError("review wait PR repository does not match target_repository")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("review wait reason must be non-empty")
        if self.status != "WAITING_REVIEW":
            raise ValueError("review wait status must be WAITING_REVIEW")
        for field_name, value in (
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"review wait {field_name} must be non-empty")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"review wait {field_name} must be ISO-8601"
                ) from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError(
                    f"review wait {field_name} must include a timezone"
                )
        if not isinstance(self.depends_on, tuple):
            object.__setattr__(self, "depends_on", tuple(self.depends_on))
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("review wait dependencies must be unique")
        for dependency in self.depends_on:
            if not isinstance(dependency, str) or not dependency.strip():
                raise ValueError("review wait dependencies must be non-empty strings")

    @property
    def pull_request_number(self) -> int:
        _, number = parse_pull_request_url(self.pull_request_url)
        return number

    def touch(self, observed_at: str, *, reason: str | None = None) -> "ReviewWaitRecord":
        return replace(
            self,
            updated_at=observed_at,
            reason=self.reason if reason is None else reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "target_repository": self.target_repository,
            "pull_request_url": self.pull_request_url,
            "pull_request_number": self.pull_request_number,
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "depends_on": list(self.depends_on),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewWaitRecord":
        if not isinstance(payload, dict):
            raise ValueError("review wait record must be a JSON object")
        allowed = {
            "schema_version",
            "task_id",
            "target_repository",
            "pull_request_url",
            "pull_request_number",
            "reason",
            "created_at",
            "updated_at",
            "depends_on",
            "status",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown review wait fields: {sorted(unknown)}")
        raw_dependencies = payload.get("depends_on", [])
        if not isinstance(raw_dependencies, list):
            raise ValueError("review wait depends_on must be a list")
        record = cls(
            schema_version=payload.get("schema_version", 0),
            task_id=str(payload.get("task_id", "")),
            target_repository=str(payload.get("target_repository", "")),
            pull_request_url=str(payload.get("pull_request_url", "")),
            reason=str(payload.get("reason", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
            depends_on=tuple(raw_dependencies),
            status=str(payload.get("status", "")),
        )
        number = payload.get("pull_request_number")
        if number is not None and number != record.pull_request_number:
            raise ValueError("review wait pull_request_number does not match URL")
        return record


@dataclass(frozen=True, slots=True)
class ReviewWaitLedger:
    records: tuple[ReviewWaitRecord, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("review wait ledger schema_version must be 1")
        if not isinstance(self.records, tuple):
            object.__setattr__(self, "records", tuple(self.records))
        task_ids = [record.task_id for record in self.records]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("review wait ledger task IDs must be unique")

    def get(self, task_id: str) -> ReviewWaitRecord | None:
        for record in self.records:
            if record.task_id == task_id:
                return record
        return None

    def upsert(self, record: ReviewWaitRecord) -> "ReviewWaitLedger":
        result = []
        replaced = False
        for existing in self.records:
            if existing.task_id == record.task_id:
                if (
                    existing.target_repository != record.target_repository
                    or existing.pull_request_url != record.pull_request_url
                ):
                    raise ValueError(
                        "review wait task cannot be rebound to a different pull request"
                    )
                result.append(record)
                replaced = True
            else:
                result.append(existing)
        if not replaced:
            result.append(record)
        return ReviewWaitLedger(records=tuple(result))

    def remove(self, task_id: str) -> "ReviewWaitLedger":
        return ReviewWaitLedger(
            records=tuple(record for record in self.records if record.task_id != task_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewWaitLedger":
        if not isinstance(payload, dict):
            raise ValueError("review wait ledger must be a JSON object")
        if payload.get("schema_version") != 1:
            raise ValueError("review wait ledger schema_version must be 1")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("review wait ledger records must be a list")
        return cls(
            records=tuple(ReviewWaitRecord.from_dict(item) for item in raw_records),
            schema_version=1,
        )
