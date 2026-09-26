from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PILOT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40,64}$")


class PilotAction(StrEnum):
    READ = "READ"
    CREATE_BRANCH = "CREATE_BRANCH"
    MODIFY_FILES = "MODIFY_FILES"
    RUN_VALIDATION = "RUN_VALIDATION"
    OPEN_PULL_REQUEST = "OPEN_PULL_REQUEST"
    COMMENT = "COMMENT"


@dataclass(frozen=True, slots=True)
class PilotTarget:
    repository: str
    base_branch: str
    baseline_sha: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository must be in OWNER/REPO form")
        if not isinstance(self.base_branch, str) or not self.base_branch.strip():
            raise ValueError("base_branch must be a non-empty string")
        if self.base_branch != self.base_branch.strip():
            raise ValueError("base_branch must not contain leading or trailing whitespace")
        if not isinstance(self.baseline_sha, str) or not _SHA.fullmatch(self.baseline_sha):
            raise ValueError("baseline_sha must be a 40-64 character hexadecimal Git SHA")
        object.__setattr__(self, "baseline_sha", self.baseline_sha.lower())

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "base_branch": self.base_branch,
            "baseline_sha": self.baseline_sha,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotTarget":
        if not isinstance(payload, dict):
            raise ValueError("pilot target must be a JSON object")
        required = {"repository", "base_branch", "baseline_sha"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"pilot target missing required keys: {sorted(missing)}")
        return cls(
            repository=payload["repository"],
            base_branch=payload["base_branch"],
            baseline_sha=payload["baseline_sha"],
        )


@dataclass(frozen=True, slots=True)
class PilotAcceptanceCheck:
    check_id: str
    command: str
    timeout_seconds: int = 900

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not _PILOT_ID.fullmatch(self.check_id):
            raise ValueError("check_id must be a lowercase slug")
        if not isinstance(self.command, str) or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if self.command != self.command.strip():
            raise ValueError("command must not contain leading or trailing whitespace")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be an integer between 1 and 3600")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "command": self.command,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotAcceptanceCheck":
        if not isinstance(payload, dict):
            raise ValueError("acceptance check must be a JSON object")
        if "check_id" not in payload or "command" not in payload:
            raise ValueError("acceptance check requires check_id and command")
        return cls(
            check_id=payload["check_id"],
            command=payload["command"],
            timeout_seconds=payload.get("timeout_seconds", 900),
        )


