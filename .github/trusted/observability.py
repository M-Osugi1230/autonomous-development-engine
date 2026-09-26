from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from github_client import GitHubClient, GitHubError


ACTIVITY_PATH = ".autodev/activity.json"
PREVIEW_PATH = ".autodev/preview.json"
ACTIVITY_SCHEMA_VERSION = 1
PREVIEW_SCHEMA_VERSION = 1
ALLOWED_ACTIVITY_KINDS = frozenset(
    {
        "TASK_STARTED",
        "TASK_COMPLETED",
        "TASK_FAILED",
        "QUOTA_PAUSED",
        "HUMAN_WAIT",
        "DECISION_OPENED",
        "DECISION_RESOLVED",
        "PR_MERGED",
        "MILESTONE",
        "SYSTEM",
    }
)
ALLOWED_PREVIEW_KINDS = frozenset({"PULL_REQUEST", "ACTION_ARTIFACT", "BUILD"})
SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
)


def _safe_text(value: object, *, field_name: str, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    if "Traceback (most recent call last)" in normalized:
        raise ValueError(f"{field_name} must not contain tracebacks")
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise ValueError(f"{field_name} contains a forbidden secret pattern")
    return normalized


def _safe_timestamp(value: object) -> str:
    normalized = _safe_text(value, field_name="occurred_at")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return normalized


def _safe_github_url(value: object) -> str:
    normalized = _safe_text(value, field_name="url")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("preview url must be an HTTPS github.com URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("preview url must not contain credentials")
    if not parsed.path or parsed.path == "/":
        raise ValueError("preview url must contain a path")
    if parsed.query or parsed.fragment:
        raise ValueError("preview url must not contain query or fragment")
    return normalized


def _load_or_empty_activity(api: GitHubClient) -> tuple[dict[str, Any], str | None]:
    try:
        payload, sha = api.get_json_file(ACTIVITY_PATH)
    except GitHubError as exc:
        if "GitHub HTTP 404:" not in str(exc):
            raise
        return {"schema_version": ACTIVITY_SCHEMA_VERSION, "events": []}, None

    if payload.get("schema_version") != ACTIVITY_SCHEMA_VERSION:
        raise ValueError("unsupported activity schema_version")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("activity events must be a list")

    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("activity events must be objects")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("activity event_id must be a non-empty string")
        if event_id in seen:
            raise ValueError(f"duplicate activity event_id: {event_id}")
        seen.add(event_id)
    return payload, sha


def append_activity(
    api: GitHubClient,
    *,
    event_id: str,
    kind: str,
    occurred_at: str,
    summary: str,
    task_id: str | None = None,
) -> bool:
    event_id = _safe_text(event_id, field_name="event_id")
    if kind not in ALLOWED_ACTIVITY_KINDS:
        raise ValueError(f"unsupported activity kind: {kind}")
    occurred_at = _safe_timestamp(occurred_at)
    summary = _safe_text(summary, field_name="summary")
    if task_id is not None:
        task_id = _safe_text(task_id, field_name="task_id")

    event = {
        "event_id": event_id,
        "kind": kind,
        "occurred_at": occurred_at,
        "summary": summary,
        "task_id": task_id,
    }
    payload, sha = _load_or_empty_activity(api)
    events = payload["events"]
    for existing in events:
        if existing.get("event_id") != event_id:
            continue
        if existing == event:
            return False
        raise ValueError(f"activity event_id conflict: {event_id}")

    events.append(event)
    api.put_json_file(
        ACTIVITY_PATH,
        payload,
        sha=sha,
        message=f"activity: {kind.lower()} {task_id or event_id}",
    )
    return True


def set_preview(
    api: GitHubClient,
    *,
    preview_id: str,
    kind: str,
    title: str,
    url: str,
    task_id: str,
    updated_at: str,
) -> None:
    preview_id = _safe_text(preview_id, field_name="preview_id")
    if kind not in ALLOWED_PREVIEW_KINDS:
        raise ValueError(f"unsupported preview kind: {kind}")
    title = _safe_text(title, field_name="title")
    url = _safe_github_url(url)
    task_id = _safe_text(task_id, field_name="task_id")
    updated_at = _safe_timestamp(updated_at)

    api.upsert_json_file(
        PREVIEW_PATH,
        {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "preview": {
                "preview_id": preview_id,
                "kind": kind,
                "title": title,
                "url": url,
                "task_id": task_id,
                "updated_at": updated_at,
            },
        },
        message=f"preview: update for {task_id}",
    )


def record_merged_pr(
    api: GitHubClient,
    *,
    pr_number: int,
    pr_url: str,
    task_id: str,
    head_sha: str,
    occurred_at: str,
) -> None:
    if type(pr_number) is not int or pr_number < 1:
        raise ValueError("pr_number must be a positive integer")
    safe_sha = _safe_text(head_sha, field_name="head_sha")
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", safe_sha):
        raise ValueError("head_sha must be a hexadecimal git SHA")
    timestamp = _safe_timestamp(occurred_at)
    safe_task = _safe_text(task_id, field_name="task_id")
    safe_url = _safe_github_url(pr_url)

    append_activity(
        api,
        event_id=f"pr-merged-{pr_number}-{safe_sha[:12]}",
        kind="PR_MERGED",
        occurred_at=timestamp,
        summary=f"Merged Jules PR #{pr_number}",
        task_id=safe_task,
    )
    set_preview(
        api,
        preview_id=f"pr-{pr_number}",
        kind="PULL_REQUEST",
        title=f"Review merged PR #{pr_number}",
        url=safe_url,
        task_id=safe_task,
        updated_at=timestamp,
    )
