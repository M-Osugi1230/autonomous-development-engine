from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from .checkpoint import SECRET_PATTERNS


SAFE_PREVIEW_HOSTS = frozenset({"github.com"})
MAX_PREVIEW_TEXT = 512


class PreviewKind(StrEnum):
    PULL_REQUEST = "PULL_REQUEST"
    ACTION_ARTIFACT = "ACTION_ARTIFACT"
    BUILD = "BUILD"


def _safe_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if "Traceback (most recent call last)" in normalized:
        raise ValueError(f"{field_name} must not contain tracebacks")
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise ValueError(f"{field_name} contains a forbidden secret pattern")
    if len(normalized) > MAX_PREVIEW_TEXT:
        raise ValueError(f"{field_name} exceeds {MAX_PREVIEW_TEXT} characters")
    return normalized


def _validate_timestamp(value: str) -> str:
    normalized = _safe_text(value, field_name="updated_at")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("updated_at must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("updated_at must be timezone-aware")
    return normalized


def _validate_url(value: str) -> str:
    normalized = _safe_text(value, field_name="url")
    parsed = urlparse(normalized)
    if parsed.scheme != "https":
        raise ValueError("preview url must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("preview url must not contain credentials")
    if parsed.hostname not in SAFE_PREVIEW_HOSTS:
        raise ValueError(f"preview host is not allowed: {parsed.hostname}")
    if not parsed.path or parsed.path == "/":
        raise ValueError("preview url must contain a path")
    if parsed.query or parsed.fragment:
        raise ValueError("preview url must not contain query or fragment")
    return normalized


@dataclass(frozen=True, slots=True)
class PreviewManifest:
    preview_id: str
    kind: PreviewKind
    title: str
    url: str
    task_id: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "preview_id",
            _safe_text(self.preview_id, field_name="preview_id"),
        )
        try:
            kind = PreviewKind(self.kind)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid preview kind: {self.kind}") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "title", _safe_text(self.title, field_name="title"))
        object.__setattr__(self, "url", _validate_url(self.url))
        object.__setattr__(
            self,
            "task_id",
            _safe_text(self.task_id, field_name="task_id"),
        )
        object.__setattr__(self, "updated_at", _validate_timestamp(self.updated_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "kind": self.kind.value,
            "title": self.title,
            "url": self.url,
            "task_id": self.task_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PreviewManifest":
        if not isinstance(payload, dict):
            raise ValueError("preview payload must be a JSON object")
        required = {"preview_id", "kind", "title", "url", "task_id", "updated_at"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"missing preview keys: {sorted(missing)}")
        return cls(
            preview_id=payload["preview_id"],
            kind=payload["kind"],
            title=payload["title"],
            url=payload["url"],
            task_id=payload["task_id"],
            updated_at=payload["updated_at"],
        )
