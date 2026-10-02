from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_planner import (
    PlannerDisposition,
    PlannerProposal,
    PlannerValidationError,
    plan_high_level_goal,
)
from ade.development_memory_planning import (
    DevelopmentMemoryPlanningBundle,
    build_planning_memory_bundle,
    build_planning_memory_bundle_from_store,
)
from ade.development_memory_store import DevelopmentMemoryStore
from ade.jules_planner import JulesPlannerConfig, JulesPlannerError, JulesPlanningProvider
from ade.models import ProjectState
from ade.planning_activation import PlanningGoalRequest, build_planning_activation
from ade.repository_intelligence import (
    RepositoryContentSummary,
    RepositoryImpactAnalysis,
    RepositoryPlannerContext,
    RepositoryRelationshipGraph,
    RepositorySnapshot,
    analyze_repository_impact,
    build_python_content_summary,
    build_repository_relationships,
    build_repository_snapshot,
    planner_repository_context,
    python_candidate_paths,
)
from github_client import GitHubClient, GitHubError
from jules_client import JulesClient, JulesError, JulesPrecondition, JulesQuota, JulesUnauthorized

REQUEST_PATH = Path(".autodev/planning-goal.json")
STATE_PATH = Path(".autodev/state.json")
STATUS_PATH = Path(".autodev/runtime/planning-status.json")
RESULT_PATH = Path(".autodev/runtime/autonomous-planner-result.json")
REMOTE_STATUS_PATH = ".autodev/runtime/planning-status.json"
REMOTE_EVIDENCE_PREFIX = ".autodev/planner-evidence"
REMOTE_REPOSITORY_INTELLIGENCE_PREFIX = ".autodev/repository-intelligence"

MAX_NON_QUOTA_ATTEMPTS = 3


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load(path)


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_error(exc: BaseException) -> str:
    value = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    return value[:256]


def _status(
    request: PlanningGoalRequest,
    *,
    state: str,
    attempt: int,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request.request_id,
        "request_fingerprint": request.fingerprint(),
        "state": state,
        "attempt": attempt,
        "reason": reason,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload


def _persist_status(gh: GitHubClient, payload: dict[str, Any]) -> None:
    gh.upsert_json_file(
        REMOTE_STATUS_PATH,
        payload,
        message=f"planner: {payload['request_id']} {str(payload['state']).lower()}",
    )
    _write_result(payload)


def _arm_capacity_retry(
    gh: GitHubClient,
    request: PlanningGoalRequest,
) -> None:
    try:
        gh.dispatch(
            "ade_planner_retry_arm",
            {
                "request_id": request.request_id,
                "request_fingerprint": request.fingerprint(),
                "source": "autonomous-planner-capacity-pause",
            },
        )
    except GitHubError as exc:
        print(
            "WARNING: planner capacity retry arm failed; cron watchdog remains fallback: "
            + _safe_error(exc),
            file=sys.stderr,
        )


def _previous_attempt(request: PlanningGoalRequest) -> tuple[int, dict[str, Any] | None]:
    previous = _optional(STATUS_PATH)
    if previous is None or previous.get("request_fingerprint") != request.fingerprint():
        return 0, None
    raw = previous.get("attempt", 0)
    attempt = raw if type(raw) is int and raw >= 0 else 0
    return attempt, previous


def _task_payload(task) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task.task_id,
        "title": task.title,
        "prompt": task.prompt,
        "starting_branch": task.starting_branch,
        "auto_create_pr": task.auto_create_pr,
        "timeout_seconds": task.timeout_seconds,
        "poll_interval_seconds": task.poll_interval_seconds,
    }


