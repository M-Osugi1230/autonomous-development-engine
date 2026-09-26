from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .checkpoint import CheckpointState, TaskCheckpoint


class ResumeAction(StrEnum):
    RESUME = "RESUME"
    WAIT = "WAIT"
    REPLAN = "REPLAN"
    NOOP = "NOOP"


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    action: ResumeAction
    reason: str

    def __post_init__(self) -> None:
        try:
            action_enum = ResumeAction(self.action)
        except (ValueError, TypeError):
            raise ValueError(f"invalid action: {self.action}")
        object.__setattr__(self, "action", action_enum)

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


def decide_resume(checkpoint: TaskCheckpoint, now: datetime) -> ResumeDecision:
    if not isinstance(checkpoint, TaskCheckpoint):
        raise ValueError("checkpoint must be an instance of TaskCheckpoint")

    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime instance")

    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be a timezone-aware datetime")

    now_utc = now.astimezone(timezone.utc)

    state = checkpoint.state

    if state is CheckpointState.PAUSED_QUOTA:
        if checkpoint.resume_after is None:
            return ResumeDecision(
                action=ResumeAction.WAIT,
                reason="Quota paused checkpoint has no resume_after deadline set",
            )
        try:
            dt = datetime.fromisoformat(checkpoint.resume_after)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid resume_after timestamp: {checkpoint.resume_after}") from exc

        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            dt_utc = dt.replace(tzinfo=timezone.utc)
        else:
            dt_utc = dt.astimezone(timezone.utc)

        if now_utc >= dt_utc:
            return ResumeDecision(
                action=ResumeAction.RESUME,
                reason=f"Quota pause deadline {checkpoint.resume_after} reached",
            )
        return ResumeDecision(
            action=ResumeAction.WAIT,
            reason=f"Quota pause deadline {checkpoint.resume_after} has not been reached yet",
        )

    if state is CheckpointState.HUMAN_WAIT:
        return ResumeDecision(
            action=ResumeAction.WAIT,
            reason="HUMAN_WAIT checkpoint requires manual intervention and cannot auto-resume",
        )

    if state is CheckpointState.REPLAN:
        return ResumeDecision(
            action=ResumeAction.REPLAN,
            reason="REPLAN checkpoint requires replanning",
        )

    if state is CheckpointState.RUNNING:
        if checkpoint.provider_session_id:
            return ResumeDecision(
                action=ResumeAction.RESUME,
                reason="RUNNING task with provider session can be resumed",
            )
        return ResumeDecision(
            action=ResumeAction.WAIT,
            reason="RUNNING task without provider session cannot be auto-resumed",
        )

    if state in (CheckpointState.FAILED, CheckpointState.COMPLETED):
        return ResumeDecision(
            action=ResumeAction.NOOP,
            reason=f"Terminal state {state.value} requires no action",
        )

    raise ValueError(f"unhandled checkpoint state: {state}")
