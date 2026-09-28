from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re
from typing import Any

from .accepted_plan import AcceptedPlan
from .autonomous_planner import PlannerPolicy, ValidatedPlannerProposal, accept_validated_proposal
from .campaign import AutonomousCampaign, CampaignStatus
from .cycle import CycleTask
from .models import ProjectState, ProjectStatus
from .plan_compiler import compile_plan
from .task_graph import GraphTaskStatus, TaskGraph
from .task_graph_transition import transition_task

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class PlanningGoalRequest:
    request_id: str
    campaign_id: str
    id_prefix: str
    goal: str
    target_repository: str
    base_branch: str
    allowed_path_prefixes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("planning request schema_version must be 1")
        for field_name in ("request_id", "campaign_id", "id_prefix"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _ID.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a safe identifier")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("goal must be non-empty")
        if len(self.goal.strip()) > 4000:
            raise ValueError("goal exceeds trusted request budget")
        if not isinstance(self.target_repository, str) or _REPOSITORY.fullmatch(self.target_repository) is None:
            raise ValueError("target_repository must be owner/name")
        if not isinstance(self.base_branch, str) or not self.base_branch.strip() or "/" in self.base_branch.strip():
            raise ValueError("base_branch must be a simple non-empty branch name")
        if not self.allowed_path_prefixes or len(self.allowed_path_prefixes) > 8:
            raise ValueError("allowed_path_prefixes must contain 1..8 entries")
        normalized: list[str] = []
        for prefix in self.allowed_path_prefixes:
            if not isinstance(prefix, str) or not prefix.strip():
                raise ValueError("allowed path prefixes must be non-empty strings")
            value = prefix.strip().rstrip("/")
            if not value or value.startswith("/") or ".." in value.split("/") or "\\" in value:
                raise ValueError(f"unsafe allowed path prefix: {prefix}")
            normalized.append(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed path prefixes must be unique")
        object.__setattr__(self, "goal", " ".join(self.goal.split()))
        object.__setattr__(self, "base_branch", self.base_branch.strip())
        object.__setattr__(self, "allowed_path_prefixes", tuple(normalized))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "request_id": self.request_id,
            "campaign_id": self.campaign_id,
            "id_prefix": self.id_prefix,
            "goal": self.goal,
            "target_repository": self.target_repository,
            "base_branch": self.base_branch,
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanningGoalRequest":
        if not isinstance(payload, dict):
            raise ValueError("planning request must be a JSON object")
        allowed = {
            "schema_version",
            "request_id",
            "campaign_id",
            "id_prefix",
            "goal",
            "target_repository",
            "base_branch",
            "allowed_path_prefixes",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown planning request fields: {sorted(unknown)}")
        prefixes = payload.get("allowed_path_prefixes")
        if not isinstance(prefixes, list):
            raise ValueError("allowed_path_prefixes must be a list")
        return cls(
            schema_version=payload.get("schema_version", 0),
            request_id=str(payload.get("request_id", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            id_prefix=str(payload.get("id_prefix", "")),
            goal=str(payload.get("goal", "")),
            target_repository=str(payload.get("target_repository", "")),
            base_branch=str(payload.get("base_branch", "")),
            allowed_path_prefixes=tuple(str(item) for item in prefixes),
        )

    def fingerprint(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def planner_policy(self) -> PlannerPolicy:
        return PlannerPolicy(allowed_path_prefixes=self.allowed_path_prefixes)


@dataclass(frozen=True, slots=True)
class PlanningActivationBundle:
    request_fingerprint: str
    proposal_fingerprint: str
    policy_fingerprint: str
    accepted_plan: AcceptedPlan
    campaign: AutonomousCampaign
    graph: TaskGraph
    cycle_task: CycleTask
    state: ProjectState

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "request_fingerprint": self.request_fingerprint,
            "proposal_fingerprint": self.proposal_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "accepted_plan_fingerprint": self.accepted_plan.fingerprint,
            "campaign_id": self.campaign.campaign_id,
            "task_ids": list(self.campaign.task_ids),
            "first_task_id": self.cycle_task.task_id,
            "target_repository": self.state.metadata.get("target_repository"),
            "base_branch": self.cycle_task.starting_branch,
        }


def build_planning_activation(
    *,
    request: PlanningGoalRequest,
    validated: ValidatedPlannerProposal,
    previous_state: ProjectState,
) -> PlanningActivationBundle:
    if not isinstance(request, PlanningGoalRequest):
        raise ValueError("request must be a PlanningGoalRequest")
    if not isinstance(previous_state, ProjectState):
        raise ValueError("previous_state must be a ProjectState")
    if previous_state.current_task_id is not None:
        raise ValueError("cannot activate a new plan while another task is current")
    if previous_state.status in {
        ProjectStatus.RUNNING,
        ProjectStatus.HUMAN_WAIT,
        ProjectStatus.PAUSED_QUOTA,
        ProjectStatus.BLOCKED,
        ProjectStatus.FAILED,
    }:
        raise ValueError(f"cannot activate plan while project is {previous_state.status.value}")

    accepted = accept_validated_proposal(validated)
    campaign, graph = compile_plan(
        accepted.plan,
        campaign_id=request.campaign_id,
        starting_branch=request.base_branch,
    )
    if not graph.tasks:
        raise ValueError("compiled planner graph is empty")

    first = graph.tasks[0]
    if first.depends_on:
        raise ValueError("first planned task cannot have dependencies")
    graph = transition_task(
        graph,
        task_id=first.task_id,
        target_status=GraphTaskStatus.RUNNING,
    )
    campaign = replace(campaign, status=CampaignStatus.RUNNING)
    running_first = graph.require(first.task_id)

    metadata = dict(previous_state.metadata)
    metadata.update(
        {
            "campaign_id": campaign.campaign_id,
            "phase": "v1.2-autonomous-planner",
            "plan_source": "live:jules-planner",
            "planning_request_id": request.request_id,
            "planning_request_fingerprint": request.fingerprint(),
            "planner_proposal_fingerprint": validated.proposal_fingerprint,
            "planner_policy_fingerprint": validated.policy_fingerprint,
            "accepted_plan_fingerprint": accepted.fingerprint,
            "target_repository": request.target_repository,
            "target_base_branch": request.base_branch,
            "scheduler": "dag",
            "dag_blocked": False,
            "queue_exhausted": False,
            "next_required_human_action": None,
            "next_system_action": "zero-touch-start",
        }
    )
    state = ProjectState(
        schema_version=previous_state.schema_version,
        project_id=previous_state.project_id,
        status=ProjectStatus.READY,
        iteration=previous_state.iteration,
        current_task_id=running_first.task_id,
        completed_task_ids=list(previous_state.completed_task_ids),
        failed_task_ids=list(previous_state.failed_task_ids),
        provider=previous_state.provider,
        updated_at=previous_state.updated_at,
        metadata=metadata,
    )
    state.validate()

    return PlanningActivationBundle(
        request_fingerprint=request.fingerprint(),
        proposal_fingerprint=validated.proposal_fingerprint,
        policy_fingerprint=validated.policy_fingerprint,
        accepted_plan=accepted,
        campaign=campaign,
        graph=graph,
        cycle_task=running_first.task,
        state=state,
    )
