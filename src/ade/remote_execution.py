from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from urllib.parse import urlparse


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JULES_AUTOMATION_MARKER = "PR created automatically by Jules for task ["


def validate_repository_name(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise ValueError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError("repository must be owner/name")
    if owner.startswith(".") or owner.endswith(".") or name.startswith(".") or name.endswith("."):
        raise ValueError("repository must be owner/name")
    return value


def execution_target_from_state(
    state_payload: dict[str, Any],
    *,
    fallback_repository: str,
) -> str:
    if not isinstance(state_payload, dict):
        raise ValueError("state payload must be a JSON object")
    fallback = validate_repository_name(fallback_repository)
    metadata = state_payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("state metadata must be a JSON object")
    candidate = metadata.get("target_repository")
    if candidate is None:
        return fallback
    if not isinstance(candidate, str):
        raise ValueError("target_repository must be a string")
    return validate_repository_name(candidate)


def parse_pull_request_url(url: str) -> tuple[str, int]:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("pull request URL must be non-empty")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("pull request URL must use https://github.com")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("pull request URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("pull request URL must not contain query or fragment")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "pull":
        raise ValueError("pull request URL must be /owner/repo/pull/number")
    repository = validate_repository_name(f"{parts[0]}/{parts[1]}")
    try:
        number = int(parts[3])
    except ValueError as exc:
        raise ValueError("pull request number must be an integer") from exc
    if number < 1:
        raise ValueError("pull request number must be positive")
    return repository, number


def pull_request_is_trusted_noop(payload: dict[str, Any] | None) -> bool:
    """Return True only for a Jules-created pull request with a verified zero diff.

    GitHub's pull request payload exposes aggregate diff counters even when the
    pull request is closed without merge.  Requiring both the Jules automation
    marker and all three counters to be zero prevents an arbitrary empty pull
    request from advancing ADE's trusted task queue.
    """

    if payload is None or not isinstance(payload, dict):
        return False
    body = payload.get("body")
    if not isinstance(body, str) or _JULES_AUTOMATION_MARKER not in body:
        return False
    if payload.get("merged_at") is not None:
        return False

    for field in ("changed_files", "additions", "deletions"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            return False
    return True


def receipt_binds_pull_request(
    payload: dict[str, Any] | None,
    *,
    task_id: str,
    target_repository: str,
    pull_request_url: str,
) -> bool:
    if payload is None or not isinstance(payload, dict):
        return False
    try:
        receipt = RemoteExecutionReceipt.from_dict(payload)
    except (ValueError, KeyError, TypeError):
        return False
    return (
        receipt.status == "PR_CREATED"
        and receipt.task_id == task_id
        and receipt.target_repository == target_repository
        and receipt.pull_request_url == pull_request_url
    )


@dataclass(frozen=True, slots=True)
class RemoteExecutionReceipt:
    task_id: str
    target_repository: str
    pull_request_url: str
    recorded_at: str
    status: str = "PR_CREATED"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("remote execution receipt schema_version must be 1")
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("remote execution receipt task_id must be non-empty")
        validate_repository_name(self.target_repository)
        repository, _ = parse_pull_request_url(self.pull_request_url)
        if repository != self.target_repository:
            raise ValueError("pull request URL repository does not match target_repository")
        if self.status not in {"PR_CREATED", "MERGED"}:
            raise ValueError("remote execution receipt status is invalid")
        if not isinstance(self.recorded_at, str) or not self.recorded_at.strip():
            raise ValueError("remote execution receipt recorded_at must be non-empty")
        try:
            parsed = datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("remote execution receipt recorded_at must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("remote execution receipt recorded_at must include a timezone")

    @property
    def pull_request_number(self) -> int:
        _, number = parse_pull_request_url(self.pull_request_url)
        return number

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "task_id": self.task_id,
            "target_repository": self.target_repository,
            "pull_request_url": self.pull_request_url,
            "recorded_at": self.recorded_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RemoteExecutionReceipt":
        if not isinstance(payload, dict):
            raise ValueError("remote execution receipt must be a JSON object")
        allowed = {
            "schema_version",
            "task_id",
            "target_repository",
            "pull_request_url",
            "recorded_at",
            "status",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown remote execution receipt fields: {sorted(unknown)}")
        return cls(
            schema_version=payload.get("schema_version", 0),
            task_id=str(payload.get("task_id", "")),
            target_repository=str(payload.get("target_repository", "")),
            pull_request_url=str(payload.get("pull_request_url", "")),
            recorded_at=str(payload.get("recorded_at", "")),
            status=str(payload.get("status", "")),
        )
