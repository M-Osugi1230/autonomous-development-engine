from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Protocol

from .accepted_plan import AcceptedPlan
from .checkpoint import SECRET_PATTERNS
from .development_plan import DevelopmentPlan, PlannedTask


_REQUIRED_HUMAN_BOUNDARIES = (
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
)
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PlannerValidationError(ValueError):
    """Trusted deterministic planner validation failure."""


class PlannerDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    HUMAN_WAIT = "HUMAN_WAIT"


@dataclass(frozen=True, slots=True)
class PlannerTaskProposal:
    key: str
    title: str
    outcome: str
    depends_on: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    acceptance: tuple[str, ...]
    human_only: bool = False
    human_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlannerProposal:
    goal: str
    tasks: tuple[PlannerTaskProposal, ...]
    human_boundaries: tuple[str, ...]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannerProposal":
        if not isinstance(payload, dict):
            raise PlannerValidationError("planner proposal must be a JSON object")
        allowed_top = {"schema_version", "goal", "tasks", "human_boundaries"}
        unknown = set(payload) - allowed_top
        if unknown:
            raise PlannerValidationError(f"unknown planner proposal fields: {sorted(unknown)}")
        if payload.get("schema_version") != 1:
            raise PlannerValidationError("planner proposal schema_version must be 1")
        raw_tasks = payload.get("tasks")
        raw_boundaries = payload.get("human_boundaries")
        if not isinstance(raw_tasks, list):
            raise PlannerValidationError("planner proposal tasks must be a list")
        if not isinstance(raw_boundaries, list):
            raise PlannerValidationError("planner proposal human_boundaries must be a list")

        tasks: list[PlannerTaskProposal] = []
        task_fields = {
            "key",
            "title",
            "outcome",
            "depends_on",
            "allowed_paths",
            "acceptance",
            "human_only",
            "human_reason",
        }
        for index, raw in enumerate(raw_tasks, 1):
            if not isinstance(raw, dict):
                raise PlannerValidationError(f"planner task {index} must be an object")
            unknown_task = set(raw) - task_fields
            if unknown_task:
                raise PlannerValidationError(
                    f"unknown planner task {index} fields: {sorted(unknown_task)}"
                )
            depends_on = raw.get("depends_on", [])
            allowed_paths = raw.get("allowed_paths", [])
            acceptance = raw.get("acceptance", [])
            if not isinstance(depends_on, list):
                raise PlannerValidationError(f"planner task {index} depends_on must be a list")
            if not isinstance(allowed_paths, list):
                raise PlannerValidationError(f"planner task {index} allowed_paths must be a list")
            if not isinstance(acceptance, list):
                raise PlannerValidationError(f"planner task {index} acceptance must be a list")
            human_only = raw.get("human_only", False)
            if type(human_only) is not bool:
                raise PlannerValidationError(f"planner task {index} human_only must be a bool")
            human_reason = raw.get("human_reason")
            if human_reason is not None and not isinstance(human_reason, str):
                raise PlannerValidationError(f"planner task {index} human_reason must be a string or null")
            tasks.append(
                PlannerTaskProposal(
                    key=str(raw.get("key", "")),
                    title=str(raw.get("title", "")),
                    outcome=str(raw.get("outcome", "")),
                    depends_on=tuple(str(item) for item in depends_on),
                    allowed_paths=tuple(str(item) for item in allowed_paths),
                    acceptance=tuple(str(item) for item in acceptance),
                    human_only=human_only,
                    human_reason=human_reason,
                )
            )
        return cls(
            goal=str(payload.get("goal", "")),
            tasks=tuple(tasks),
            human_boundaries=tuple(str(item) for item in raw_boundaries),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "goal": _normalize_text(self.goal),
            "tasks": [
                {
                    "key": task.key,
                    "title": _normalize_text(task.title),
                    "outcome": _normalize_text(task.outcome),
                    "depends_on": list(task.depends_on),
                    "allowed_paths": list(task.allowed_paths),
                    "acceptance": [_normalize_text(item) for item in task.acceptance],
                    "human_only": task.human_only,
                    "human_reason": (
                        _normalize_text(task.human_reason)
                        if task.human_reason is not None and task.human_reason.strip()
                        else None
                    ),
                }
                for task in self.tasks
            ],
            "human_boundaries": [_normalize_text(item) for item in self.human_boundaries],
        }

    def fingerprint(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PlannerPolicy:
    allowed_path_prefixes: tuple[str, ...]
    protected_path_prefixes: tuple[str, ...] = (
        ".github",
        ".autodev",
        ".env",
        "secrets",
        "credentials",
    )
    required_human_boundaries: tuple[str, ...] = _REQUIRED_HUMAN_BOUNDARIES
    min_tasks: int = 1
    max_tasks: int = 8
    max_paths_per_task: int = 4
    max_acceptance_per_task: int = 6
    max_text_chars: int = 2000
    require_concrete_file_paths: bool = True
    extensionless_file_names: tuple[str, ...] = (
        "Dockerfile",
        "Makefile",
        "Procfile",
    )
    planner_meta_markers: tuple[str, ...] = (
        "json proposal",
        "schema_version",
        "define tasks",
        "human_boundaries",
        "allowed_paths",
        "acceptance checks",
        "planning request",
    )
    sensitive_action_markers: tuple[str, ...] = (
        "delete repository",
        "drop database",
        "production deploy",
        "deploy to production",
        "rotate secret",
        "revoke credential",
        "purchase ",
        "make payment",
        "send email",
        "publish externally",
    )

    def __post_init__(self) -> None:
        if not self.allowed_path_prefixes:
            raise PlannerValidationError("planner policy requires allowed_path_prefixes")
        for value in (
            self.min_tasks,
            self.max_tasks,
            self.max_paths_per_task,
            self.max_acceptance_per_task,
            self.max_text_chars,
        ):
            if type(value) is not int or value < 1:
                raise PlannerValidationError("planner policy budgets must be positive integers")
        if self.min_tasks > self.max_tasks:
            raise PlannerValidationError("planner policy min_tasks must not exceed max_tasks")
        if type(self.require_concrete_file_paths) is not bool:
            raise PlannerValidationError("require_concrete_file_paths must be a bool")
        for prefix in self.allowed_path_prefixes + self.protected_path_prefixes:
            _validate_policy_prefix(prefix)
        if not self.required_human_boundaries:
            raise PlannerValidationError("planner policy requires human boundaries")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "protected_path_prefixes": list(self.protected_path_prefixes),
            "required_human_boundaries": list(self.required_human_boundaries),
            "min_tasks": self.min_tasks,
            "max_tasks": self.max_tasks,
            "max_paths_per_task": self.max_paths_per_task,
            "max_acceptance_per_task": self.max_acceptance_per_task,
            "max_text_chars": self.max_text_chars,
            "require_concrete_file_paths": self.require_concrete_file_paths,
            "extensionless_file_names": list(self.extensionless_file_names),
            "planner_meta_markers": list(self.planner_meta_markers),
            "sensitive_action_markers": list(self.sensitive_action_markers),
        }

    def fingerprint(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ValidatedPlannerProposal:
    disposition: PlannerDisposition
    proposal_fingerprint: str
    policy_fingerprint: str
    plan: DevelopmentPlan | None = None
    human_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is PlannerDisposition.ACCEPTED and self.plan is None:
            raise PlannerValidationError("accepted planner result requires a plan")
        if self.disposition is PlannerDisposition.HUMAN_WAIT and self.plan is not None:
            raise PlannerValidationError("HUMAN_WAIT planner result cannot contain an executable plan")


@dataclass(frozen=True, slots=True)
class AutonomousPlanningResult:
    raw_proposal: dict[str, Any]
    validated: ValidatedPlannerProposal
    accepted_plan: AcceptedPlan | None


class PlanningProvider(Protocol):
    def propose(self, prompt: str) -> dict[str, Any]:
        ...


def _normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise PlannerValidationError("planner text values must be strings")
    normalized = " ".join(value.split())
    if not normalized:
        raise PlannerValidationError("planner text values must not be empty")
    return normalized


def _validate_policy_prefix(prefix: str) -> None:
    if not isinstance(prefix, str) or not prefix.strip():
        raise PlannerValidationError("planner path prefixes must be non-empty strings")
    if "\\" in prefix or prefix.startswith("/"):
        raise PlannerValidationError(f"invalid planner path prefix: {prefix}")
    path = PurePosixPath(prefix)
    if ".." in path.parts or str(path) != prefix.rstrip("/"):
        raise PlannerValidationError(f"planner path prefix must be normalized: {prefix}")


def _path_within(path: str, prefix: str) -> bool:
    normalized_prefix = prefix.rstrip("/")
    return path == normalized_prefix or path.startswith(normalized_prefix + "/")


def _validate_path(path: str, policy: PlannerPolicy) -> str:
    if not isinstance(path, str) or not path.strip():
        raise PlannerValidationError("planner paths must be non-empty strings")
    if "\\" in path or path.startswith("/"):
        raise PlannerValidationError(f"unsafe planner path: {path}")
    parsed = PurePosixPath(path)
    normalized = str(parsed)
    if ".." in parsed.parts or normalized != path:
        raise PlannerValidationError(f"planner path must be normalized: {path}")
    if any(_path_within(path, prefix) for prefix in policy.protected_path_prefixes):
        raise PlannerValidationError(f"protected planner path: {path}")
    matching_roots = [
        prefix
        for prefix in policy.allowed_path_prefixes
        if _path_within(path, prefix)
    ]
    if not matching_roots:
        raise PlannerValidationError(f"planner path outside trusted roots: {path}")
    if policy.require_concrete_file_paths:
        if any(path == prefix.rstrip("/") for prefix in matching_roots):
            raise PlannerValidationError(
                f"planner path must name a concrete file, not a trusted root: {path}"
            )
        basename = parsed.name
        if not parsed.suffix and basename not in policy.extensionless_file_names:
            raise PlannerValidationError(
                f"planner path must name a concrete file: {path}"
            )
    return path


def _bounded_text(value: str, policy: PlannerPolicy, *, label: str) -> str:
    normalized = _normalize_text(value)
    if len(normalized) > policy.max_text_chars:
        raise PlannerValidationError(f"{label} exceeds trusted text budget")
    for pattern in SECRET_PATTERNS:
        if pattern.search(normalized):
            raise PlannerValidationError(f"{label} contains a forbidden secret pattern")
    return normalized


def _validate_task_semantics(
    *,
    task: PlannerTaskProposal,
    goal: str,
    policy: PlannerPolicy,
) -> None:
    task_text = " ".join(
        [task.title, task.outcome, *task.acceptance]
    ).casefold()
    goal_text = goal.casefold()
    for marker in policy.planner_meta_markers:
        normalized = marker.casefold().strip()
        if normalized and normalized in task_text and normalized not in goal_text:
            raise PlannerValidationError(
                f"task {task.key} describes planner protocol instead of repository work: {marker}"
            )


def _human_wait_reasons(
    proposal: PlannerProposal,
    policy: PlannerPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    markers = tuple(item.casefold() for item in policy.sensitive_action_markers)
    for task in proposal.tasks:
        if task.human_only:
            reason = (
                _bounded_text(task.human_reason, policy, label=f"task {task.key} human_reason")
                if task.human_reason is not None and task.human_reason.strip()
                else f"{task.key} marked human_only"
            )
            reasons.append(reason)
        searchable = f"{task.title} {task.outcome}".casefold()
        for marker in markers:
            if marker and marker in searchable:
                reasons.append(f"{task.key} matched human-only action marker: {marker}")
                break
    return tuple(dict.fromkeys(reasons))


def validate_planner_proposal(
    *,
    high_level_goal: str,
    proposal_payload: dict[str, Any],
    policy: PlannerPolicy,
    id_prefix: str = "auto",
) -> ValidatedPlannerProposal:
    goal = _bounded_text(high_level_goal, policy, label="high-level goal")
    if not isinstance(id_prefix, str) or not _KEY_PATTERN.fullmatch(id_prefix):
        raise PlannerValidationError("id_prefix must be a safe identifier")

    proposal = PlannerProposal.from_dict(proposal_payload)
    if _bounded_text(proposal.goal, policy, label="proposal goal") != goal:
        raise PlannerValidationError("planner proposal goal does not match the high-level goal")
    if len(proposal.tasks) < policy.min_tasks or len(proposal.tasks) > policy.max_tasks:
        raise PlannerValidationError(
            "planner proposal violates trusted task-count budget"
        )

    normalized_required = {_normalize_text(item) for item in policy.required_human_boundaries}
    normalized_boundaries = {_normalize_text(item) for item in proposal.human_boundaries}
    missing_boundaries = sorted(normalized_required - normalized_boundaries)
    if missing_boundaries:
        raise PlannerValidationError(
            f"planner proposal is missing mandatory human boundaries: {missing_boundaries}"
        )

    keys: list[str] = []
    for index, task in enumerate(proposal.tasks, 1):
        if not _KEY_PATTERN.fullmatch(task.key):
            raise PlannerValidationError(f"planner task {index} key is invalid")
        if task.key in keys:
            raise PlannerValidationError(f"duplicate planner task key: {task.key}")
        keys.append(task.key)
        _validate_task_semantics(task=task, goal=goal, policy=policy)
        _bounded_text(task.title, policy, label=f"task {task.key} title")
        _bounded_text(task.outcome, policy, label=f"task {task.key} outcome")
        if not task.allowed_paths or len(task.allowed_paths) > policy.max_paths_per_task:
            raise PlannerValidationError(f"task {task.key} violates trusted path budget")
        if not task.acceptance or len(task.acceptance) > policy.max_acceptance_per_task:
            raise PlannerValidationError(f"task {task.key} violates trusted acceptance budget")
        for path in task.allowed_paths:
            _validate_path(path, policy)
        for item in task.acceptance:
            _bounded_text(item, policy, label=f"task {task.key} acceptance")

    key_index = {key: index for index, key in enumerate(keys)}
    for index, task in enumerate(proposal.tasks):
        seen: set[str] = set()
        for dependency in task.depends_on:
            if dependency in seen:
                raise PlannerValidationError(f"duplicate dependency {dependency} for {task.key}")
            seen.add(dependency)
            if dependency not in key_index:
                raise PlannerValidationError(f"unknown dependency {dependency} for {task.key}")
            if dependency == task.key:
                raise PlannerValidationError(f"self dependency for {task.key}")
            if key_index[dependency] >= index:
                raise PlannerValidationError(
                    f"forward or cyclic dependency {dependency} for {task.key}"
                )

    human_reasons = _human_wait_reasons(proposal, policy)
    proposal_fingerprint = proposal.fingerprint()
    policy_fingerprint = policy.fingerprint()
    if human_reasons:
        return ValidatedPlannerProposal(
            disposition=PlannerDisposition.HUMAN_WAIT,
            proposal_fingerprint=proposal_fingerprint,
            policy_fingerprint=policy_fingerprint,
            human_reasons=human_reasons,
        )

    task_ids = {key: f"{id_prefix}-{index:03d}" for index, key in enumerate(keys, 1)}
    planned: list[PlannedTask] = []
    for task in proposal.tasks:
        title = _bounded_text(task.title, policy, label=f"task {task.key} title")
        outcome = _bounded_text(task.outcome, policy, label=f"task {task.key} outcome")
        prompt = f"Goal: {goal}\nOutcome: {outcome}"
        planned.append(
            PlannedTask(
                task_id=task_ids[task.key],
                title=title,
                prompt=prompt,
                depends_on=tuple(task_ids[item] for item in task.depends_on),
                allowed_paths=tuple(_validate_path(path, policy) for path in task.allowed_paths),
                acceptance=tuple(
                    _bounded_text(item, policy, label=f"task {task.key} acceptance")
                    for item in task.acceptance
                ),
            )
        )
    plan = DevelopmentPlan(
        goal=goal,
        tasks=tuple(planned),
        human_boundaries=tuple(
            dict.fromkeys(_normalize_text(item) for item in proposal.human_boundaries)
        ),
    )
    plan.validate()
    return ValidatedPlannerProposal(
        disposition=PlannerDisposition.ACCEPTED,
        proposal_fingerprint=proposal_fingerprint,
        policy_fingerprint=policy_fingerprint,
        plan=plan,
    )


def accept_validated_proposal(validated: ValidatedPlannerProposal) -> AcceptedPlan:
    if not isinstance(validated, ValidatedPlannerProposal):
        raise PlannerValidationError("validated planner result is required")
    if validated.disposition is not PlannerDisposition.ACCEPTED or validated.plan is None:
        raise PlannerValidationError("only an ACCEPTED trusted planner result may become AcceptedPlan")
    return AcceptedPlan.accept(validated.plan)


def build_planner_prompt(high_level_goal: str, policy: PlannerPolicy) -> str:
    goal = _bounded_text(high_level_goal, policy, label="high-level goal")
    roots = ", ".join(policy.allowed_path_prefixes)
    boundaries = "; ".join(policy.required_human_boundaries)
    return (
        "You are an untrusted planning component. Do not implement code or claim completion. "
        "Return only one JSON object matching schema_version=1. "
        f"Goal: {goal}. "
        f"Trusted writable roots: {roots}. "
        f"Use between {policy.min_tasks} and {policy.max_tasks} tasks. "
        f"Maximum paths per task: {policy.max_paths_per_task}; "
        f"maximum acceptance checks per task: {policy.max_acceptance_per_task}. "
        "Each task must describe repository implementation, tests, or documentation needed to achieve the Goal; "
        "never create a task about planning, JSON formatting, schemas, or producing the proposal itself. "
        "Each task must contain key, title, outcome, depends_on, allowed_paths, acceptance, "
        "human_only, and human_reason. Dependencies use task keys. "
        "allowed_paths must name concrete repository files, not directories or trusted root names. "
        "The proposal must include human_boundaries and must include: "
        f"{boundaries}. Mark any task crossing a human-only boundary with human_only=true."
    )


def plan_high_level_goal(
    provider: PlanningProvider,
    *,
    high_level_goal: str,
    policy: PlannerPolicy,
    id_prefix: str = "auto",
) -> AutonomousPlanningResult:
    prompt = build_planner_prompt(high_level_goal, policy)
    raw = provider.propose(prompt)
    if not isinstance(raw, dict):
        raise PlannerValidationError("planning provider must return a JSON object")
    validated = validate_planner_proposal(
        high_level_goal=high_level_goal,
        proposal_payload=raw,
        policy=policy,
        id_prefix=id_prefix,
    )
    accepted = (
        accept_validated_proposal(validated)
        if validated.disposition is PlannerDisposition.ACCEPTED
        else None
    )
    return AutonomousPlanningResult(
        raw_proposal=raw,
        validated=validated,
        accepted_plan=accepted,
    )