def _steps_hash(steps: tuple[dict[str, str], ...]) -> str:
    raw = json.dumps(list(steps), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _collect_repository_intelligence(
    gh: GitHubClient,
    request: PlanningGoalRequest,
) -> tuple[
    RepositorySnapshot,
    RepositoryContentSummary,
    RepositoryRelationshipGraph,
    RepositoryPlannerContext,
]:
    target_token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "").strip()
    reader = (
        GitHubClient(
            repository=request.target_repository,
            token=target_token,
        )
        if target_token
        else gh
    )
    try:
        source_sha = reader.get_branch_head_sha(
            request.target_repository,
            branch=request.base_branch,
        )
        paths = reader.list_tree_paths(
            request.target_repository,
            tree_sha=source_sha,
            max_entries=5000,
        )
    except GitHubError as exc:
        if (
            not target_token
            and request.target_repository != gh.repository
            and "GitHub HTTP 404:" in str(exc)
        ):
            raise GitHubError(
                "external target repository is not readable; configure "
                "ADE_TARGET_GITHUB_TOKEN for private repository access"
            ) from exc
        raise
    snapshot = build_repository_snapshot(
        repository=request.target_repository,
        base_branch=request.base_branch,
        source_sha=source_sha,
        paths=paths,
        max_paths=5000,
    )

    files: list[tuple[str, str, str]] = []
    for path in python_candidate_paths(
        snapshot,
        allowed_path_prefixes=request.allowed_path_prefixes,
        max_files=20,
    ):
        try:
            source, blob_sha = reader.get_text_file(
                request.target_repository,
                path=path,
                ref=source_sha,
                max_bytes=65536,
            )
        except GitHubError as exc:
            if "exceeds trusted byte budget" in str(exc):
                continue
            raise
        files.append((path, source, blob_sha))

    content_summary = build_python_content_summary(
        files,
        max_files=20,
        max_source_chars=100000,
    )
    relationship_graph = build_repository_relationships(content_summary)
    context = planner_repository_context(
        snapshot,
        allowed_path_prefixes=request.allowed_path_prefixes,
        content_summary=content_summary,
        relationship_graph=relationship_graph,
        max_files=200,
        max_summary_modules=20,
        max_relationships=100,
        max_chars=12000,
    )
    return snapshot, content_summary, relationship_graph, context


def _collect_development_memory(
    *,
    request: PlanningGoalRequest,
    snapshot: RepositorySnapshot,
    previous_state: ProjectState,
) -> DevelopmentMemoryPlanningBundle | None:
    store_path = Path(".autodev/development-memory.json")
    if store_path.exists():
        store = DevelopmentMemoryStore.from_dict(_load(store_path))
        stored_bundle = build_planning_memory_bundle_from_store(
            store=store,
            store_path=str(store_path),
            repository=request.target_repository,
            current_source_sha=snapshot.source_sha,
            max_results=8,
            max_chars=4000,
        )
        if stored_bundle is not None:
            return stored_bundle

    raw_path = previous_state.metadata.get("v1_4_graduation_evidence")
    if raw_path is None:
        return None
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("development memory evidence path is invalid")
    if "\\" in raw_path or raw_path.startswith("/"):
        raise ValueError("development memory evidence path is unsafe")
    parsed = PurePosixPath(raw_path)
    if "." in parsed.parts or ".." in parsed.parts or str(parsed) != raw_path:
        raise ValueError("development memory evidence path must be normalized")
    if not raw_path.startswith(".autodev/campaign-evidence/"):
        raise ValueError(
            "development memory evidence must remain inside trusted campaign evidence"
        )

    path = Path(raw_path)
    if not path.exists():
        raise ValueError("development memory evidence file is missing")
    evidence = _load(path)
    if evidence.get("target_repository") != request.target_repository:
        return None

    return build_planning_memory_bundle(
        evidence_path=raw_path,
        evidence_payload=evidence,
        repository=request.target_repository,
        current_source_sha=snapshot.source_sha,
        max_results=8,
        max_chars=4000,
    )


