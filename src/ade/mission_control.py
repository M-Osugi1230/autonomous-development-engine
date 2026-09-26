from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .activity import ActivityEvent
from .activity_store import ActivityStore
from .checkpoint import CheckpointState, SECRET_PATTERNS
from .checkpoint_store import CheckpointStore
from .decision_store import DecisionStore
from .decisions import DecisionRecord, DecisionStatus
from .preview import PreviewManifest, SAFE_PREVIEW_HOSTS
from .preview_store import PreviewStore
from .state import StateStore


def _redact_display_text(value: str) -> str:
    text = value
    if "Traceback (most recent call last)" in text:
        return "[REDACTED]"
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _optional_metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return _redact_display_text(value) if value else None


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} contains invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class MissionDecisionSummary:
    decision_id: str
    question: str
    options: tuple[str, ...]
    priority: str
    blocking_task_id: str

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "question", "priority", "blocking_task_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))
        if len(self.options) < 2:
            raise ValueError("options must contain at least two values")
        for option in self.options:
            if not isinstance(option, str) or not option.strip():
                raise ValueError("options must contain non-empty strings")

    @classmethod
    def from_record(cls, record: DecisionRecord) -> "MissionDecisionSummary":
        if not isinstance(record, DecisionRecord):
            raise ValueError("record must be a DecisionRecord")
        return cls(
            decision_id=_redact_display_text(record.request.decision_id),
            question=_redact_display_text(record.request.question),
            options=tuple(_redact_display_text(option) for option in record.request.options),
            priority=record.request.priority.value,
            blocking_task_id=_redact_display_text(record.request.blocking_task_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "question": self.question,
            "options": list(self.options),
            "priority": self.priority,
            "blocking_task_id": self.blocking_task_id,
        }


@dataclass(frozen=True, slots=True)
class MissionActivitySummary:
    event_id: str
    kind: str
    occurred_at: str
    summary: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("event_id", "kind", "occurred_at", "summary"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.task_id is not None and (
            not isinstance(self.task_id, str) or not self.task_id.strip()
        ):
            raise ValueError("task_id must be a non-empty string or None")

    @classmethod
    def from_event(cls, event: ActivityEvent) -> "MissionActivitySummary":
        if not isinstance(event, ActivityEvent):
            raise ValueError("event must be an ActivityEvent")
        return cls(
            event_id=_redact_display_text(event.event_id),
            kind=event.kind.value,
            occurred_at=event.occurred_at,
            summary=_redact_display_text(event.summary),
            task_id=(
                _redact_display_text(event.task_id)
                if event.task_id is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "summary": self.summary,
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class MissionPreviewSummary:
    preview_id: str
    kind: str
    title: str
    url: str
    task_id: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "preview_id",
            "kind",
            "title",
            "url",
            "task_id",
            "updated_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname not in SAFE_PREVIEW_HOSTS:
            raise ValueError("preview url must be an allowed HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("preview url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("preview url must not contain query or fragment")

    @classmethod
    def from_manifest(cls, preview: PreviewManifest) -> "MissionPreviewSummary":
        if not isinstance(preview, PreviewManifest):
            raise ValueError("preview must be a PreviewManifest")
        return cls(
            preview_id=_redact_display_text(preview.preview_id),
            kind=preview.kind.value,
            title=_redact_display_text(preview.title),
            url=preview.url,
            task_id=_redact_display_text(preview.task_id),
            updated_at=preview.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "task_id": self.task_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class MissionCheckpointSummary:
    task_id: str
    state: str
    attempt: int
    replan_count: int
    failure_kind: str | None
    resume_after: str | None
    provider_session_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "attempt": self.attempt,
            "replan_count": self.replan_count,
            "failure_kind": self.failure_kind,
            "resume_after": self.resume_after,
            "provider_session_present": self.provider_session_present,
        }


@dataclass(frozen=True, slots=True)
class MissionTelemetrySummary:
    cycles_started: int
    cycles_completed: int
    repair_attempts: int
    human_interrupts: int
    quota_pauses: int

    def __post_init__(self) -> None:
        for field_name in (
            "cycles_started",
            "cycles_completed",
            "repair_attempts",
            "human_interrupts",
            "quota_pauses",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "cycles_started": self.cycles_started,
            "cycles_completed": self.cycles_completed,
            "repair_attempts": self.repair_attempts,
            "human_interrupts": self.human_interrupts,
            "quota_pauses": self.quota_pauses,
        }


@dataclass(frozen=True, slots=True)
class MissionControlSnapshot:
    project_id: str
    project_status: str
    iteration: int
    current_task_id: str | None
    state_updated_at: str | None
    phase: str | None
    milestone: str | None
    completed_tasks: int
    failed_tasks: int
    queue_depth: int
    queue_exhausted: bool
    failure_ledger_count: int
    checkpoint: MissionCheckpointSummary | None
    open_decisions: tuple[MissionDecisionSummary, ...]
    telemetry: MissionTelemetrySummary
    warnings: tuple[str, ...]
    activity: tuple[MissionActivitySummary, ...] = ()
    preview: MissionPreviewSummary | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Mission Control schema_version")
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(self.project_status, str) or not self.project_status.strip():
            raise ValueError("project_status must be a non-empty string")
        for field_name in (
            "iteration",
            "completed_tasks",
            "failed_tasks",
            "queue_depth",
            "failure_ledger_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if type(self.queue_exhausted) is not bool:
            raise ValueError("queue_exhausted must be a bool")
        object.__setattr__(self, "open_decisions", tuple(self.open_decisions))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "activity", tuple(self.activity))
        for item in self.activity:
            if not isinstance(item, MissionActivitySummary):
                raise ValueError("activity must contain MissionActivitySummary values")
        if self.preview is not None and not isinstance(
            self.preview, MissionPreviewSummary
        ):
            raise ValueError("preview must be a MissionPreviewSummary or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_status": self.project_status,
            "iteration": self.iteration,
            "current_task_id": self.current_task_id,
            "state_updated_at": self.state_updated_at,
            "phase": self.phase,
            "milestone": self.milestone,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "queue_depth": self.queue_depth,
            "queue_exhausted": self.queue_exhausted,
            "failure_ledger_count": self.failure_ledger_count,
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint is not None else None,
            "open_decisions": [decision.to_dict() for decision in self.open_decisions],
            "telemetry": self.telemetry.to_dict(),
            "warnings": list(self.warnings),
            "activity": [event.to_dict() for event in self.activity],
            "preview": self.preview.to_dict() if self.preview is not None else None,
        }


def _load_queue_depth(path: Path) -> int:
    payload = _load_json_object(path, label="task queue")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported task queue schema_version")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("task queue tasks must be a list")
    return len(tasks)


def _load_failure_count(path: Path) -> int:
    payload = _load_json_object(path, label="failure ledger")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported failure ledger schema_version")
    failures = payload.get("failures")
    if not isinstance(failures, list):
        raise ValueError("failure ledger failures must be a list")
    return len(failures)


def _load_telemetry(path: Path) -> MissionTelemetrySummary:
    payload = _load_json_object(path, label="metrics ledger")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported metrics ledger schema_version")

    required = (
        "cycles_started",
        "cycles_completed",
        "repair_attempts",
        "human_interrupts",
        "quota_pauses",
    )
    values: dict[str, int] = {}
    for key in required:
        value = payload.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"metrics ledger {key} must be a non-negative integer")
        values[key] = value

    return MissionTelemetrySummary(**values)


def build_mission_control_snapshot(
    root: str | Path = ".",
) -> MissionControlSnapshot:
    root_path = Path(root)
    autodev = root_path / ".autodev"

    state = StateStore(autodev / "state.json").load()
    queue_depth = _load_queue_depth(autodev / "task-queue.json")
    failure_count = _load_failure_count(autodev / "failures.json")
    telemetry = _load_telemetry(autodev / "metrics.json")

    checkpoint_path = autodev / "runtime" / "checkpoint.json"
    checkpoint_summary: MissionCheckpointSummary | None = None
    checkpoint = None
    if checkpoint_path.exists():
        checkpoint = CheckpointStore(checkpoint_path).load()
        checkpoint_summary = MissionCheckpointSummary(
            task_id=_redact_display_text(checkpoint.task_id),
            state=checkpoint.state.value,
            attempt=checkpoint.attempt,
            replan_count=checkpoint.replan_count,
            failure_kind=(
                checkpoint.last_failure_kind.value
                if checkpoint.last_failure_kind is not None
                else None
            ),
            resume_after=checkpoint.resume_after,
            provider_session_present=checkpoint.provider_session_id is not None,
        )

    records = DecisionStore(autodev / "decisions.json").load()
    open_decisions = tuple(
        MissionDecisionSummary.from_record(record)
        for record in records
        if record.status is DecisionStatus.OPEN
    )

    activity = tuple(
        MissionActivitySummary.from_event(event)
        for event in ActivityStore(autodev / "activity.json").recent(20)
    )
    preview_manifest = PreviewStore(autodev / "preview.json").load()
    preview = (
        MissionPreviewSummary.from_manifest(preview_manifest)
        if preview_manifest is not None
        else None
    )

    warnings: list[str] = []
    if telemetry.cycles_completed < state.iteration:
        warnings.append("telemetry metrics lag project iteration")
    if telemetry.cycles_started < telemetry.cycles_completed:
        warnings.append("telemetry cycles_started is lower than cycles_completed")
    if failure_count != len(state.failed_task_ids):
        warnings.append("failure ledger count differs from state failed task count")
    if (
        checkpoint is not None
        and checkpoint.state is not CheckpointState.COMPLETED
        and state.current_task_id is None
    ):
        warnings.append("non-terminal checkpoint exists without a current task")
    if (
        checkpoint is not None
        and checkpoint.state is not CheckpointState.COMPLETED
        and state.current_task_id is not None
        and checkpoint.task_id != state.current_task_id
    ):
        warnings.append("active checkpoint does not match current task")
    if state.status.value == "HUMAN_WAIT" and not open_decisions:
        warnings.append("project is HUMAN_WAIT but no open human decision exists")

    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    queue_exhausted_value = metadata.get("queue_exhausted", False)
    queue_exhausted = (
        queue_exhausted_value if type(queue_exhausted_value) is bool else False
    )

    return MissionControlSnapshot(
        project_id=_redact_display_text(state.project_id),
        project_status=state.status.value,
        iteration=state.iteration,
        current_task_id=(
            _redact_display_text(state.current_task_id)
            if state.current_task_id is not None
            else None
        ),
        state_updated_at=state.updated_at,
        phase=_optional_metadata_text(metadata, "phase"),
        milestone=_optional_metadata_text(metadata, "milestone"),
        completed_tasks=len(state.completed_task_ids),
        failed_tasks=len(state.failed_task_ids),
        queue_depth=queue_depth,
        queue_exhausted=queue_exhausted,
        failure_ledger_count=failure_count,
        checkpoint=checkpoint_summary,
        open_decisions=open_decisions,
        telemetry=telemetry,
        warnings=tuple(warnings),
        activity=activity,
        preview=preview,
    )
