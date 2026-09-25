from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any, Callable

from .providers.base import CodingAgentProvider


class CycleError(RuntimeError):
    """Base ADE cycle failure."""


class CycleFailed(CycleError):
    """The provider reported that the coding task failed."""


class CycleTimedOut(CycleError):
    """The coding task exceeded the configured timeout."""


class HumanInputRequired(CycleError):
    """The provider requires human input before it can continue."""


class CyclePaused(CycleError):
    """The provider paused the session and it must be resumed later."""


@dataclass(frozen=True, slots=True)
class CycleTask:
    task_id: str
    title: str
    prompt: str
    starting_branch: str = "main"
    auto_create_pr: bool = True
    timeout_seconds: int = 1800
    poll_interval_seconds: int = 15

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CycleTask":
        task = cls(
            task_id=str(payload["task_id"]),
            title=str(payload["title"]),
            prompt=str(payload["prompt"]),
            starting_branch=str(payload.get("starting_branch", "main")),
            auto_create_pr=bool(payload.get("auto_create_pr", True)),
            timeout_seconds=int(payload.get("timeout_seconds", 1800)),
            poll_interval_seconds=int(payload.get("poll_interval_seconds", 15)),
        )
        task.validate()
        return task

    def validate(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if not self.starting_branch.strip():
            raise ValueError("starting_branch must not be empty")
        if self.timeout_seconds < 60:
            raise ValueError("timeout_seconds must be >= 60")
        if self.poll_interval_seconds < 5:
            raise ValueError("poll_interval_seconds must be >= 5")


@dataclass(frozen=True, slots=True)
class CycleResult:
    task_id: str
    session_id: str
    session_url: str | None
    state: str
    pull_request_url: str | None


def _session_id(session: dict[str, Any]) -> str:
    identifier = session.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        identifier = name.removeprefix("sessions/")
        if identifier:
            return identifier
    raise CycleError("provider returned a session without an id")


def _pull_request_url(session: dict[str, Any]) -> str | None:
    outputs = session.get("outputs", [])
    if not isinstance(outputs, list):
        return None
    for output in outputs:
        if not isinstance(output, dict):
            continue
        pull_request = output.get("pullRequest")
        if not isinstance(pull_request, dict):
            continue
        url = pull_request.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def run_cycle(
    provider: CodingAgentProvider,
    *,
    task: CycleTask,
    source_name: str,
    sleeper: Callable[[float], None] = sleep,
    clock: Callable[[], float] = monotonic,
) -> CycleResult:
    task.validate()

    session = provider.create_session(
        prompt=task.prompt,
        source=source_name,
        starting_branch=task.starting_branch,
        title=task.title,
        auto_create_pr=task.auto_create_pr,
        require_plan_approval=False,
    )
    session_id = _session_id(session)
    session_url = session.get("url")
    if not isinstance(session_url, str):
        session_url = None

    deadline = clock() + task.timeout_seconds

    while True:
        current = provider.get_session(session_id)
        state = current.get("state")
        if not isinstance(state, str):
            raise CycleError("provider returned a session without state")

        if state == "COMPLETED":
            return CycleResult(
                task_id=task.task_id,
                session_id=session_id,
                session_url=session_url,
                state=state,
                pull_request_url=_pull_request_url(current),
            )

        if state == "FAILED":
            raise CycleFailed(f"session {session_id} failed")
        if state == "AWAITING_USER_FEEDBACK":
            raise HumanInputRequired(f"session {session_id} requires human input")
        if state == "PAUSED":
            raise CyclePaused(f"session {session_id} is paused")

        if clock() >= deadline:
            raise CycleTimedOut(f"session {session_id} exceeded timeout")

        sleeper(task.poll_interval_seconds)