def _persist_activation(
    gh: GitHubClient,
    *,
    request: PlanningGoalRequest,
    result,
    bundle,
    provider: JulesPlanningProvider,
    snapshot: RepositorySnapshot,
    content_summary: RepositoryContentSummary,
    relationship_graph: RepositoryRelationshipGraph,
    repository_context: RepositoryPlannerContext,
    attempt: int,
    development_memory: DevelopmentMemoryPlanningBundle | None = None,
) -> None:
    proposal = PlannerProposal.from_dict(result.raw_proposal).canonical_dict()
    proposed_paths = tuple(
        sorted(
            {
                path
                for task in bundle.accepted_plan.plan.tasks
                for path in task.allowed_paths
            }
        )
    )
    impact_analysis: RepositoryImpactAnalysis = analyze_repository_impact(
        relationship_graph,
        changed_paths=proposed_paths,
        max_depth=3,
        max_results=100,
    )
    evidence = {
        "schema_version": 1,
        "request": request.to_dict(),
        "request_fingerprint": bundle.request_fingerprint,
        "provider": "jules",
        "provider_plan_step_count": len(provider.last_plan_steps),
        "provider_plan_steps_sha256": _steps_hash(provider.last_plan_steps),
        "proposal": proposal,
        "proposal_fingerprint": bundle.proposal_fingerprint,
        "policy_fingerprint": bundle.policy_fingerprint,
        "accepted_plan_fingerprint": bundle.accepted_plan.fingerprint,
        "campaign_id": bundle.campaign.campaign_id,
        "task_ids": list(bundle.campaign.task_ids),
        "planning_session_terminal_state": provider.last_observed_state,
        "provider_proposal_mode": getattr(provider, "last_proposal_mode", None),
        "provider_execution_boundary_crossed": bool(
            getattr(provider, "last_execution_boundary_crossed", False)
        ),
        "planning_only": not bool(
            getattr(provider, "last_execution_boundary_crossed", False)
        ),
        "workflow_run_id": (
            int(os.environ["GITHUB_RUN_ID"])
            if os.environ.get("GITHUB_RUN_ID", "").isdigit()
            else None
        ),
        "workflow_run_attempt": (
            int(os.environ["GITHUB_RUN_ATTEMPT"])
            if os.environ.get("GITHUB_RUN_ATTEMPT", "").isdigit()
            else None
        ),
        "plan_approved": False,
        "implementation_output_accepted": False,
        "repository_snapshot_fingerprint": snapshot.fingerprint(),
        "repository_context_fingerprint": repository_context.fingerprint,
        "repository_content_summary_fingerprint": content_summary.fingerprint(),
        "repository_relationship_graph_fingerprint": relationship_graph.fingerprint(),
        "repository_impact_analysis_fingerprint": impact_analysis.fingerprint(),
        "repository_source_sha": snapshot.source_sha,
        "development_memory": (
            development_memory.evidence_dict()
            if development_memory is not None
            else {
                "schema_version": 1,
                "used": False,
                "authority": "advisory-data-only",
                "reason": "no-trusted-memory-evidence-for-target",
            }
        ),
    }

    # AcceptedPlan is deliberately persisted last. Every canonical execution
    # file must reconcile before activation becomes visible. After the write,
    # request an explicit repository_dispatch because GitHub suppresses normal
    # workflow chaining from pushes created with GITHUB_TOKEN. The scheduled
    # Zero-Touch watchdog remains the bounded fallback if dispatch is unavailable.
    gh.upsert_json_file(
        ".autodev/campaign.json",
        bundle.campaign.to_dict(),
        message=f"planner: prepare campaign {request.campaign_id}",
    )
    gh.upsert_json_file(
        ".autodev/task-graph.json",
        bundle.graph.to_dict(),
        message=f"planner: prepare DAG {request.campaign_id}",
    )
    gh.upsert_json_file(
        ".autodev/cycle-task.json",
        _task_payload(bundle.cycle_task),
        message=f"planner: prepare first task {bundle.cycle_task.task_id}",
    )
    state_payload = bundle.state.to_dict()
    metadata = state_payload.setdefault("metadata", {})
    metadata["repository_intelligence_snapshot_fingerprint"] = snapshot.fingerprint()
    metadata["repository_intelligence_context_fingerprint"] = repository_context.fingerprint
    metadata["repository_intelligence_content_fingerprint"] = content_summary.fingerprint()
    metadata["repository_intelligence_relationship_fingerprint"] = relationship_graph.fingerprint()
    metadata["repository_intelligence_impact_fingerprint"] = impact_analysis.fingerprint()
    metadata["repository_intelligence_source_sha"] = snapshot.source_sha
    if development_memory is not None:
        memory_evidence = development_memory.evidence_dict()
        metadata["development_memory_source_evidence_fingerprint"] = (
            memory_evidence["source_evidence_fingerprint"]
        )
        metadata["development_memory_resolution_fingerprint"] = (
            memory_evidence["resolution_fingerprint"]
        )
        metadata["development_memory_retrieval_fingerprint"] = (
            memory_evidence["retrieval_fingerprint"]
        )
        metadata["development_memory_context_fingerprint"] = (
            memory_evidence["context_fingerprint"]
        )
        metadata["development_memory_retrieved_record_count"] = (
            memory_evidence["retrieved_record_count"]
        )
        metadata["development_memory_source_sha"] = snapshot.source_sha
    state_payload["updated_at"] = datetime.now(UTC).isoformat()
    gh.upsert_json_file(
        ".autodev/state.json",
        state_payload,
        message=f"planner: prepare state {request.campaign_id}",
    )
    gh.upsert_json_file(
        f"{REMOTE_REPOSITORY_INTELLIGENCE_PREFIX}/{request.request_id}.json",
        {
            "schema_version": 1,
            "snapshot": snapshot.canonical_dict(),
            "snapshot_fingerprint": snapshot.fingerprint(),
            "content_summary": content_summary.canonical_dict(),
            "content_summary_fingerprint": content_summary.fingerprint(),
            "relationship_graph": relationship_graph.canonical_dict(),
            "relationship_graph_fingerprint": relationship_graph.fingerprint(),
            "impact_analysis": impact_analysis.canonical_dict(),
            "impact_analysis_fingerprint": impact_analysis.fingerprint(),
            "planner_context": repository_context.payload,
            "planner_context_fingerprint": repository_context.fingerprint,
        },
        message=f"repository intelligence: {request.request_id}",
    )
    gh.upsert_json_file(
        f"{REMOTE_EVIDENCE_PREFIX}/{request.request_id}.json",
        evidence,
        message=f"planner: evidence {request.request_id}",
    )
    accepted_status = _status(
        request,
        state="ACCEPTED",
        attempt=attempt,
        reason="trusted-plan-accepted",
        extra={
            "proposal_fingerprint": bundle.proposal_fingerprint,
            "accepted_plan_fingerprint": bundle.accepted_plan.fingerprint,
            "campaign_id": bundle.campaign.campaign_id,
            "first_task_id": bundle.cycle_task.task_id,
            "development_memory_context_fingerprint": (
                development_memory.context.fingerprint
                if development_memory is not None
                else None
            ),
            "development_memory_record_count": (
                development_memory.retrieved_record_count
                if development_memory is not None
                else 0
            ),
        },
    )
    gh.upsert_json_file(
        REMOTE_STATUS_PATH,
        accepted_status,
        message=f"planner: accepted {request.request_id}",
    )
    gh.upsert_json_file(
        ".autodev/accepted-plan.json",
        bundle.accepted_plan.to_dict(),
        message=f"planner: activate accepted plan {request.request_id}",
    )
    try:
        gh.dispatch(
            "ade_zero_touch_start",
            {
                "task_id": bundle.cycle_task.task_id,
                "campaign_id": bundle.campaign.campaign_id,
                "request_id": request.request_id,
                "source": "autonomous-planner",
            },
        )
    except GitHubError as exc:
        print(
            "WARNING: immediate Zero-Touch dispatch failed; scheduled watchdog remains armed: "
            + _safe_error(exc),
            file=sys.stderr,
        )
    _write_result(accepted_status)


