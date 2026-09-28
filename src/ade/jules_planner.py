from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
import time
from typing import Any, Callable, Protocol


class JulesPlannerError(RuntimeError):
    """A planning-only Jules session failed or violated the planning boundary."""


_REQUIRED_HUMAN_BOUNDARIES = (
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
)
_PATH_TOKEN = re.compile(r"`([^`]+)`|((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)")


class JulesPlannerClient(Protocol):
    def create_session(
        self,
        *,
        prompt: str,
        source: str,
        starting_branch: str,
        title: str | None,
        auto_create_pr: bool,
        require_plan_approval: bool,
    ) -> dict[str, Any]:
        ...

    def get_session(self, session_id: str) -> dict[str, Any]:
        ...

    def list_activities(
        self,
        session_id: str,
        *,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    def send_message(self, session_id: str, prompt: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class JulesPlannerConfig:
    source_name: str
    starting_branch: str = "main"
    title: str = "ADE autonomous planning"
    poll_interval_seconds: float = 5.0
    max_plan_polls: int = 120
    max_structured_polls: int = 36
    activity_404_retries: int = 6
    allowed_path_prefixes: tuple[str, ...] = ()
    required_human_boundaries: tuple[str, ...] = _REQUIRED_HUMAN_BOUNDARIES

    def __post_init__(self) -> None:
        if not isinstance(self.source_name, str) or not self.source_name.strip():
            raise ValueError("source_name must be non-empty")
        if not isinstance(self.starting_branch, str) or not self.starting_branch.strip():
            raise ValueError("starting_branch must be non-empty")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be non-empty")
        if not isinstance(self.poll_interval_seconds, (int, float)) or self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        for value in (
            self.max_plan_polls,
            self.max_structured_polls,
            self.activity_404_retries,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("planner retry/poll budgets must be positive integers")
        for prefix in self.allowed_path_prefixes:
            if not isinstance(prefix, str) or not prefix.strip():
                raise ValueError("allowed_path_prefixes must contain non-empty strings")
            path = PurePosixPath(prefix)
            if prefix.startswith("/") or ".." in path.parts or str(path) != prefix.rstrip("/"):
                raise ValueError(f"invalid allowed planner path prefix: {prefix}")
        if not self.required_human_boundaries:
            raise ValueError("required_human_boundaries must not be empty")


def _session_id(session: dict[str, Any]) -> str:
    value = session.get("id")
    if isinstance(value, str) and value.strip():
        return value
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        suffix = name.removeprefix("sessions/")
        if suffix and "/" not in suffix:
            return suffix
    raise JulesPlannerError("Jules planner session did not return an id")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text.strip():
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _agent_messages(activities: list[dict[str, Any]]) -> tuple[str, ...]:
    messages: list[str] = []
    for activity in activities:
        event = activity.get("agentMessaged")
        if not isinstance(event, dict):
            continue
        value = event.get("agentMessage")
        if isinstance(value, str) and value.strip():
            messages.append(value.strip())
    return tuple(messages)


def _plan_generated_payloads(activities: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    plans: list[dict[str, Any]] = []
    for activity in activities:
        event = activity.get("planGenerated")
        if not isinstance(event, dict):
            continue
        plan = event.get("plan")
        if isinstance(plan, dict):
            plans.append(plan)
    return tuple(plans)


def extract_structured_proposal(
    activities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(_agent_messages(activities)):
        payload = _extract_json_object(message)
        if payload is not None:
            return payload

    for plan in reversed(_plan_generated_payloads(activities)):
        for step in plan.get("steps", []):
            if not isinstance(step, dict):
                continue
            for field in ("description", "title"):
                value = step.get(field)
                if isinstance(value, str):
                    payload = _extract_json_object(value)
                    if payload is not None:
                        return payload
    return None


def latest_plan_steps(
    activities: list[dict[str, Any]],
) -> tuple[dict[str, str], ...]:
    plans = _plan_generated_payloads(activities)
    if not plans:
        return ()
    raw_steps = plans[-1].get("steps", [])
    if not isinstance(raw_steps, list):
        return ()
    steps: list[dict[str, str]] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title")
        description = raw.get("description")
        if not isinstance(title, str) or not title.strip():
            continue
        steps.append(
            {
                "title": title.strip(),
                "description": description.strip() if isinstance(description, str) else "",
            }
        )
    return tuple(steps)


def _path_within(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def _step_paths(
    step: dict[str, str],
    *,
    allowed_path_prefixes: tuple[str, ...],
) -> tuple[str, ...]:
    if not allowed_path_prefixes:
        return ()
    text = f"{step.get('title', '')} {step.get('description', '')}"
    paths: list[str] = []
    for match in _PATH_TOKEN.finditer(text):
        candidate = (match.group(1) or match.group(2) or "").strip()
        candidate = candidate.rstrip(".,;:)")
        if not candidate or candidate.startswith("/"):
            continue
        parsed = PurePosixPath(candidate)
        if ".." in parsed.parts or str(parsed) != candidate:
            continue
        if not any(_path_within(candidate, prefix) for prefix in allowed_path_prefixes):
            continue
        if candidate not in paths:
            paths.append(candidate)
    return tuple(paths)


def derive_proposal_from_plan_steps(
    *,
    goal: str,
    steps: tuple[dict[str, str], ...],
    allowed_path_prefixes: tuple[str, ...],
    required_human_boundaries: tuple[str, ...] = _REQUIRED_HUMAN_BOUNDARIES,
) -> dict[str, Any] | None:
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be non-empty")
    if not allowed_path_prefixes:
        return None

    tasks: list[dict[str, Any]] = []
    previous_key: str | None = None
    for index, step in enumerate(steps, 1):
        paths = _step_paths(
            step,
            allowed_path_prefixes=allowed_path_prefixes,
        )
        if not paths:
            continue
        title = " ".join(str(step.get("title", "")).split())
        description = " ".join(str(step.get("description", "")).split())
        if not title:
            continue
        outcome = description or title
        key = f"jules-step-{len(tasks) + 1:03d}"
        dependencies = [previous_key] if previous_key is not None else []
        acceptance = [
            outcome,
            "Repository CI remains green",
        ]
        tasks.append(
            {
                "key": key,
                "title": title,
                "outcome": outcome,
                "depends_on": dependencies,
                "allowed_paths": list(paths),
                "acceptance": acceptance,
                "human_only": False,
                "human_reason": None,
            }
        )
        previous_key = key

    if not tasks:
        return None
    return {
        "schema_version": 1,
        "goal": " ".join(goal.split()),
        "tasks": tasks,
        "human_boundaries": list(required_human_boundaries),
    }


def _goal_from_planner_prompt(prompt: str) -> str:
    marker = "Goal: "
    start = prompt.find(marker)
    if start < 0:
        raise JulesPlannerError("trusted planner prompt does not contain Goal")
    start += len(marker)
    end = prompt.find(". Trusted writable roots:", start)
    if end < 0:
        raise JulesPlannerError("trusted planner prompt goal boundary is missing")
    goal = prompt[start:end].strip()
    if not goal:
        raise JulesPlannerError("trusted planner prompt goal is empty")
    return goal


def _structured_followup(original_prompt: str) -> str:
    return (
        "Remain in planning-only mode. Do NOT approve the plan, implement code, modify files, "
        "or create a pull request. Reply with exactly one JSON object and no markdown fences. "
        "The JSON must satisfy the schema and trusted bounds from the original planning request. "
        "It must include schema_version=1, the exact original goal, tasks with key/title/outcome/"
        "depends_on/allowed_paths/acceptance/human_only/human_reason, and mandatory human_boundaries. "
        "Use only repository-relative paths you actually inferred from the repository. "
        "Original trusted planning request follows:\n\n"
        + original_prompt
    )


class JulesPlanningProvider:
    """PlanningProvider adapter that never approves or executes a Jules plan."""

    def __init__(
        self,
        client: JulesPlannerClient,
        config: JulesPlannerConfig,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._config = config
        self._sleep = sleeper
        self.last_plan_steps: tuple[dict[str, str], ...] = ()
        self.last_observed_state: str | None = None
        self.last_proposal_mode: str | None = None

    def _activities(self, session_id: str) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self._config.activity_404_retries + 1):
            try:
                return self._client.list_activities(session_id, page_size=100)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "404" not in message and "not found" not in message.casefold():
                    raise
                if attempt >= self._config.activity_404_retries:
                    raise
                self._sleep(min(float(attempt * 2), 10.0))
        assert last_error is not None
        raise last_error

    def _wait_for_plan(self, session_id: str) -> str:
        for _ in range(self._config.max_plan_polls):
            current = self._client.get_session(session_id)
            state = current.get("state")
            if not isinstance(state, str):
                raise JulesPlannerError("Jules planner session returned no state")
            self.last_observed_state = state

            if state == "AWAITING_PLAN_APPROVAL":
                return state
            if state in {"FAILED", "PAUSED", "AWAITING_USER_FEEDBACK"}:
                raise JulesPlannerError(f"Jules planner stopped in {state}")
            if state in {"IN_PROGRESS", "COMPLETED"}:
                raise JulesPlannerError(
                    f"planning-only session crossed execution boundary: {state}"
                )
            self._sleep(self._config.poll_interval_seconds)

        raise JulesPlannerError("Jules planner did not reach plan approval boundary in time")

    def _wait_for_structured_proposal(
        self,
        session_id: str,
        *,
        baseline_message_count: int,
    ) -> dict[str, Any]:
        for _ in range(self._config.max_structured_polls):
            current = self._client.get_session(session_id)
            state = current.get("state")
            if not isinstance(state, str):
                raise JulesPlannerError("Jules planner session returned no state")
            self.last_observed_state = state
            if state == "IN_PROGRESS":
                raise JulesPlannerError("planning-only session began implementation without approval")
            if state in {"FAILED", "PAUSED"}:
                raise JulesPlannerError(f"Jules planner stopped in {state}")

            activities = self._activities(session_id)
            messages = _agent_messages(activities)
            for message in reversed(messages[baseline_message_count:]):
                payload = _extract_json_object(message)
                if payload is not None:
                    return payload

            self._sleep(self._config.poll_interval_seconds)

        raise JulesPlannerError("Jules planner did not return a structured proposal in time")

    def propose(self, prompt: str) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("planner prompt must be non-empty")

        session = self._client.create_session(
            prompt=prompt,
            source=self._config.source_name,
            starting_branch=self._config.starting_branch,
            title=self._config.title,
            auto_create_pr=False,
            require_plan_approval=True,
        )
        session_id = _session_id(session)
        self._wait_for_plan(session_id)

        activities = self._activities(session_id)
        self.last_plan_steps = latest_plan_steps(activities)
        immediate = extract_structured_proposal(activities)
        if immediate is not None:
            self.last_proposal_mode = "structured"
            return immediate

        if self._config.allowed_path_prefixes:
            derived = derive_proposal_from_plan_steps(
                goal=_goal_from_planner_prompt(prompt),
                steps=self.last_plan_steps,
                allowed_path_prefixes=self._config.allowed_path_prefixes,
                required_human_boundaries=self._config.required_human_boundaries,
            )
            if derived is not None:
                self.last_proposal_mode = "derived-plan-steps"
                return derived

        before_messages = _agent_messages(activities)
        self._client.send_message(session_id, _structured_followup(prompt))
        proposal = self._wait_for_structured_proposal(
            session_id,
            baseline_message_count=len(before_messages),
        )

        final = self._client.get_session(session_id)
        final_state = final.get("state")
        self.last_observed_state = final_state if isinstance(final_state, str) else None
        if final_state == "IN_PROGRESS":
            raise JulesPlannerError("Jules planner crossed execution boundary after follow-up")
        self.last_proposal_mode = "followup-structured"
        return proposal
