from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from .accepted_plan import AcceptedPlan
from .multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from .provider_registry import ProviderRegistry
from .provider_router import (
    ProviderAvailabilitySnapshot,
    RoutingDecision,
    RoutingOutcome,
    route_provider,
)
from .provider_routing import RoutingRequest


class MultiAgentPlanningError(ValueError):
    """Trusted multi-agent plan derivation failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MultiAgentDerivationPolicy:
    implementer_request: RoutingRequest
    reviewer_request: RoutingRequest
    reviewer_required: bool = True
    prefer_distinct_reviewer: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MultiAgentPlanningError(
                "unsupported multi-agent derivation policy schema version"
            )
        if not isinstance(self.implementer_request, RoutingRequest):
            raise MultiAgentPlanningError(
                "implementer_request must be RoutingRequest"
            )
        if not isinstance(self.reviewer_request, RoutingRequest):
            raise MultiAgentPlanningError(
                "reviewer_request must be RoutingRequest"
            )
        if type(self.reviewer_required) is not bool:
            raise MultiAgentPlanningError("reviewer_required must be a bool")
        if type(self.prefer_distinct_reviewer) is not bool:
            raise MultiAgentPlanningError(
                "prefer_distinct_reviewer must be a bool"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "implementer_request": self.implementer_request.to_dict(),
            "reviewer_request": self.reviewer_request.to_dict(),
            "reviewer_required": self.reviewer_required,
            "prefer_distinct_reviewer": self.prefer_distinct_reviewer,
            "execution_authority": False,
            "auto_dispatch": False,
            "merge_authority": False,
            "acceptance_authority": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def _routing_request_without_provider(
    registry: ProviderRegistry,
    request: RoutingRequest,
    provider_id: str,
) -> RoutingRequest | None:
    candidates = tuple(
        item.provider_id
        for item in registry.candidates(request)
        if item.provider_id != provider_id
    )
    if not candidates:
        return None

    allowed = set(candidates)
    preferred = tuple(
        item
        for item in request.preferred_provider_ids
        if item in allowed
    )
    return RoutingRequest(
        required_capabilities=request.required_capabilities,
        allowed_provider_ids=candidates,
        preferred_provider_ids=preferred,
    )


def _select_reviewer(
    *,
    registry: ProviderRegistry,
    policy: MultiAgentDerivationPolicy,
    availability: tuple[ProviderAvailabilitySnapshot, ...],
    implementer_provider_id: str,
) -> RoutingDecision:
    if policy.prefer_distinct_reviewer:
        distinct_request = _routing_request_without_provider(
            registry,
            policy.reviewer_request,
            implementer_provider_id,
        )
        if distinct_request is not None:
            distinct = route_provider(
                registry,
                distinct_request,
                availability,
            )
            if distinct.outcome is RoutingOutcome.SELECTED:
                return distinct

    return route_provider(
        registry,
        policy.reviewer_request,
        availability,
    )


def _assignment_id(
    *,
    role: AgentRole,
    provider_id: str,
    repository: str,
    source_sha: str,
    campaign_id: str,
    task_id: str,
    accepted_plan_fingerprint: str,
) -> str:
    digest = _fingerprint(
        {
            "role": role.value,
            "provider_id": provider_id,
            "repository": repository,
            "source_sha": source_sha,
            "campaign_id": campaign_id,
            "task_id": task_id,
            "accepted_plan_fingerprint": accepted_plan_fingerprint,
        }
    )
    return f"agent-{role.value.lower()}-{digest[:16]}"


def _plan_id(
    *,
    repository: str,
    source_sha: str,
    campaign_id: str,
    task_id: str,
    accepted_plan_fingerprint: str,
    assignments: tuple[AgentAssignment, ...],
    policy_fingerprint: str,
) -> str:
    digest = _fingerprint(
        {
            "repository": repository,
            "source_sha": source_sha,
            "campaign_id": campaign_id,
            "task_id": task_id,
            "accepted_plan_fingerprint": accepted_plan_fingerprint,
            "assignment_fingerprints": sorted(
                item.fingerprint() for item in assignments
            ),
            "policy_fingerprint": policy_fingerprint,
        }
    )
    return f"multi-agent-{digest[:24]}"


def derive_multi_agent_plan(
    *,
    accepted_plan: AcceptedPlan,
    repository: str,
    source_sha: str,
    campaign_id: str,
    task_id: str,
    registry: ProviderRegistry,
    availability: Iterable[ProviderAvailabilitySnapshot],
    accepted_plan_path: str,
    accepted_plan_evidence_fingerprint: str,
    provider_availability_path: str,
    provider_availability_evidence_fingerprint: str,
    policy: MultiAgentDerivationPolicy,
) -> MultiAgentPlan:
    if not isinstance(accepted_plan, AcceptedPlan):
        raise MultiAgentPlanningError("accepted_plan must be AcceptedPlan")
    if accepted_plan.status != "ACCEPTED":
        raise MultiAgentPlanningError(
            "multi-agent derivation requires ACCEPTED plan status"
        )
    accepted_plan.plan.validate()
    if not isinstance(registry, ProviderRegistry):
        raise MultiAgentPlanningError("registry must be ProviderRegistry")
    if not isinstance(policy, MultiAgentDerivationPolicy):
        raise MultiAgentPlanningError(
            "policy must be MultiAgentDerivationPolicy"
        )

    snapshots = tuple(availability)
    for snapshot in snapshots:
        if not isinstance(snapshot, ProviderAvailabilitySnapshot):
            raise MultiAgentPlanningError(
                "availability must contain ProviderAvailabilitySnapshot values"
            )

    task = next(
        (
            item
            for item in accepted_plan.plan.tasks
            if item.task_id == task_id
        ),
        None,
    )
    if task is None:
        raise MultiAgentPlanningError(
            "task_id is not present in the AcceptedPlan"
        )

    implementer = route_provider(
        registry,
        policy.implementer_request,
        snapshots,
    )
    if (
        implementer.outcome is not RoutingOutcome.SELECTED
        or implementer.selected_provider_id is None
    ):
        raise MultiAgentPlanningError(
            "no provider is available for IMPLEMENTER role"
        )

    evidence_paths = (
        accepted_plan_path,
        provider_availability_path,
    )
    evidence_fingerprints = (
        accepted_plan_evidence_fingerprint,
        provider_availability_evidence_fingerprint,
    )
    accepted_fingerprint = accepted_plan.fingerprint

    assignments: list[AgentAssignment] = [
        AgentAssignment(
            assignment_id=_assignment_id(
                role=AgentRole.IMPLEMENTER,
                provider_id=implementer.selected_provider_id,
                repository=repository,
                source_sha=source_sha,
                campaign_id=campaign_id,
                task_id=task_id,
                accepted_plan_fingerprint=accepted_fingerprint,
            ),
            role=AgentRole.IMPLEMENTER,
            provider_id=implementer.selected_provider_id,
            repository=repository,
            source_sha=source_sha,
            campaign_id=campaign_id,
            task_id=task_id,
            accepted_plan_fingerprint=accepted_fingerprint,
            objective=(
                f"Implement AcceptedPlan task {task.task_id}: {task.title}"
            ),
            evidence_paths=evidence_paths,
            evidence_fingerprints=evidence_fingerprints,
        )
    ]

    reviewer = _select_reviewer(
        registry=registry,
        policy=policy,
        availability=snapshots,
        implementer_provider_id=implementer.selected_provider_id,
    )
    if (
        reviewer.outcome is RoutingOutcome.SELECTED
        and reviewer.selected_provider_id is not None
    ):
        assignments.append(
            AgentAssignment(
                assignment_id=_assignment_id(
                    role=AgentRole.REVIEWER,
                    provider_id=reviewer.selected_provider_id,
                    repository=repository,
                    source_sha=source_sha,
                    campaign_id=campaign_id,
                    task_id=task_id,
                    accepted_plan_fingerprint=accepted_fingerprint,
                ),
                role=AgentRole.REVIEWER,
                provider_id=reviewer.selected_provider_id,
                repository=repository,
                source_sha=source_sha,
                campaign_id=campaign_id,
                task_id=task_id,
                accepted_plan_fingerprint=accepted_fingerprint,
                objective=(
                    f"Review AcceptedPlan task {task.task_id} against its "
                    "frozen acceptance criteria and trusted scope."
                ),
                evidence_paths=evidence_paths,
                evidence_fingerprints=evidence_fingerprints,
            )
        )
    elif policy.reviewer_required:
        raise MultiAgentPlanningError(
            "no provider is available for required REVIEWER role"
        )

    normalized = tuple(assignments)
    return MultiAgentPlan(
        plan_id=_plan_id(
            repository=repository,
            source_sha=source_sha,
            campaign_id=campaign_id,
            task_id=task_id,
            accepted_plan_fingerprint=accepted_fingerprint,
            assignments=normalized,
            policy_fingerprint=policy.fingerprint(),
        ),
        repository=repository,
        source_sha=source_sha,
        campaign_id=campaign_id,
        task_id=task_id,
        accepted_plan_fingerprint=accepted_fingerprint,
        assignments=normalized,
    )