def main() -> int:
    if not REQUEST_PATH.exists():
        result = {
            "schema_version": 1,
            "state": "NOOP",
            "reason": "planning-goal-missing",
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    request = PlanningGoalRequest.from_dict(_load(REQUEST_PATH))
    previous_attempt, previous = _previous_attempt(request)
    if previous is not None and previous.get("state") in {"ACCEPTED", "HUMAN_WAIT"}:
        result = {
            **previous,
            "noop": True,
            "reason": "planning-request-already-terminal",
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    gh = GitHubClient()
    attempt = previous_attempt + 1
    owner, repo = request.target_repository.split("/", 1)

    try:
        client = JulesClient()
        source = client.find_github_source(owner, repo)
        if source is None:
            payload = _status(
                request,
                state="HUMAN_WAIT",
                attempt=attempt,
                reason="target-repository-not-visible-to-jules",
            )
            _persist_status(gh, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        source_name = source.get("name")
        if not isinstance(source_name, str) or not source_name.strip():
            raise JulesPlannerError("Jules target source has no resource name")

        (
            snapshot,
            content_summary,
            relationship_graph,
            repository_context,
        ) = _collect_repository_intelligence(
            gh,
            request,
        )
        previous_state = ProjectState.from_dict(_load(STATE_PATH))
        development_memory = _collect_development_memory(
            request=request,
            snapshot=snapshot,
            previous_state=previous_state,
        )

        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name=source_name,
                starting_branch=request.base_branch,
                title=f"ADE planner: {request.request_id}",
                allowed_path_prefixes=request.allowed_path_prefixes,
                required_human_boundaries=request.planner_policy().required_human_boundaries,
            ),
        )
        result = plan_high_level_goal(
            provider,
            high_level_goal=request.goal,
            policy=request.planner_policy(),
            id_prefix=request.id_prefix,
            repository_context=repository_context.serialized,
            development_memory_context=(
                development_memory.context
                if development_memory is not None
                else None
            ),
            existing_paths=frozenset(snapshot.paths),
        )

        if result.validated.disposition is PlannerDisposition.HUMAN_WAIT:
            proposal = PlannerProposal.from_dict(result.raw_proposal).canonical_dict()
            payload = _status(
                request,
                state="HUMAN_WAIT",
                attempt=attempt,
                reason="planner-proposal-requires-human",
                extra={
                    "human_reasons": list(result.validated.human_reasons),
                    "proposal_fingerprint": result.validated.proposal_fingerprint,
                },
            )
            gh.upsert_json_file(
                f"{REMOTE_EVIDENCE_PREFIX}/{request.request_id}.json",
                {
                    "schema_version": 1,
                    "request": request.to_dict(),
                    "provider": "jules",
                    "proposal": proposal,
                    "proposal_fingerprint": result.validated.proposal_fingerprint,
                    "policy_fingerprint": result.validated.policy_fingerprint,
                    "planning_only": True,
                    "plan_approved": False,
                    "development_memory": (
                        development_memory.evidence_dict()
                        if development_memory is not None
                        else {
                            "schema_version": 1,
                            "used": False,
                            "authority": "advisory-data-only",
                            "reason": "no-trusted-memory-evidence-for-target",
                        }
                    ),
                    "disposition": "HUMAN_WAIT",
                },
                message=f"planner: human wait evidence {request.request_id}",
            )
            _persist_status(gh, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        if result.accepted_plan is None:
            raise PlannerValidationError("accepted planner result did not produce AcceptedPlan")

        bundle = build_planning_activation(
            request=request,
            validated=result.validated,
            previous_state=previous_state,
        )
        _persist_activation(
            gh,
            request=request,
            result=result,
            bundle=bundle,
            provider=provider,
            snapshot=snapshot,
            content_summary=content_summary,
            relationship_graph=relationship_graph,
            repository_context=repository_context,
            development_memory=development_memory,
            attempt=attempt,
        )
        print(json.dumps({
            "schema_version": 1,
            "state": "ACCEPTED",
            "request_id": request.request_id,
            "campaign_id": bundle.campaign.campaign_id,
            "task_count": len(bundle.campaign.task_ids),
            "planning_only": True,
            "plan_approved": False,
            "development_memory_record_count": (
                development_memory.retrieved_record_count
                if development_memory is not None
                else 0
            ),
        }, sort_keys=True))
        return 0

    except (JulesQuota, JulesPrecondition) as exc:
        # Provider capacity is resumable and does not consume the non-quota
        # planner failure budget. The scheduled watchdog will retry.
        payload = _status(
            request,
            state="PAUSED_QUOTA",
            attempt=previous_attempt,
            reason="planner-provider-capacity",
            extra={"detail": _safe_error(exc)},
        )
        _persist_status(gh, payload)
        _arm_capacity_retry(gh, request)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except JulesUnauthorized as exc:
        payload = _status(
            request,
            state="HUMAN_WAIT",
            attempt=attempt,
            reason="planner-provider-authentication",
            extra={"detail": _safe_error(exc)},
        )
        _persist_status(gh, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (JulesPlannerError, PlannerValidationError, JulesError, GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        terminal = attempt >= MAX_NON_QUOTA_ATTEMPTS
        payload = _status(
            request,
            state="HUMAN_WAIT" if terminal else "REPLAN",
            attempt=attempt,
            reason="planner-failure-budget-exhausted" if terminal else "planner-retryable-failure",
            extra={"detail": _safe_error(exc)},
        )
        _persist_status(gh, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