def _normalize_paths(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must be an iterable of relative path prefixes")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError(f"{field} must be iterable") from exc

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in iterator:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        value = raw.strip().replace("\\", "/")
        if value.startswith("/") or value.startswith("./"):
            raise ValueError(f"{field} paths must be repository-relative")
        parts = [part for part in value.split("/") if part]
        if not parts or any(part == ".." for part in parts):
            raise ValueError(f"{field} contains unsafe path prefix: {raw!r}")
        value = "/".join(parts)
        if value in seen:
            raise ValueError(f"{field} contains duplicate path prefix: {value}")
        seen.add(value)
        normalized.append(value)

    if not normalized:
        raise ValueError(f"{field} must contain at least one path prefix")
    return tuple(sorted(normalized))


def _normalize_actions(values: Iterable[PilotAction | str]) -> tuple[PilotAction, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("allowed_actions must be an iterable")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError("allowed_actions must be iterable") from exc

    actions: list[PilotAction] = []
    seen: set[PilotAction] = set()
    for raw in iterator:
        try:
            action = PilotAction(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid pilot action: {raw!r}") from exc
        if action in seen:
            raise ValueError(f"duplicate pilot action: {action.value}")
        seen.add(action)
        actions.append(action)
    if not actions:
        raise ValueError("allowed_actions must not be empty")
    return tuple(sorted(actions, key=lambda item: item.value))


@dataclass(frozen=True, slots=True)
class PilotSafetyEnvelope:
    allowed_path_prefixes: tuple[str, ...]
    forbidden_path_prefixes: tuple[str, ...]
    allowed_actions: tuple[PilotAction, ...]
    max_tasks: int = 3
    max_consecutive_failures: int = 2
    require_human_activation: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_path_prefixes",
            _normalize_paths(self.allowed_path_prefixes, field="allowed_path_prefixes"),
        )
        object.__setattr__(
            self,
            "forbidden_path_prefixes",
            _normalize_paths(self.forbidden_path_prefixes, field="forbidden_path_prefixes"),
        )
        object.__setattr__(self, "allowed_actions", _normalize_actions(self.allowed_actions))

        if type(self.max_tasks) is not int or not 1 <= self.max_tasks <= 20:
            raise ValueError("max_tasks must be an integer between 1 and 20")
        if (
            type(self.max_consecutive_failures) is not int
            or not 1 <= self.max_consecutive_failures <= 5
        ):
            raise ValueError(
                "max_consecutive_failures must be an integer between 1 and 5"
            )
        if type(self.require_human_activation) is not bool:
            raise ValueError("require_human_activation must be a boolean")

        required_actions = {
            PilotAction.READ,
            PilotAction.RUN_VALIDATION,
            PilotAction.OPEN_PULL_REQUEST,
        }
        missing = required_actions - set(self.allowed_actions)
        if missing:
            raise ValueError(
                "production pilot must allow READ, RUN_VALIDATION, and OPEN_PULL_REQUEST"
            )

    def path_allowed(self, path: str) -> bool:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty repository-relative string")
        value = path.strip().replace("\\", "/")
        if value.startswith("/") or value.startswith("./"):
            raise ValueError("path must be repository-relative")
        parts = [part for part in value.split("/") if part]
        if not parts or any(part == ".." for part in parts):
            raise ValueError("path contains unsafe traversal")
        normalized = "/".join(parts)

        if any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in self.forbidden_path_prefixes
        ):
            return False
        return any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in self.allowed_path_prefixes
        )

    def action_allowed(self, action: PilotAction | str) -> bool:
        try:
            normalized = PilotAction(action)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid pilot action: {action!r}") from exc
        return normalized in self.allowed_actions

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "forbidden_path_prefixes": list(self.forbidden_path_prefixes),
            "allowed_actions": [action.value for action in self.allowed_actions],
            "max_tasks": self.max_tasks,
            "max_consecutive_failures": self.max_consecutive_failures,
            "require_human_activation": self.require_human_activation,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotSafetyEnvelope":
        if not isinstance(payload, dict):
            raise ValueError("pilot safety envelope must be a JSON object")
        required = {
            "allowed_path_prefixes",
            "forbidden_path_prefixes",
            "allowed_actions",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"pilot safety envelope missing keys: {sorted(missing)}")
        return cls(
            allowed_path_prefixes=tuple(payload["allowed_path_prefixes"]),
            forbidden_path_prefixes=tuple(payload["forbidden_path_prefixes"]),
            allowed_actions=tuple(payload["allowed_actions"]),
            max_tasks=payload.get("max_tasks", 3),
            max_consecutive_failures=payload.get("max_consecutive_failures", 2),
            require_human_activation=payload.get("require_human_activation", True),
        )


def _normalize_provider_ids(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must be an iterable of provider IDs")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError(f"{field} must be iterable") from exc

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in iterator:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} must contain non-empty provider IDs")
        value = raw.strip()
        if value in seen:
            raise ValueError(f"{field} contains duplicate provider ID: {value}")
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class PilotProviderPolicy:
    allowed_provider_ids: tuple[str, ...]
    preferred_provider_ids: tuple[str, ...]
    allow_fallback_before_session: bool = True
    sticky_after_session: bool = True

    def __post_init__(self) -> None:
        allowed = _normalize_provider_ids(
            self.allowed_provider_ids,
            field="allowed_provider_ids",
        )
        preferred = _normalize_provider_ids(
            self.preferred_provider_ids,
            field="preferred_provider_ids",
        )
        if any(provider_id not in allowed for provider_id in preferred):
            raise ValueError("preferred_provider_ids must be a subset of allowed_provider_ids")
        if type(self.allow_fallback_before_session) is not bool:
            raise ValueError("allow_fallback_before_session must be a boolean")
        if self.sticky_after_session is not True:
            raise ValueError("production pilot requires sticky_after_session=True")
        object.__setattr__(self, "allowed_provider_ids", allowed)
        object.__setattr__(self, "preferred_provider_ids", preferred)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_provider_ids": list(self.allowed_provider_ids),
            "preferred_provider_ids": list(self.preferred_provider_ids),
            "allow_fallback_before_session": self.allow_fallback_before_session,
            "sticky_after_session": self.sticky_after_session,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotProviderPolicy":
        if not isinstance(payload, dict):
            raise ValueError("pilot provider policy must be a JSON object")
        if "allowed_provider_ids" not in payload or "preferred_provider_ids" not in payload:
            raise ValueError(
                "pilot provider policy requires allowed_provider_ids and preferred_provider_ids"
            )
        return cls(
            allowed_provider_ids=tuple(payload["allowed_provider_ids"]),
            preferred_provider_ids=tuple(payload["preferred_provider_ids"]),
            allow_fallback_before_session=payload.get(
                "allow_fallback_before_session",
                True,
            ),
            sticky_after_session=payload.get("sticky_after_session", True),
        )


