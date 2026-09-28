from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_planner import (
    PlannerDisposition,
    PlannerProposal,
    PlannerValidationError,
    plan_high_level_goal,
)
from ade.jules_planner import JulesPlannerConfig, JulesPlannerError, JulesPlanningProvider
from ade.models import ProjectState
from ade.planning_activation import PlanningGoalRequest, build_planning_activation
from github_client import GitHubClient, GitHubError
from jules_client import JulesClient, JulesError, JulesPrecondition, JulesQuota, JulesUnauthorized

REQUEST_PATH = Path(".autodev/planning-goal.json")
STATE_PATH = Path(".autodev/state.json")
STATUS_PATH = Path(".autodev/runtime/planning-status.json")
RESULT_PATH = Path(".autodev/runtime/autonomous-planner-result.json")
REMOTE_STATUS_PATH = ".autodev/runtime/planning-status.json"
REMOTE_EVIDENCE_PREFIX = ".autodev/planner-evidence"

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


def _persist_activation(
    gh: GitHubClient,
    *,
    request: PlanningGoalRequest,
    result,
    bundle,
    provider: JulesPlanningProvider,
    attempt: int,
) -> None:
    proposal = PlannerProposal.from_dict(result.raw_proposal).canonical_dict()
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
        "planning_only": True,
        "plan_approved": False,
    }

    # AcceptedPlan is deliberately persisted last. Its main-branch push is the
    # Zero-Touch Start trigger, so every canonical execution file must already
    # reconcile before that final write is visible.
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
    state_payload["updated_at"] = datetime.now(UTC).isoformat()
    gh.upsert_json_file(
        ".autodev/state.json",
        state_payload,
        message=f"planner: prepare state {request.campaign_id}",
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
                    "disposition": "HUMAN_WAIT",
                },
                message=f"planner: human wait evidence {request.request_id}",
            )
            _persist_status(gh, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        if result.accepted_plan is None:
            raise PlannerValidationError("accepted planner result did not produce AcceptedPlan")

        previous_state = ProjectState.from_dict(_load(STATE_PATH))
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
        }, sort_keys=True))
        return 0

    except (JulesQuota, JulesPrecondition) as exc:
        # Provider capacity is resumable and does not consume the non-quota
        # planner failure budget. The hourly workflow will retry.
        payload = _status(
            request,
            state="PAUSED_QUOTA",
            attempt=previous_attempt,
            reason="planner-provider-capacity",
            extra={"detail": _safe_error(exc)},
        )
        _persist_status(gh, payload)
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
