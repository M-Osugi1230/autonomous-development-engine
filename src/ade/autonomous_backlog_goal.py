from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .autonomous_backlog import AutonomousBacklog, AutonomousBacklogError
from .autonomous_backlog_resolution import AutonomousBacklogResolution, BacklogResolutionState
from .autonomous_backlog_selection import BacklogSelection
from .planning_activation import PlanningGoalRequest


_BRANCH = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_PREFIX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BacklogPlanningPolicy:
    repository: str
    base_branch: str
    allowed_path_prefixes: tuple[str, ...]
    request_prefix: str = "abg"
    min_tasks: int = 1
    max_tasks: int = 4
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported backlog planning policy version")
        if not isinstance(self.repository, str) or "/" not in self.repository:
            raise AutonomousBacklogError("planning policy repository must be owner/name")
        if not isinstance(self.base_branch, str) or _BRANCH.fullmatch(self.base_branch) is None:
            raise AutonomousBacklogError("planning policy base_branch is invalid")
        if not isinstance(self.request_prefix, str) or _PREFIX.fullmatch(self.request_prefix) is None:
            raise AutonomousBacklogError("planning policy request_prefix is invalid")
        if type(self.min_tasks) is not int or type(self.max_tasks) is not int:
            raise AutonomousBacklogError("planning policy task bounds must be integers")
        if self.min_tasks < 1 or self.max_tasks < self.min_tasks or self.max_tasks > 8:
            raise AutonomousBacklogError("planning policy task bounds are invalid")
        if not self.allowed_path_prefixes or len(self.allowed_path_prefixes) > 8:
            raise AutonomousBacklogError("planning policy needs 1..8 allowed roots")
        normalized: list[str] = []
        for raw in self.allowed_path_prefixes:
            if not isinstance(raw, str) or not raw.strip():
                raise AutonomousBacklogError("planning policy path root is invalid")
            value = raw.strip().rstrip("/")
            if (
                not value
                or value.startswith("/")
                or "\\" in value
                or ".." in value.split("/")
                or value.startswith(".github")
                or value.startswith(".autodev")
                or value.startswith(".env")
                or value.startswith("secrets")
                or value.startswith("credentials")
            ):
                raise AutonomousBacklogError("planning policy path root is unsafe")
            normalized.append(value)
        if len(set(normalized)) != len(normalized):
            raise AutonomousBacklogError("planning policy path roots must be unique")
        object.__setattr__(self, "allowed_path_prefixes", tuple(normalized))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "request_prefix": self.request_prefix,
            "min_tasks": self.min_tasks,
            "max_tasks": self.max_tasks,
            "scope_source": "trusted-backlog-planning-policy-v1",
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class BacklogGoalHandoff:
    candidate_id: str
    candidate_fingerprint: str
    selection_fingerprint: str
    resolution_fingerprint: str
    policy_fingerprint: str
    request: PlanningGoalRequest
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported Goal handoff version")
        for value in (
            self.candidate_fingerprint,
            self.selection_fingerprint,
            self.resolution_fingerprint,
            self.policy_fingerprint,
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise AutonomousBacklogError("Goal handoff fingerprints must be sha256")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "selection_fingerprint": self.selection_fingerprint,
            "resolution_fingerprint": self.resolution_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "planning_goal_request": self.request.to_dict(),
            "handoff_target": "AutonomousPlanner",
            "execution_authority": False,
            "accepted_plan_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def build_planning_goal_handoff(
    backlog: AutonomousBacklog,
    resolution: AutonomousBacklogResolution,
    selection: BacklogSelection,
    *,
    policy: BacklogPlanningPolicy,
) -> BacklogGoalHandoff:
    if not isinstance(backlog, AutonomousBacklog):
        raise AutonomousBacklogError("backlog must be AutonomousBacklog")
    if not isinstance(resolution, AutonomousBacklogResolution):
        raise AutonomousBacklogError("resolution must be AutonomousBacklogResolution")
    if not isinstance(selection, BacklogSelection):
        raise AutonomousBacklogError("selection must be BacklogSelection")
    if not isinstance(policy, BacklogPlanningPolicy):
        raise AutonomousBacklogError("policy must be BacklogPlanningPolicy")
    if selection.backlog_fingerprint != backlog.fingerprint():
        raise AutonomousBacklogError("selection does not bind backlog")
    if selection.resolution_fingerprint != resolution.fingerprint():
        raise AutonomousBacklogError("selection does not bind resolution")
    if selection.repository != policy.repository:
        raise AutonomousBacklogError("planning policy repository mismatch")
    if selection.selected_candidate_id is None:
        raise AutonomousBacklogError("no eligible candidate was selected")

    candidates = {candidate.candidate_id: candidate for candidate in backlog.candidates}
    candidate = candidates.get(selection.selected_candidate_id)
    if candidate is None:
        raise AutonomousBacklogError("selected candidate is missing from backlog")
    entry = resolution.entry_for(candidate.candidate_id)
    if entry.state is not BacklogResolutionState.CURRENT:
        raise AutonomousBacklogError("selected candidate is not CURRENT")
    if candidate.human_only:
        raise AutonomousBacklogError("human-only candidate cannot become PlanningGoal")
    if candidate.repository != policy.repository:
        raise AutonomousBacklogError("selected candidate repository mismatch")
    if candidate.source_sha != selection.source_sha:
        raise AutonomousBacklogError("selected candidate source SHA mismatch")

    digest = hashlib.sha256(
        (
            candidate.candidate_id
            + ":"
            + candidate.fingerprint()
            + ":"
            + policy.fingerprint()
        ).encode("utf-8")
    ).hexdigest()[:16]
    request_id = f"{policy.request_prefix}-request-{digest}"
    campaign_id = f"{policy.request_prefix}-campaign-{digest}"
    id_prefix = f"{policy.request_prefix}-{digest[:10]}"
    goal = f"Resolve trusted Autonomous Backlog candidate: {candidate.statement}"

    request = PlanningGoalRequest(
        request_id=request_id,
        campaign_id=campaign_id,
        id_prefix=id_prefix,
        goal=goal,
        target_repository=policy.repository,
        base_branch=policy.base_branch,
        allowed_path_prefixes=policy.allowed_path_prefixes,
        min_tasks=policy.min_tasks,
        max_tasks=policy.max_tasks,
    )
    return BacklogGoalHandoff(
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=candidate.fingerprint(),
        selection_fingerprint=selection.fingerprint(),
        resolution_fingerprint=resolution.fingerprint(),
        policy_fingerprint=policy.fingerprint(),
        request=request,
    )
