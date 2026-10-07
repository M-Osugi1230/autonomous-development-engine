from __future__ import annotations

from typing import Any

from .autonomous_planner import (
    AutonomousPlanningResult,
    PlannerDisposition,
    PlannerPolicy,
    PlannerProposal,
    PlannerValidationError,
    PlanningProvider,
    accept_validated_proposal,
    build_planner_prompt,
    validate_planner_proposal,
)
from .development_memory import DevelopmentMemoryPlannerContext


def ground_derived_plan_new_paths(
    proposal_payload: dict[str, Any],
    *,
    existing_paths: frozenset[str] | set[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Reconcile derived-plan path existence from trusted repository state.

    This function does not add, remove, or rewrite allowed paths. It only
    classifies already-proposed allowed paths as existing or new according to
    the trusted repository snapshot. The result is still subjected to the
    normal deterministic planner validator.
    """

    if not isinstance(proposal_payload, dict):
        raise PlannerValidationError("planner proposal must be a JSON object")
    if not isinstance(existing_paths, (frozenset, set, tuple)):
        raise PlannerValidationError(
            "existing_paths must be a set, frozenset, or tuple"
        )

    known_paths: set[str] = set()
    for path in existing_paths:
        if not isinstance(path, str) or not path:
            raise PlannerValidationError(
                "existing_paths must contain non-empty strings"
            )
        known_paths.add(path)

    grounded = PlannerProposal.from_dict(proposal_payload).canonical_dict()
    for task in grounded["tasks"]:
        allowed_paths = task["allowed_paths"]
        task["new_paths"] = [
            path for path in allowed_paths if path not in known_paths
        ]
    return grounded


def plan_high_level_goal_with_path_grounding(
    provider: PlanningProvider,
    *,
    high_level_goal: str,
    policy: PlannerPolicy,
    id_prefix: str = "auto",
    repository_context: str | None = None,
    development_memory_context: DevelopmentMemoryPlannerContext | None = None,
    existing_paths: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> AutonomousPlanningResult:
    """Plan normally, grounding only ADE-derived Jules plan-step proposals.

    Structured provider proposals remain untouched so their explicit
    ``new_paths`` declarations continue to be validated strictly. ADE-generated
    ``derived-plan-steps`` proposals are deterministic translations of Jules'
    native approval plan; for those proposals, trusted repository state is the
    authoritative source for whether an allowed path already exists.
    """

    prompt = build_planner_prompt(
        high_level_goal,
        policy,
        repository_context=repository_context,
        development_memory_context=development_memory_context,
    )
    raw = provider.propose(prompt)
    if not isinstance(raw, dict):
        raise PlannerValidationError("planning provider must return a JSON object")

    proposal_mode = getattr(provider, "last_proposal_mode", None)
    if proposal_mode == "derived-plan-steps" and existing_paths is not None:
        raw = ground_derived_plan_new_paths(
            raw,
            existing_paths=existing_paths,
        )

    validated = validate_planner_proposal(
        high_level_goal=high_level_goal,
        proposal_payload=raw,
        policy=policy,
        id_prefix=id_prefix,
        existing_paths=existing_paths,
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
