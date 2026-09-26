from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .activity import ActivityEvent


SCHEMA_VERSION = 1
DEFAULT_ACTIVITY_PATH = Path(".autodev/activity.json")


class ActivityStore:
    """Atomic append-only activity ledger with idempotent event IDs."""

    def __init__(self, path: str | Path = DEFAULT_ACTIVITY_PATH) -> None:
        self.path = Path(path)

    def load(self) -> tuple[ActivityEvent, ...]:
        if not self.path.exists():
            return ()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"activity store contains invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("activity store must contain a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported activity schema_version: {payload.get('schema_version')}"
            )
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ValueError("activity store events must be a list")

        events: list[ActivityEvent] = []
        seen: set[str] = set()
        for raw in raw_events:
            if not isinstance(raw, dict):
                raise ValueError("activity events must be JSON objects")
            event = ActivityEvent.from_dict(raw)
            if event.event_id in seen:
                raise ValueError(f"duplicate activity event_id: {event.event_id}")
            seen.add(event.event_id)
            events.append(event)
        return tuple(events)

    def save(self, events: tuple[ActivityEvent, ...] | list[ActivityEvent]) -> None:
        if not isinstance(events, (tuple, list)):
            raise TypeError("events must be a tuple or list")

        normalized: list[ActivityEvent] = []
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, ActivityEvent):
                raise TypeError("events must contain only ActivityEvent values")
            if event.event_id in seen:
                raise ValueError(f"duplicate activity event_id: {event.event_id}")
            seen.add(event.event_id)
            normalized.append(event)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "events": [event.to_dict() for event in normalized],
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

    def append(self, event: ActivityEvent) -> ActivityEvent:
        if not isinstance(event, ActivityEvent):
            raise TypeError("event must be an ActivityEvent")

        events = list(self.load())
        for existing in events:
            if existing.event_id != event.event_id:
                continue
            if existing == event:
                return existing
            raise ValueError(f"activity event_id conflict: {event.event_id}")

        events.append(event)
        self.save(events)
        return event

    def recent(self, limit: int = 20) -> tuple[ActivityEvent, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        events = self.load()
        return tuple(reversed(events[-limit:]))