@dataclass(frozen=True, slots=True)
class PilotContract:
    pilot_id: str
    target: PilotTarget
    goal: str
    safety: PilotSafetyEnvelope
    provider_policy: PilotProviderPolicy
    acceptance_checks: tuple[PilotAcceptanceCheck, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("pilot contract schema_version must be 1")
        if not isinstance(self.pilot_id, str) or not _PILOT_ID.fullmatch(self.pilot_id):
            raise ValueError("pilot_id must be a lowercase slug")
        if not isinstance(self.target, PilotTarget):
            raise ValueError("target must be a PilotTarget")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("goal must be a non-empty string")
        if self.goal != self.goal.strip():
            raise ValueError("goal must not contain leading or trailing whitespace")
        if not isinstance(self.safety, PilotSafetyEnvelope):
            raise ValueError("safety must be a PilotSafetyEnvelope")
        if not isinstance(self.provider_policy, PilotProviderPolicy):
            raise ValueError("provider_policy must be a PilotProviderPolicy")

        raw_checks = self.acceptance_checks
        if not isinstance(raw_checks, tuple):
            try:
                raw_checks = tuple(raw_checks)
            except TypeError as exc:
                raise ValueError("acceptance_checks must be iterable") from exc
        if not raw_checks:
            raise ValueError("acceptance_checks must not be empty")
        seen: set[str] = set()
        normalized: list[PilotAcceptanceCheck] = []
        for check in raw_checks:
            if not isinstance(check, PilotAcceptanceCheck):
                raise ValueError("acceptance_checks must contain PilotAcceptanceCheck values")
            if check.check_id in seen:
                raise ValueError(f"duplicate acceptance check_id: {check.check_id}")
            seen.add(check.check_id)
            normalized.append(check)
        object.__setattr__(self, "acceptance_checks", tuple(normalized))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pilot_id": self.pilot_id,
            "target": self.target.to_dict(),
            "goal": self.goal,
            "safety": self.safety.to_dict(),
            "provider_policy": self.provider_policy.to_dict(),
            "acceptance_checks": [check.to_dict() for check in self.acceptance_checks],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotContract":
        if not isinstance(payload, dict):
            raise ValueError("pilot contract must be a JSON object")
        required = {
            "schema_version",
            "pilot_id",
            "target",
            "goal",
            "safety",
            "provider_policy",
            "acceptance_checks",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"pilot contract missing required keys: {sorted(missing)}")
        checks = payload["acceptance_checks"]
        if not isinstance(checks, list):
            raise ValueError("acceptance_checks must be a list")
        return cls(
            schema_version=payload["schema_version"],
            pilot_id=payload["pilot_id"],
            target=PilotTarget.from_dict(payload["target"]),
            goal=payload["goal"],
            safety=PilotSafetyEnvelope.from_dict(payload["safety"]),
            provider_policy=PilotProviderPolicy.from_dict(payload["provider_policy"]),
            acceptance_checks=tuple(
                PilotAcceptanceCheck.from_dict(item) for item in checks
            ),
        )
